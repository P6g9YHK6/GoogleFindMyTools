def test_register_form(client):
    resp = client.get("/register")
    assert resp.status_code == 200


def test_register_submit(client):
    resp = client.post("/register")
    assert resp.status_code == 200
    assert "deadbeef" in resp.text


def test_register_then_devices_table_sees_the_new_tracker_immediately(client, monkeypatch):
    """webui/deps.py's register_tracker() invalidates the shared
    device-list cache (webui/device_list_cache.py) on success, so a
    just-registered tracker shows up on the very next /devices/table load
    instead of waiting out its TTL. The autouse stub_backend fixture
    (tests/conftest.py) replaces register.register_tracker wholesale, which
    would bypass that invalidate() call entirely - this test points it back
    at the real webui.deps.register_tracker and only stubs the actual
    Google call underneath it."""
    from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME, FAKE_LAST_SEEN
    from webui import deps
    from webui.routers import devices, register

    monkeypatch.setattr(register, "register_tracker", deps.register_tracker)
    monkeypatch.setattr(deps, "register_esp32", lambda: {"eid_hex": "deadbeef"})

    resp = client.get("/devices/table")
    assert FAKE_DEVICE_NAME in resp.text
    assert "New Tracker" not in resp.text

    def fake_get_canonic_ids(device_list):
        return [
            (FAKE_DEVICE_NAME, FAKE_CANONIC_ID, FAKE_LAST_SEEN),
            ("New Tracker", "new-canonic-id", None),
        ]

    monkeypatch.setattr(devices, "get_canonic_ids", fake_get_canonic_ids)

    resp = client.post("/register")
    assert resp.status_code == 200
    assert "deadbeef" in resp.text

    # Still well within the cache's default TTL - without the invalidate()
    # call, this would still show only the original device.
    resp = client.get("/devices/table")
    assert "New Tracker" in resp.text
