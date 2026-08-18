import asyncio

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


async def test_run_build_fails_gracefully_without_idf(monkeypatch):
    _reset_state()
    monkeypatch.setattr(firmware_build.shutil, "which", lambda name: None)

    called = False

    async def fake_exec(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("should never spawn a subprocess when idf.py is missing")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await firmware_build._run_build("esp32", "a" * 40)

    assert called is False
    state = firmware_build.get_state()
    assert state["phase"] == "error"
    assert "idf.py" in state["error"] or "ESP-IDF" in state["message"]


async def test_start_refuses_concurrent_build(monkeypatch):
    _reset_state()
    firmware_build._state["phase"] = "building"
    result = await firmware_build.start("esp32", "a" * 40)
    assert result["started"] is False
    _reset_state()


def test_inject_eid_replaces_placeholder(tmp_path):
    src = tmp_path / "ESP32Firmware" / "main"
    src.mkdir(parents=True)
    main_c = src / "main.c"
    main_c.write_text('const char *eid_string = "INSERT_YOUR_ADVERTISEMENT_KEY_HERE";\n')

    firmware_build._inject_eid(tmp_path / "ESP32Firmware", "b" * 40)

    assert 'const char *eid_string = "' + "b" * 40 + '";' in main_c.read_text()


def test_inject_eid_fails_loudly_if_literal_missing(tmp_path):
    src = tmp_path / "ESP32Firmware" / "main"
    src.mkdir(parents=True)
    (src / "main.c").write_text("// no eid_string literal here\n")

    try:
        firmware_build._inject_eid(tmp_path / "ESP32Firmware", "b" * 40)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_firmware_store_round_trip():
    assert firmware_store.list_registered() == []
    firmware_store.record_registration("a" * 40, 1700000000)
    firmware_store.record_registration("b" * 40, 1700000100)

    entries = firmware_store.list_registered()
    assert [e["eid_hex"] for e in entries] == ["b" * 40, "a" * 40]  # newest first


def test_register_submit_records_eid_for_firmware_page(client):
    client.post("/register")
    entries = firmware_store.list_registered()
    assert any(e["eid_hex"] == "deadbeef" for e in entries)
