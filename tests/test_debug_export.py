import io
import json
import tempfile
from pathlib import Path

import py7zr
import pytest

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME

# Every boolean toggle on this route defaults to False (see
# webui/routers/debug_export.py's own comment on why) - tests that want the
# live query to actually run have to ask for it explicitly, same as the real
# frontend's JS always does.
_LIVE = {"include_live_query": "true"}


def _archive_names(content: bytes, password: str | None = None) -> set[str]:
    with py7zr.SevenZipFile(io.BytesIO(content), "r", password=password) as archive:
        return set(archive.getnames())


def _archive_extract(content: bytes, password: str | None = None) -> dict[str, bytes]:
    """Extracted {relative_path: bytes} for every member - py7zr has no
    in-memory read, only extract-to-disk, so this uses a scratch tempdir."""
    with tempfile.TemporaryDirectory() as tmp:
        with py7zr.SevenZipFile(io.BytesIO(content), "r", password=password) as archive:
            archive.extractall(path=tmp)
        return {
            path.relative_to(tmp).as_posix(): path.read_bytes()
            for path in Path(tmp).rglob("*") if path.is_file()
        }


def _stub_device_list_and_locate(monkeypatch, locations=None, locate_capture=None):
    """Common happy-path stubs: one fake device, one successful locate.
    Mirrors the fetch/parse/refresh/decode sequence in
    webui/routers/debug_export.py._fetch_device_list_debug, patched on the
    debug_export module itself (each router binds its own `from X import Y`
    name - see tests/conftest.py's own docstring for why patches must target
    the router module, not the source module)."""
    from ProtoDecoders import DeviceUpdate_pb2
    from webui.routers import debug_export

    monkeypatch.setattr(debug_export, "is_logged_in", lambda: True)
    monkeypatch.setattr(debug_export, "request_device_list", lambda: "deadbeef")
    monkeypatch.setattr(debug_export, "parse_device_list_protobuf", lambda hex_str: DeviceUpdate_pb2.DevicesList())
    monkeypatch.setattr(debug_export, "refresh_custom_trackers", lambda device_list: None)
    monkeypatch.setattr(
        debug_export, "get_device_details",
        lambda device_list: [{"canonic_id": FAKE_CANONIC_ID, "name": FAKE_DEVICE_NAME}],
    )

    async def fake_locate(canonic_id, name, timeout=None):
        return (
            locations if locations is not None else [{"latitude": 1.0, "longitude": 2.0}],
            locate_capture if locate_capture is not None else {"raw_hex": "cafebabe", "device_update_text": "dump"},
        )

    monkeypatch.setattr(debug_export, "locate_device_with_capture", fake_locate)
    return debug_export


def test_debug_export_requires_login(client, monkeypatch):
    from webui.routers import debug_export

    monkeypatch.setattr(debug_export, "is_logged_in", lambda: False)

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 400
    assert "sign in" in resp.json()["error"].lower()


def test_debug_export_device_list_failure_returns_502(client, monkeypatch):
    from webui.routers import debug_export

    monkeypatch.setattr(debug_export, "is_logged_in", lambda: True)

    def boom():
        raise RuntimeError("nova blew up")

    monkeypatch.setattr(debug_export, "request_device_list", boom)

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 502
    assert "nova blew up" in resp.json()["error"]


def test_debug_export_happy_path_builds_expected_archive(client, monkeypatch):
    _stub_device_list_and_locate(monkeypatch)

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-7z-compressed"
    assert resp.headers["content-disposition"].endswith('.7z"')

    names = _archive_names(resp.content)
    assert names == {
        "manifest.json",
        "device_list/raw_hex.txt",
        "device_list/protobuf_text.txt",
        "device_list/decoded.json",
        f"locate/{FAKE_CANONIC_ID}/status.json",
        f"locate/{FAKE_CANONIC_ID}/raw_hex.txt",
        f"locate/{FAKE_CANONIC_ID}/protobuf_text.txt",
        f"locate/{FAKE_CANONIC_ID}/decoded_locations.json",
    }

    files = _archive_extract(resp.content)
    assert files["device_list/raw_hex.txt"] == b"deadbeef"
    assert files[f"locate/{FAKE_CANONIC_ID}/raw_hex.txt"] == b"cafebabe"


def test_debug_export_decoded_json_carries_type_id(client, monkeypatch):
    """device_list/decoded.json is get_device_details()'s output dumped
    verbatim (see debug_export.py) - type_id needs no dedicated handling
    here, just confirming it actually survives the dump."""
    debug_export = _stub_device_list_and_locate(monkeypatch)
    monkeypatch.setattr(
        debug_export, "get_device_details",
        lambda device_list: [{"canonic_id": FAKE_CANONIC_ID, "name": FAKE_DEVICE_NAME, "type_id": 3}],
    )

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200

    files = _archive_extract(resp.content)
    decoded = json.loads(files["device_list/decoded.json"])
    assert decoded[0]["type_id"] == 3


def test_debug_export_no_devices_still_succeeds(client, monkeypatch):
    from ProtoDecoders import DeviceUpdate_pb2
    from webui.routers import debug_export

    monkeypatch.setattr(debug_export, "is_logged_in", lambda: True)
    monkeypatch.setattr(debug_export, "request_device_list", lambda: "deadbeef")
    monkeypatch.setattr(debug_export, "parse_device_list_protobuf", lambda hex_str: DeviceUpdate_pb2.DevicesList())
    monkeypatch.setattr(debug_export, "refresh_custom_trackers", lambda device_list: None)
    monkeypatch.setattr(debug_export, "get_device_details", lambda device_list: [])

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200
    names = _archive_names(resp.content)
    assert names == {"manifest.json", "device_list/raw_hex.txt", "device_list/protobuf_text.txt",
                      "device_list/decoded.json"}


def test_debug_export_one_device_failing_does_not_abort_export(client, monkeypatch):
    from ProtoDecoders import DeviceUpdate_pb2
    from webui.routers import debug_export

    monkeypatch.setattr(debug_export, "is_logged_in", lambda: True)
    monkeypatch.setattr(debug_export, "request_device_list", lambda: "deadbeef")
    monkeypatch.setattr(debug_export, "parse_device_list_protobuf", lambda hex_str: DeviceUpdate_pb2.DevicesList())
    monkeypatch.setattr(debug_export, "refresh_custom_trackers", lambda device_list: None)
    monkeypatch.setattr(
        debug_export, "get_device_details",
        lambda device_list: [{"canonic_id": FAKE_CANONIC_ID, "name": FAKE_DEVICE_NAME}],
    )

    async def boom(canonic_id, name, timeout=None):
        raise RuntimeError("decrypt failed")

    monkeypatch.setattr(debug_export, "locate_device_with_capture", boom)

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200
    files = _archive_extract(resp.content)
    status = json.loads(files[f"locate/{FAKE_CANONIC_ID}/status.json"])
    assert status["outcome"] == "error"
    assert "decrypt failed" in status["error"]


def test_debug_export_password_encrypts_the_archive(client, monkeypatch):
    _stub_device_list_and_locate(monkeypatch)

    resp = client.post("/auth/debug-export", data={**_LIVE, "password": "hunter2"})
    assert resp.status_code == 200

    with pytest.raises(Exception):
        _archive_names(resp.content, password="wrong-password")

    names = _archive_names(resp.content, password="hunter2")
    assert "manifest.json" in names


def test_debug_export_no_password_leaves_archive_unencrypted(client, monkeypatch):
    _stub_device_list_and_locate(monkeypatch)

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200
    # Opens with no password at all - never silently defaults to encrypted.
    names = _archive_names(resp.content, password=None)
    assert "manifest.json" in names


def test_debug_export_logs_omitted_by_default(client, monkeypatch, tmp_path):
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")
    _stub_device_list_and_locate(monkeypatch)

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200
    names = _archive_names(resp.content)
    assert "logs/system_log.txt" not in names
    assert "logs/forward_log.txt" not in names


def test_debug_export_include_logs_redacts_tokens_in_forward_log(client, monkeypatch, tmp_path):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    log_store.append(
        FAKE_CANONIC_ID, FAKE_DEVICE_NAME, "custom",
        "GET https://example.com/webhook/SUPER-SECRET-TOKEN", "ok",
    )
    _stub_device_list_and_locate(monkeypatch)

    resp = client.post("/auth/debug-export", data={**_LIVE, "include_logs": "true"})
    assert resp.status_code == 200
    # The regression that matters most: the raw token must never appear
    # anywhere in the returned archive, compressed or not.
    assert b"SUPER-SECRET-TOKEN" not in resp.content

    files = _archive_extract(resp.content)
    forward_log = files["logs/forward_log.txt"].decode()
    assert "SUPER-SECRET-TOKEN" not in forward_log
    assert "https://example.com/...(redacted)" in forward_log


def test_debug_export_requires_at_least_one_of_live_query_or_logs(client, monkeypatch):
    from webui.routers import debug_export

    # Not even patched to be logged in - the "select at least one" check
    # must fire before anything else, including the sign-in check.
    monkeypatch.setattr(debug_export, "is_logged_in", lambda: False)

    # Neither field sent at all - both toggles default to False (see
    # webui/routers/debug_export.py's own comment on why), so this is the
    # same as explicitly sending "" for both.
    resp = client.post("/auth/debug-export")
    assert resp.status_code == 400
    assert "select at least one" in resp.json()["error"].lower()


def test_debug_export_logs_only_skips_live_query_and_login_check(client, monkeypatch, tmp_path):
    from webui import config, system_log_store
    from webui.routers import debug_export

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")
    system_log_store.append("WARNING", "webui.test", "something happened", 1)

    # Deliberately NOT logged in, and every live-query call left unpatched
    # (would error/hang if actually invoked) - a logs-only export must never
    # touch either.
    monkeypatch.setattr(debug_export, "is_logged_in", lambda: False)

    resp = client.post("/auth/debug-export", data={"include_logs": "true"})
    assert resp.status_code == 200

    names = _archive_names(resp.content)
    assert names == {"manifest.json", "logs/system_log.txt", "logs/forward_log.txt"}
    files = _archive_extract(resp.content)
    assert "something happened" in files["logs/system_log.txt"].decode()


def test_debug_export_anonymize_scrambles_coordinates_and_semantic_name(client, monkeypatch):
    real_location = {
        "latitude": 48.8584, "longitude": 2.2945, "altitude": 35.0, "time": 1700000000,
        "is_semantic": False, "semantic_name": None, "status": "GEOLOCATION", "status_id": 1,
        "accuracy": 12.5, "is_own_report": True,
        "map_links": {"OSM": "https://www.openstreetmap.org/?mlat=48.8584&mlon=2.2945"},
    }
    real_semantic = {
        "latitude": None, "longitude": None, "altitude": None, "time": 1700000001,
        "is_semantic": True, "semantic_name": "123 Real Street, Hometown", "status": "SEMANTIC", "status_id": 2,
        "accuracy": 0, "is_own_report": True, "map_links": None,
    }
    _stub_device_list_and_locate(
        monkeypatch, locations=[real_location, real_semantic],
        locate_capture={"raw_hex": "cafebabe", "device_update_text": "dump"},
    )

    resp = client.post("/auth/debug-export", data={**_LIVE, "anonymize_locations": "true"})
    assert resp.status_code == 200

    # The raw wire-format dumps aren't scrubbed by anonymization, so they
    # must be left out entirely rather than included un-anonymized - and the
    # archive must say so, not just silently drop them.
    names = _archive_names(resp.content)
    assert f"locate/{FAKE_CANONIC_ID}/raw_hex.txt" not in names
    assert f"locate/{FAKE_CANONIC_ID}/protobuf_text.txt" not in names
    assert "ANONYMIZATION_NOTICE.txt" in names

    files = _archive_extract(resp.content)
    manifest = json.loads(files["manifest.json"])
    assert manifest["raw_location_dumps_omitted"] is True
    assert "raw_hex.txt" in files["ANONYMIZATION_NOTICE.txt"].decode()

    locations = json.loads(files[f"locate/{FAKE_CANONIC_ID}/decoded_locations.json"])
    geo, semantic = locations

    assert (geo["latitude"], geo["longitude"]) != (48.8584, 2.2945)
    assert -90 <= geo["latitude"] <= 90
    assert -180 <= geo["longitude"] <= 180
    assert geo["altitude"] != 35.0
    assert geo["accuracy"] != 12.5
    # Coordinates baked into the map links must be re-derived, not left
    # pointing at the real location.
    assert "48.8584" not in json.dumps(geo["map_links"])
    # Categorical/timing fields are untouched - they're not GPS data and are
    # needed to debug parsing logic.
    assert geo["status"] == "GEOLOCATION"
    assert geo["time"] == 1700000000

    assert semantic["semantic_name"] != "123 Real Street, Hometown"
    assert "123 Real Street, Hometown" not in json.dumps(locations)
    assert semantic["latitude"] is None  # never invented for a semantic-only entry


def test_debug_export_anonymize_off_by_default_keeps_real_coordinates(client, monkeypatch):
    real_location = {
        "latitude": 48.8584, "longitude": 2.2945, "altitude": 35.0, "time": 1700000000,
        "is_semantic": False, "semantic_name": None, "status": "GEOLOCATION", "status_id": 1,
        "accuracy": 12.5, "is_own_report": True, "map_links": {},
    }
    _stub_device_list_and_locate(monkeypatch, locations=[real_location])

    resp = client.post("/auth/debug-export", data=_LIVE)
    assert resp.status_code == 200

    names = _archive_names(resp.content)
    assert f"locate/{FAKE_CANONIC_ID}/raw_hex.txt" in names
    assert f"locate/{FAKE_CANONIC_ID}/protobuf_text.txt" in names
    assert "ANONYMIZATION_NOTICE.txt" not in names

    files = _archive_extract(resp.content)
    manifest = json.loads(files["manifest.json"])
    assert manifest["raw_location_dumps_omitted"] is False

    locations = json.loads(files[f"locate/{FAKE_CANONIC_ID}/decoded_locations.json"])
    assert locations[0]["latitude"] == 48.8584
    assert locations[0]["longitude"] == 2.2945
