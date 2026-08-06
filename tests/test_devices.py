from tests.conftest import FAKE_DEVICE_NAME


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
