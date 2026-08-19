from datetime import datetime

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME, FAKE_LAST_SEEN


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_devices_table_logged_in(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert FAKE_DEVICE_NAME in resp.text


def test_devices_table_is_sortable(client):
    """Opts into static/tables.js's click-to-sort/drag-to-resize columns."""
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert '<table class="sortable-table" data-table-id="devices">' in resp.text


def test_devices_table_shows_alias_and_endpoint_count(client, tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", tmp_path / "forwarding_config.json")

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "Garage Tracker",
        "endpoints": [
            {"method": "GET", "url": "http://a/", "cron": "*/5 * * * *"},
            {"method": "GET", "url": "http://b/", "cron": "*/5 * * * *"},
        ],
    })

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert '<th data-col="alias">Alias</th>' in resp.text
    assert '<th data-col="endpoints">Endpoints</th>' in resp.text
    assert "Garage Tracker" in resp.text
    assert "<td>2</td>" in resp.text


def test_devices_table_alias_and_endpoint_count_default_for_an_unconfigured_device(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "<td>-</td>" in resp.text  # no alias set yet
    assert "<td>0</td>" in resp.text  # no endpoints configured yet


def test_devices_table_last_seen_header_credits_the_find_hub(client):
    """Clarifies that this timestamp is Google's Find My Device network's
    own reporting, not e.g. this app's last poll."""
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert '<th data-col="last_seen">Last seen by find hub</th>' in resp.text


def test_devices_table_shows_last_seen_when_available(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert datetime.fromtimestamp(FAKE_LAST_SEEN).strftime("%Y-%m-%d %H:%M:%S") in resp.text


def test_devices_table_not_logged_in(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "is_logged_in", lambda: False)
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text


def test_devices_table_prepopulates_from_a_prior_locate_no_click_needed(client, tmp_path, monkeypatch):
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [{"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "map_links": {"OSM": "http://maps.example"}}],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "12.50000, 34.50000" in resp.text
    assert '<th data-col="polled_at">Polled at</th>' in resp.text
    from datetime import datetime

    assert datetime.fromtimestamp(1700000000).strftime("%Y-%m-%d %H:%M:%S") in resp.text


def test_devices_table_shows_only_the_most_recent_reading_by_default(client, tmp_path, monkeypatch):
    """devices_page_most_recent_only defaults to on (see settings_store.py) -
    a batch with an older and a newer reading only shows the newer one."""
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [
            {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 100, "map_links": {}},
            {"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "time": 200, "map_links": {}},
        ],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "12.50000, 34.50000" in resp.text
    assert "1.00000, 2.00000" not in resp.text


def test_devices_table_shows_the_full_batch_when_most_recent_only_is_off(client, tmp_path, monkeypatch):
    from webui import config, device_location_store, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    settings_store.save({**settings_store.load(), "devices_page_most_recent_only": False})

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [
            {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 100, "map_links": {}},
            {"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "time": 200, "map_links": {}},
        ],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "12.50000, 34.50000" in resp.text
    assert "1.00000, 2.00000" in resp.text


def test_devices_table_shows_a_map_links_column_with_every_provider(client, tmp_path, monkeypatch):
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import create_map_links

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [{"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "map_links": create_map_links(12.5, 34.5)}],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert '<th data-col="map">Map</th>' in resp.text
    # OSM is the default/primary provider - listed first, not just present
    assert resp.text.index("openstreetmap.org") < resp.text.index("google.com/maps")
    for host in ("openstreetmap.org", "google.com/maps", "maps.apple.com", "bing.com/maps", "waze.com"):
        assert host in resp.text


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


def test_devices_table_shows_not_scheduled_with_no_endpoints_configured(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Not scheduled" in resp.text


def test_devices_table_shows_the_next_poll_time_for_a_configured_device(client, tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", tmp_path / "forwarding_config.json")

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": FAKE_DEVICE_NAME,
        "endpoints": [{"type": "traccar", "url": "http://x/", "cron": "0 0 1 1 *"}],  # once a year
    })

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Not scheduled" not in resp.text
    assert '<a href="/settings#device-' + FAKE_CANONIC_ID in resp.text


def test_devices_table_shows_a_live_countdown_for_a_configured_device(client, tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", tmp_path / "forwarding_config.json")

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": FAKE_DEVICE_NAME,
        "endpoints": [{"type": "traccar", "url": "http://x/", "cron": "*/5 * * * *"}],
    })

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert 'class="next-poll-countdown" data-next-poll-ts="' in resp.text


def test_devices_table_has_no_countdown_element_when_not_scheduled(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Not scheduled" in resp.text
    assert "data-next-poll-ts" not in resp.text


def test_next_poll_str_is_none_with_no_valid_cron(monkeypatch, tmp_path):
    from webui import config
    from webui.forwarders import config_store
    from webui.routers.devices import _next_poll_str

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", tmp_path / "forwarding_config.json")

    assert _next_poll_str(FAKE_CANONIC_ID) is None  # no config at all yet

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": FAKE_DEVICE_NAME,
        "endpoints": [{"type": "traccar", "url": "http://x/", "cron": "not-a-cron"}],
    })
    assert _next_poll_str(FAKE_CANONIC_ID) is None


def test_devices_table_uses_persisted_location_time_when_proto_has_no_last_seen(client, tmp_path, monkeypatch):
    from webui import config, device_location_store
    from webui.routers import devices

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [{
        "name": FAKE_DEVICE_NAME, "canonic_id": FAKE_CANONIC_ID, "last_seen": None,
        "is_phone": False, "image_url": None, "device_type": None, "type_id": None, "manufacturer": None,
        "model": None, "carrier": None, "codename": None, "imei": None, "registered_at": None, "access": [],
    }])

    device_location_store.set_last_location(
        FAKE_CANONIC_ID, [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1786118431}],
        fetched_at=1786118500,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert datetime.fromtimestamp(1786118431).strftime("%Y-%m-%d %H:%M:%S") in resp.text


def test_devices_table_reuses_cached_device_list_across_requests(client, monkeypatch):
    """See webui/device_list_cache.py - request_device_list() is the slow
    call the cache exists to avoid repeating on every page load."""
    from webui.routers import devices

    calls = []
    monkeypatch.setattr(devices, "request_device_list", lambda: calls.append(1) or b"")

    assert client.get("/devices/table").status_code == 200
    assert client.get("/devices/table").status_code == 200
    assert len(calls) == 1


def test_devices_and_settings_pages_share_one_cache_fill(client, monkeypatch):
    """The two routers hit the same underlying device_list_cache singleton
    (webui/device_list_cache.py), so a /settings load right after /devices
    (or vice versa) reuses that fetch too - one of them "wins" the miss and
    the other gets a hit, whichever asks first. This also means
    devices.py's refresh_custom_trackers side effect only runs when
    devices.py's own fetch is the one that wins - a deliberate tradeoff,
    see webui/device_list_cache.py's module docstring."""
    from webui.forwarders import settings_service
    from webui.routers import devices

    calls = []
    monkeypatch.setattr(devices, "request_device_list", lambda: calls.append("devices") or b"")
    monkeypatch.setattr(settings_service, "request_device_list", lambda: calls.append("settings") or b"")

    assert client.get("/devices/table").status_code == 200
    assert client.get("/settings").status_code == 200
    assert len(calls) == 1  # only "devices" won the fetch; settings got a cache hit


def _fake_detail(**overrides) -> dict:
    base = {
        "name": FAKE_DEVICE_NAME, "canonic_id": FAKE_CANONIC_ID, "last_seen": FAKE_LAST_SEEN,
        "is_phone": False, "image_url": None, "device_type": None, "type_id": None, "manufacturer": None,
        "model": None, "carrier": None, "codename": None, "imei": None, "registered_at": None, "access": [],
    }
    base.update(overrides)
    return base


def test_devices_table_shows_device_type_and_photo_for_a_tag(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [_fake_detail(
        device_type="DEVICE_TYPE_KEYS", type_id=3, image_url="https://example.com/tag.png",
        manufacturer="Chipolo", model="Chipolo ONE Point",
    )])

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "🔑 Keys" in resp.text
    assert 'src="https://example.com/tag.png"' in resp.text


def test_devices_table_shows_phone_label_for_a_phone(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [_fake_detail(is_phone=True)])

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "📱 Phone" in resp.text


def test_devices_table_falls_back_to_a_readable_label_for_an_unmapped_device_type(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [_fake_detail(
        device_type="DEVICE_TYPE_SOMETHING_NEW", type_id=9999,
    )])

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "🏷️ Something New" in resp.text


def test_devices_table_keeps_imei_and_hardware_details_behind_a_details_toggle(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [_fake_detail(
        is_phone=True, manufacturer="Xiaomi", model="M2007J17G",
        carrier="No carrier", codename="gauguin", imei="864025058184054",
    )])

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "<details" in resp.text
    assert "IMEI: 864025058184054" in resp.text
    # everything sensitive/verbose lives inside the <details> block, not
    # rendered plain into the always-visible row above it
    assert resp.text.index("864025058184054") > resp.text.index("<details")


def test_devices_table_shows_who_a_device_is_shared_with(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [_fake_detail(access=[
        {"email": "me@example.com", "has_access": True, "is_owner": True, "this_account": True},
        {"email": "family@example.com", "has_access": True, "is_owner": False, "this_account": False},
    ])])

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Shared with: family@example.com" in resp.text
    assert "me@example.com" not in resp.text  # your own account isn't "shared with"


def test_devices_table_omits_sharing_line_when_only_the_owner_has_access(client, monkeypatch):
    from webui.routers import devices

    monkeypatch.setattr(devices, "get_device_details", lambda device_list: [_fake_detail(access=[
        {"email": "me@example.com", "has_access": True, "is_owner": True, "this_account": True},
    ])])

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "Shared with" not in resp.text


