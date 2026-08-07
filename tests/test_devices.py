from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_devices_table_logged_in(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert FAKE_DEVICE_NAME in resp.text


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
