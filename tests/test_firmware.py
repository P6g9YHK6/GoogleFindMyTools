import asyncio
import json

import webui.esp_idf_provisioning as esp_idf_provisioning
import webui.firmware_build as firmware_build
import webui.firmware_store as firmware_store


def _reset_state():
    firmware_build._state.update(
        phase="idle", message="", percent=0, error=None,
        artifact_path=None, download_name=None,
    )


def test_firmware_page(client):
    resp = client.get("/firmware")
    assert resp.status_code == 200


def test_zephyr_readme_page(client):
    resp = client.get("/firmware/zephyr-readme")
    assert resp.status_code == 200


async def test_start_rejects_bad_board():
    _reset_state()
    result = await firmware_build.start("not-a-board", "a" * 40)
    assert result["started"] is False
    assert firmware_build._state["phase"] == "idle"  # never touched


async def test_start_rejects_bad_eid():
    _reset_state()
    result = await firmware_build.start("esp32", "not-hex")
    assert result["started"] is False
    assert firmware_build._state["phase"] == "idle"


async def test_run_build_fails_gracefully_when_esp_idf_provisioning_fails(monkeypatch):
    _reset_state()

    async def fake_provision(on_progress=None):
        raise RuntimeError("git clone failed: could not resolve host")

    monkeypatch.setattr(esp_idf_provisioning, "provision", fake_provision)

    called = False

    async def fake_exec(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("should never spawn idf.py when provisioning fails")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await firmware_build._run_build("esp32", "a" * 40)

    assert called is False
    state = firmware_build.get_state()
    assert state["phase"] == "error"
    assert "git clone failed" in state["error"]


async def test_run_build_skips_set_target_for_esp32(monkeypatch):
    """idf.py set-target forces a fullclean + full sdkconfig regen from bare
    Kconfig defaults - fine for esp32c3 (there's a sdkconfig.defaults.esp32c3
    to regenerate from), but esp32's checked-in sdkconfig already has custom
    options (CONFIG_BT_ENABLED, Bluedroid, ...) main.c depends on baked in,
    with no sdkconfig.defaults.esp32 to restore them from - running
    set-target there silently disables BT and breaks the build. Regression
    test for exactly that, caught building against a live container."""
    _reset_state()

    async def fake_provision(on_progress=None):
        pass

    async def fake_get_env():
        return {}

    monkeypatch.setattr(esp_idf_provisioning, "provision", fake_provision)
    monkeypatch.setattr(esp_idf_provisioning, "get_env", fake_get_env)
    monkeypatch.setattr(esp_idf_provisioning, "idf_py_path", lambda: "idf.py")

    calls = []

    async def fake_run_cmd(cmd, env, cwd, phase, base_percent, cap_percent):
        calls.append(cmd)

    monkeypatch.setattr(firmware_build, "_run_cmd", fake_run_cmd)

    await firmware_build._run_build("esp32", "a" * 40)

    assert all("set-target" not in cmd for cmd in calls)
    assert any("build" in cmd for cmd in calls)


async def test_run_build_runs_set_target_for_esp32c3(monkeypatch):
    _reset_state()

    async def fake_provision(on_progress=None):
        pass

    async def fake_get_env():
        return {}

    monkeypatch.setattr(esp_idf_provisioning, "provision", fake_provision)
    monkeypatch.setattr(esp_idf_provisioning, "get_env", fake_get_env)
    monkeypatch.setattr(esp_idf_provisioning, "idf_py_path", lambda: "idf.py")

    calls = []

    async def fake_run_cmd(cmd, env, cwd, phase, base_percent, cap_percent):
        calls.append(cmd)

    monkeypatch.setattr(firmware_build, "_run_cmd", fake_run_cmd)

    await firmware_build._run_build("esp32c3", "a" * 40)

    assert calls[0][-2:] == ["set-target", "esp32c3"]


async def test_start_refuses_concurrent_build(monkeypatch):
    _reset_state()
    firmware_build._state["phase"] = "building"
    result = await firmware_build.start("esp32", "a" * 40)
    assert result["started"] is False
    _reset_state()


async def test_merge_bin_drives_esptool_from_flasher_args(monkeypatch, tmp_path):
    """idf.py's own "merge-bin" action doesn't exist in ESP-IDF 5.1 at all
    (added in a later release) - regression test for driving esptool.py
    directly from build/flasher_args.json instead, which has been stable
    across versions."""
    src_dir = tmp_path / "ESP32Firmware"
    build_dir = src_dir / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "flasher_args.json").write_text(json.dumps({
        "flash_settings": {"flash_mode": "dio", "flash_size": "2MB", "flash_freq": "40m"},
        "flash_files": {
            "0x1000": "bootloader/bootloader.bin",
            "0x10000": "ESPFindMy.bin",
            "0x8000": "partition_table/partition-table.bin",
        },
        "extra_esptool_args": {"chip": "esp32"},
    }))

    calls = []

    async def fake_run_cmd(cmd, env, cwd, phase, base_percent, cap_percent):
        calls.append((cmd, cwd))

    monkeypatch.setattr(firmware_build, "_run_cmd", fake_run_cmd)

    artifact_path = src_dir / "artifact.bin"
    await firmware_build._merge_bin({}, src_dir, artifact_path)

    assert len(calls) == 1
    cmd, cwd = calls[0]
    assert cmd[:3] == ["esptool.py", "--chip", "esp32"]
    assert "merge_bin" in cmd
    assert "--output" in cmd and str(artifact_path) in cmd
    assert "0x1000" in cmd and "bootloader/bootloader.bin" in cmd
    assert cwd == build_dir


def test_write_build_config_esp32(tmp_path):
    src = tmp_path / "ESP32Firmware" / "main"
    src.mkdir(parents=True)

    firmware_build._write_build_config(
        tmp_path / "ESP32Firmware", "esp32", "b" * 40, "My Tracker",
        adv_interval_ms=100, tx_power_dbm=-6, tracking_protection=False,
    )

    text = (src / "build_config.h").read_text()
    assert f'#define GFMT_EID_STRING "{"b" * 40}"' in text
    assert '#define GFMT_DEVICE_NAME "My Tracker"' in text
    assert "#define GFMT_ADV_FRAME_TYPE 0x40" in text  # protection off
    assert "#define GFMT_ADV_INTERVAL_UNITS 0x00a0" in text  # 100ms / 0.625ms
    assert "#define GFMT_TX_POWER_LEVEL ESP_PWR_LVL_N6" in text


def test_write_build_config_esp32c3_omits_tx_power(tmp_path):
    src = tmp_path / "ESP32Firmware" / "main"
    src.mkdir(parents=True)

    firmware_build._write_build_config(
        tmp_path / "ESP32Firmware", "esp32c3", "b" * 40, "My Tracker",
        adv_interval_ms=20, tx_power_dbm=9, tracking_protection=True,
    )

    text = (src / "build_config.h").read_text()
    assert "#define GFMT_ADV_FRAME_TYPE 0x41" in text  # protection on
    assert "GFMT_TX_POWER_LEVEL" not in text  # ESP32-only, not wired up for C3 yet


def test_validate_device_name():
    assert firmware_build._validate_device_name("Tracker") is None
    assert firmware_build._validate_device_name("") is not None
    assert firmware_build._validate_device_name("x" * 21) is not None
    assert firmware_build._validate_device_name('bad"name') is not None


def test_validate_adv_interval():
    assert firmware_build._validate_adv_interval(20) is None
    assert firmware_build._validate_adv_interval(10240) is None
    assert firmware_build._validate_adv_interval(19) is not None
    assert firmware_build._validate_adv_interval(10241) is not None


def test_validate_tx_power():
    assert firmware_build._validate_tx_power(9) is None
    assert firmware_build._validate_tx_power(1) is not None


async def test_start_rejects_bad_device_name():
    _reset_state()
    result = await firmware_build.start("esp32", "a" * 40, device_name="")
    assert result["started"] is False
    assert firmware_build._state["phase"] == "idle"


def test_firmware_store_round_trip():
    assert firmware_store.list_registered() == []
    firmware_store.record_registration("a" * 40, 1700000000)
    firmware_store.record_registration("b" * 40, 1700000100)

    entries = firmware_store.list_registered()
    assert [e["eid_hex"] for e in entries] == ["b" * 40, "a" * 40]  # newest first
    # New registrations already carry the default build settings.
    assert entries[0]["device_name"] == firmware_store.DEFAULT_BUILD_SETTINGS["device_name"]


def test_firmware_store_backfills_defaults_for_legacy_entries():
    firmware_store._save_unlocked([{"eid_hex": "c" * 40, "pair_date": 1700000200}])

    entries = firmware_store.list_registered()

    assert entries[0]["eid_hex"] == "c" * 40
    assert entries[0]["device_name"] == firmware_store.DEFAULT_BUILD_SETTINGS["device_name"]
    assert entries[0]["tracking_protection"] is True


def test_record_build_settings_updates_existing_entry():
    firmware_store.record_registration("d" * 40, 1700000300)

    firmware_store.record_build_settings("d" * 40, "Renamed", 100, -3, False)

    entries = firmware_store.list_registered()
    updated = next(e for e in entries if e["eid_hex"] == "d" * 40)
    assert updated["device_name"] == "Renamed"
    assert updated["adv_interval_ms"] == 100
    assert updated["tx_power_dbm"] == -3
    assert updated["tracking_protection"] is False


def test_record_build_settings_inserts_when_eid_unknown():
    firmware_store.record_build_settings("e" * 40, "Hand-typed", 40, 0, True)

    entries = firmware_store.list_registered()
    assert any(e["eid_hex"] == "e" * 40 and e["device_name"] == "Hand-typed" for e in entries)


def test_register_submit_records_eid_for_firmware_page(client):
    client.post("/register")
    entries = firmware_store.list_registered()
    assert any(e["eid_hex"] == "deadbeef" for e in entries)
