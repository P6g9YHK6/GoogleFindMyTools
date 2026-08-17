from tests.conftest import FAKE_CANONIC_ID


def test_locate_success(client, tmp_path, monkeypatch):
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})
    assert resp.status_code == 200
    # The separate "Map" column is updated via an out-of-band swap alongside
    # the main response (see _locate_cell.html/_table.html) - not part of
    # the normal targeted swap, so it needs its own id + hx-swap-oob here.
    assert f'id="map-links-{FAKE_CANONIC_ID}"' in resp.text
    assert 'hx-swap-oob="true"' in resp.text


def test_locate_failure_renders_error_fragment_not_bare_500(client, monkeypatch):
    from webui.routers import locate

    async def boom(canonic_id, name, timeout=None):
        raise RuntimeError("decrypt failed")

    monkeypatch.setattr(locate, "locate_device", boom)

    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})
    assert resp.status_code == 200  # error is rendered inline, not a 500 - htmx doesn't swap those in
    assert "decrypt failed" in resp.text
    # A failed attempt didn't change what's persisted - the Map/Polled-at
    # columns must be left alone, not OOB-blanked with this response's own
    # empty locations (see routers/locate.py).
    assert "hx-swap-oob" not in resp.text


def test_locate_success_persists_the_result_with_a_timestamp(client, tmp_path, monkeypatch):
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})
    assert resp.status_code == 200
    # The separate "Polled at" column (see _table.html) is also updated via
    # an out-of-band swap, same as the Map column - see test_locate_success.
    assert f'id="polled-at-{FAKE_CANONIC_ID}"' in resp.text

    saved = device_location_store.get_last_location(FAKE_CANONIC_ID)
    assert saved is not None
    assert saved["locations"][0]["latitude"] == 1.0
    assert isinstance(saved["fetched_at"], int)


def test_locate_failure_does_not_clobber_the_last_good_result(client, tmp_path, monkeypatch):
    from webui import config, device_location_store
    from webui.routers import locate

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    # A real fix first...
    client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})
    good = device_location_store.get_last_location(FAKE_CANONIC_ID)
    assert good is not None

    # ...then a failure must not erase it.
    async def boom(canonic_id, name, timeout=None):
        raise RuntimeError("decrypt failed")

    monkeypatch.setattr(locate, "locate_device", boom)
    client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})

    assert device_location_store.get_last_location(FAKE_CANONIC_ID) == good
