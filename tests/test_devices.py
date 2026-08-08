from datetime import datetime

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME, FAKE_LAST_SEEN


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_devices_table_logged_in(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert FAKE_DEVICE_NAME in resp.text


def test_devices_table_shows_last_seen_when_available(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert datetime.fromtimestamp(FAKE_LAST_SEEN).strftime("%Y-%m-%d %H:%M:%S") in resp.text


def test_devices_table_shows_battery_and_wifi_when_extra_info_present(client, tmp_path, monkeypatch):
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_extra_info(
        FAKE_CANONIC_ID, {"battery_pct": 95, "wifi_ssid": "Mordor"}, fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "95%" in resp.text
    assert "Mordor" in resp.text


def test_devices_table_shows_dashes_when_no_extra_info(client, tmp_path, monkeypatch):
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "—" in resp.text  # last seen and/or battery/wifi columns fall back to this


def test_devices_table_not_logged_in(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "is_logged_in", lambda: False)
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text


def test_devices_table_prepopulates_from_a_prior_locate_no_click_needed(client, tmp_path, monkeypatch):
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [{"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "google_maps_link": "http://maps.example"}],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "12.50000, 34.50000" in resp.text
    assert "as of" in resp.text


def test_last_seen_falls_back_to_the_most_recent_persisted_location_time():
    """Spot/BLE tags carry no hardwareInfo.lastSeenTime at all (see
    ProtoDecoders/decoder.py:get_last_seen) - the Devices page should still
    show something once the tag has actually been located at least once."""
    from webui.routers.devices import _last_seen_from_persisted_locations

    assert _last_seen_from_persisted_locations(None) is None

    no_usable_time = {"locations": [{"is_semantic": True, "time": 999}, {"is_semantic": False, "time": None}]}
    assert _last_seen_from_persisted_locations(no_usable_time) is None

    multiple_fixes = {"locations": [
        {"is_semantic": False, "time": 100},
        {"is_semantic": True, "time": 999},  # semantic entries don't count
        {"is_semantic": False, "time": 300},
    ]}
    assert _last_seen_from_persisted_locations(multiple_fixes) == 300


def test_devices_table_uses_persisted_location_time_when_proto_has_no_last_seen(client, tmp_path, monkeypatch):
    from webui import config, device_location_store
    from webui.routers import devices

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")
    monkeypatch.setattr(devices, "get_canonic_ids", lambda device_list: [(FAKE_DEVICE_NAME, FAKE_CANONIC_ID, None)])

    device_location_store.set_last_location(
        FAKE_CANONIC_ID, [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1786118431}],
        fetched_at=1786118500,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert datetime.fromtimestamp(1786118431).strftime("%Y-%m-%d %H:%M:%S") in resp.text
