from datetime import datetime

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME, FAKE_LAST_SEEN


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_devices_table_logged_in(client):
    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert FAKE_DEVICE_NAME in resp.text


def test_devices_table_shows_alias_and_endpoint_count(client, tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
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
    assert "<th>Alias</th>" in resp.text
    assert "<th>Endpoints</th>" in resp.text
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
    assert "<th>Last seen by find hub</th>" in resp.text


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
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [{"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "map_links": {"OSM": "http://maps.example"}}],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "12.50000, 34.50000" in resp.text
    assert "<th>Polled at</th>" in resp.text
    from datetime import datetime

    assert datetime.fromtimestamp(1700000000).strftime("%Y-%m-%d %H:%M:%S") in resp.text


def test_devices_table_shows_a_map_links_column_with_every_provider(client, tmp_path, monkeypatch):
    from webui import config, device_location_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import create_map_links

    device_location_store.set_last_location(
        FAKE_CANONIC_ID,
        [{"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "map_links": create_map_links(12.5, 34.5)}],
        fetched_at=1700000000,
    )

    resp = client.get("/devices/table")
    assert resp.status_code == 200
    assert "<th>Map</th>" in resp.text
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
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
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
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
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
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
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
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")
    monkeypatch.setattr(devices, "get_canonic_ids", lambda device_list: [(FAKE_DEVICE_NAME, FAKE_CANONIC_ID, None)])

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
    from webui.routers import devices, settings

    calls = []
    monkeypatch.setattr(devices, "request_device_list", lambda: calls.append("devices") or b"")
    monkeypatch.setattr(settings, "request_device_list", lambda: calls.append("settings") or b"")

    assert client.get("/devices/table").status_code == 200
    assert client.get("/settings").status_code == 200
    assert len(calls) == 1  # only "devices" won the fetch; settings got a cache hit


