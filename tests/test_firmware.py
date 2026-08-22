import asyncio
import json

import yaml

import webui.esp_idf_provisioning as esp_idf_provisioning
import webui.firmware_build as firmware_build
import webui.firmware_store as firmware_store
from webui import config


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
    # ESP-IDF doesn't auto-apply a sdkconfig.defaults.<target> file just
    # from its name - it has to be spelled out via -D SDKCONFIG_DEFAULTS,
    # otherwise CONFIG_BT_ENABLED/CONFIG_BT_NIMBLE_ENABLED never get set and
    # main.c fails to compile on a missing esp_nimble_hci.h. Regression test
    # for exactly that, caught building against a live container.
    assert "SDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32c3" in calls[0]


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
    firmware_store._save_unlocked({"entries": [{"eid_hex": "c" * 40, "pair_date": 1700000200}]})

    entries = firmware_store.list_registered()

    assert entries[0]["eid_hex"] == "c" * 40
    assert entries[0]["device_name"] == firmware_store.DEFAULT_BUILD_SETTINGS["device_name"]
    assert entries[0]["tracking_protection"] is True


def test_firmware_store_identity_round_trip():
    firmware_store.record_identity("My Keys", "DEVICE_TYPE_KEYS", "Acme", "Tag v2",
                                    "https://example.com/tag.png", True)

    identity = firmware_store.load_last_identity()

    assert identity == {
        "display_name": "My Keys", "device_type": "DEVICE_TYPE_KEYS",
        "manufacturer_name": "Acme", "model_name": "Tag v2",
        "image_url": "https://example.com/tag.png",
        "experimental_official_app_compat": True,
    }


def test_firmware_store_identity_survives_legacy_list_shaped_file():
    # The file shape before last_identity existed was a bare list, not
    # {"entries": [...], "last_identity": {...}} - both readers must still
    # work against it without raising, and load_last_identity() falls back
    # to defaults since a legacy file never had one.
    firmware_store._save_unlocked({"entries": [{"eid_hex": "f" * 40, "pair_date": 1700000400}]})
    with open(config.REGISTERED_TRACKERS_PATH) as f:
        raw = yaml.safe_load(f)
    with open(config.REGISTERED_TRACKERS_PATH, "w") as f:
        yaml.safe_dump(raw["entries"], f)  # rewrite as the old bare-list shape

    assert any(e["eid_hex"] == "f" * 40 for e in firmware_store.list_registered())
    assert firmware_store.load_last_identity() == firmware_store.DEFAULT_IDENTITY


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


def test_firmware_store_records_identity_and_keep_track():
    firmware_store.record_registration(
        "1" * 40, 1700000000, display_name="Store Round Trip Keys", device_type="DEVICE_TYPE_KEYS",
        manufacturer_name="Acme", model_name="Tag v2", image_url="https://example.com/tag.png",
        experimental_official_app_compat=True, keep_track=True,
    )

    entry = next(e for e in firmware_store.list_registered() if e["eid_hex"] == "1" * 40)
    assert entry["display_name"] == "Store Round Trip Keys"
    assert entry["device_type"] == "DEVICE_TYPE_KEYS"
    assert entry["manufacturer_name"] == "Acme"
    assert entry["model_name"] == "Tag v2"
    assert entry["image_url"] == "https://example.com/tag.png"
    assert entry["experimental_official_app_compat"] is True
    assert entry["keep_track"] is True


def test_firmware_store_backfills_keep_track_false_for_legacy_entries():
    # An entry from before the "Keep track" toggle existed never opted in.
    # _save_unlocked() replaces the whole file, so this deliberately starts
    # from a clean slate rather than appending, unlike the other tests here.
    firmware_store._save_unlocked({"entries": [{"eid_hex": "c" * 40, "pair_date": 1700000200}]})

    entry = next(e for e in firmware_store.list_registered() if e["eid_hex"] == "c" * 40)
    assert entry["keep_track"] is False


def test_set_keep_track_flips_flag():
    firmware_store.record_registration("2" * 40, 1700000300, keep_track=True)

    firmware_store.set_keep_track("2" * 40, False)

    entry = next(e for e in firmware_store.list_registered() if e["eid_hex"] == "2" * 40)
    assert entry["keep_track"] is False


def test_set_keep_track_is_a_noop_for_unknown_eid():
    # The store is a real, session-shared singleton across this whole test
    # file (see conftest.py's GFMT_DATA_DIR comment) - "1"*40/"2"*40 above
    # are already in it by the time this runs, so this only asserts that an
    # eid_hex nothing has ever registered stays absent, not that the store
    # is empty.
    firmware_store.set_keep_track("unknown" + "0" * 33, True)  # must not raise
    assert not any(e["eid_hex"] == "unknown" + "0" * 33 for e in firmware_store.list_registered())


def test_firmware_page_keep_track_checkbox_is_checked(client):
    # The "on by default" behavior is purely the template's initial render -
    # see webui/routers/register.py's keep_track: bool = Form(False) comment
    # for why the server side can't default it to True.
    resp = client.get("/firmware")
    assert '<input id="keep_track" name="keep_track" type="checkbox" checked>' in resp.text


def test_register_submit_keep_track_checked(client):
    # A browser only posts a checkbox at all when it's checked - same
    # pattern as test_register_submit_persists_custom_identity's
    # experimental_official_app_compat: "on".
    client.post("/register", data={"display_name": "My Keys", "keep_track": "on"})

    entry = next(e for e in firmware_store.list_registered() if e["display_name"] == "My Keys")
    assert entry["keep_track"] is True


def test_register_submit_keep_track_unchecked(client):
    client.post("/register", data={"display_name": "Untracked Keys"})  # keep_track omitted

    entry = next(e for e in firmware_store.list_registered() if e["display_name"] == "Untracked Keys")
    assert entry["keep_track"] is False


def test_firmware_tracked_reports_not_found_for_no_matching_device(client):
    firmware_store.record_registration(
        "3" * 40, 1700000000, display_name="Tracked Not Found Keys",
        manufacturer_name="Acme", model_name="Tag v2", keep_track=True,
    )

    resp = client.get("/firmware/tracked")

    assert resp.status_code == 200
    assert "Tracked Not Found Keys" in resp.text
    assert "Not found" in resp.text


def test_firmware_tracked_reports_found_for_matching_device(client, monkeypatch):
    from webui.routers import devices

    firmware_store.record_registration(
        "4" * 40, 1700000000, display_name="Tracked Found Keys",
        manufacturer_name="Acme", model_name="Tag v2", keep_track=True,
    )

    def fake_get_device_details(device_list):
        return [{
            "name": "Tracked Found Keys", "canonic_id": "keys-canonic-id", "last_seen": None,
            "is_phone": False, "image_url": None, "device_type": None, "type_id": None,
            "manufacturer": "Acme", "model": "Tag v2", "carrier": None, "codename": None,
            "imei": None, "registered_at": None, "access": [],
        }]

    monkeypatch.setattr(devices, "get_device_details", fake_get_device_details)

    resp = client.get("/firmware/tracked")

    assert resp.status_code == 200
    assert "Found on your account" in resp.text
    assert "keys-canonic-id" in resp.text


def test_firmware_tracked_reports_ambiguous_for_multiple_matching_devices(client, monkeypatch):
    from webui.routers import devices

    firmware_store.record_registration(
        "5" * 40, 1700000000, display_name="Tracked Ambiguous Keys",
        manufacturer_name="Acme", model_name="Tag v2", keep_track=True,
    )

    def fake_get_device_details(device_list):
        base = {
            "name": "Tracked Ambiguous Keys", "last_seen": None, "is_phone": False, "image_url": None,
            "device_type": None, "type_id": None, "manufacturer": "Acme", "model": "Tag v2",
            "carrier": None, "codename": None, "imei": None, "registered_at": None, "access": [],
        }
        return [{**base, "canonic_id": "keys-1"}, {**base, "canonic_id": "keys-2"}]

    monkeypatch.setattr(devices, "get_device_details", fake_get_device_details)

    resp = client.get("/firmware/tracked")

    assert resp.status_code == 200
    assert "2 devices match this identity" in resp.text


def test_firmware_untrack_removes_entry_from_tracked_panel(client):
    firmware_store.record_registration(
        "6" * 40, 1700000000, display_name="Tracked Untrack Keys",
        manufacturer_name="Acme", model_name="Tag v2", keep_track=True,
    )

    resp = client.post(f"/firmware/tracked/{'6' * 40}/untrack")

    assert resp.status_code == 200
    assert "Tracked Untrack Keys" not in resp.text
    entry = next(e for e in firmware_store.list_registered() if e["eid_hex"] == "6" * 40)
    assert entry["keep_track"] is False
