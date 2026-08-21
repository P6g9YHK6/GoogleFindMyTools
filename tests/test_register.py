def test_register_form_redirects_to_firmware_page(client):
    # /register used to be its own page - now it's the "Register Tracker"
    # section at the top of /firmware, see webui/templates/firmware/page.html.
    resp = client.get("/register")
    assert resp.status_code == 200
    assert resp.request.url.path == "/firmware"
    assert "Register Tracker" in resp.text


def test_register_submit(client):
    resp = client.post("/register")
    assert resp.status_code == 200
    assert "deadbeef" in resp.text


def test_register_submit_persists_custom_identity(client):
    from webui import firmware_store

    resp = client.post("/register", data={
        "display_name": "My Keys", "device_type": "DEVICE_TYPE_KEYS",
        "manufacturer_name": "Acme", "model_name": "Tag v2",
        "image_url": "https://example.com/tag.png",
        # A browser only posts a checkbox at all when it's checked, and
        # "on" is what it posts - see webui/routers/register.py's
        # experimental_official_app_compat: bool = Form(False) comment.
        "experimental_official_app_compat": "on",
    })
    assert resp.status_code == 200
    assert "deadbeef" in resp.text

    identity = firmware_store.load_last_identity()
    assert identity == {
        "display_name": "My Keys", "device_type": "DEVICE_TYPE_KEYS",
        "manufacturer_name": "Acme", "model_name": "Tag v2",
        "image_url": "https://example.com/tag.png",
        "experimental_official_app_compat": True,
    }


def test_register_submit_rejects_bad_device_type(client):
    from webui import firmware_store

    before = firmware_store.list_registered()
    resp = client.post("/register", data={"device_type": "DEVICE_TYPE_NOT_A_REAL_TYPE"})
    assert resp.status_code == 200
    assert "form-error" in resp.text
    assert "new-eid-hex" not in resp.text
    assert firmware_store.list_registered() == before


def test_register_submit_rejects_bad_image_url(client):
    from webui import firmware_store

    before = firmware_store.list_registered()
    resp = client.post("/register", data={"image_url": "ftp://example.com/x.png"})
    assert resp.status_code == 200
    assert "form-error" in resp.text
    assert "new-eid-hex" not in resp.text
    assert firmware_store.list_registered() == before


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
    monkeypatch.setattr(deps, "register_esp32", lambda **kwargs: {"eid_hex": "deadbeef"})

    resp = client.get("/devices/table")
    assert FAKE_DEVICE_NAME in resp.text
    assert "New Tracker" not in resp.text

    def fake_get_device_details(device_list):
        base = {
            "is_phone": False, "image_url": None, "device_type": None, "type_id": None, "manufacturer": None,
            "model": None, "carrier": None, "codename": None, "imei": None, "registered_at": None, "access": [],
        }
        return [
            {"name": FAKE_DEVICE_NAME, "canonic_id": FAKE_CANONIC_ID, "last_seen": FAKE_LAST_SEEN, **base},
            {"name": "New Tracker", "canonic_id": "new-canonic-id", "last_seen": None, **base},
        ]

    monkeypatch.setattr(devices, "get_device_details", fake_get_device_details)

    resp = client.post("/register")
    assert resp.status_code == 200
    assert "deadbeef" in resp.text

    # Still well within the cache's default TTL - without the invalidate()
    # call, this would still show only the original device.
    resp = client.get("/devices/table")
    assert "New Tracker" in resp.text
