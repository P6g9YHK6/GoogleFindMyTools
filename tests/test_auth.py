def test_auth_page(client):
    resp = client.get("/auth")
    assert resp.status_code == 200


def test_auth_status_fragment_logged_in(client):
    # is_logged_in() is stubbed True by default (see conftest.stub_backend), but no real
    # credentials exist in the test secrets dir, so the diagnostics breakdown is all "missing".
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert "Signed in" in resp.text
    assert "not yet confirmed" in resp.text  # shared_key never cached either
    assert resp.text.count("<em>missing</em>") == 5


def test_auth_status_fragment_not_logged_in(client, monkeypatch):
    from webui.routers import auth

    monkeypatch.setattr(auth, "is_logged_in", lambda: False)
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert "Not signed in" in resp.text


def test_auth_clear(client):
    resp = client.post("/auth/clear")
    assert resp.status_code == 200


def test_auth_clear_refused_while_signing_in(client, monkeypatch):
    import webui.browser_provisioning as browser_provisioning

    monkeypatch.setattr(browser_provisioning, "is_active", lambda: True)
    resp = client.post("/auth/clear")
    assert resp.status_code == 200
    assert "sign-in is currently in progress" in resp.text


def test_auth_login_start(client, monkeypatch):
    import webui.browser_provisioning as browser_provisioning

    async def fake_start():
        return {"started": True, "state": browser_provisioning.get_state()}

    monkeypatch.setattr(browser_provisioning, "start", fake_start)
    resp = client.post("/auth/login/start")
    assert resp.status_code == 200
    assert resp.json()["started"] is True


def test_auth_login_poll(client):
    resp = client.get("/auth/login/poll")
    assert resp.status_code == 200
    assert resp.json()["phase"] == "idle"


def test_auth_queue_status_reflects_live_waiting_count(client, monkeypatch):
    from webui.routers import auth

    monkeypatch.setattr(auth.query_gate, "waiting", 0)
    resp = client.get("/auth/queue")
    assert resp.status_code == 200
    assert "0 requests waiting" in resp.text

    monkeypatch.setattr(auth.query_gate, "waiting", 1)
    resp = client.get("/auth/queue")
    assert "1 request waiting" in resp.text


def test_app_settings_round_trip(client, tmp_path, monkeypatch):
    import logging

    from webui import config, notify, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    # Saving settings reconfigures Apprise for real (see routers/auth.py) -
    # stub it out so this test never actually touches the network.
    class FakeApprise:
        def add(self, url):
            return True

    monkeypatch.setattr(notify.apprise, "Apprise", FakeApprise)

    try:
        resp = client.post("/auth/settings", data={
            "query_throttle_max": "5",
            "query_throttle_window_s": "30",
            "query_min_spread_s": "0.5",
            "apprise_urls": "json://example.com/hook",
            "apprise_notify_level": "ERROR",
        })
        assert resp.status_code == 200
        assert "Saved." in resp.text
        assert 'value="5"' in resp.text

        saved = settings_store.load()
        assert saved["query_throttle_max"] == 5
        assert saved["query_throttle_window_s"] == 30.0
        assert saved["query_min_spread_s"] == 0.5
        assert saved["apprise_urls"] == "json://example.com/hook"
        assert saved["apprise_notify_level"] == "ERROR"

        # A fresh GET of the Config page reflects the saved settings too.
        page = client.get("/auth")
        assert 'value="json://example.com/hook"' not in page.text  # it's a textarea, not an input
        assert "json://example.com/hook" in page.text
    finally:
        # configure_apprise_logging() really did install a handler on the
        # webui logger (with our FakeApprise inside it) - don't leave it
        # attached for every other test in the session to trip over.
        for handler in list(logging.getLogger("webui").handlers):
            if isinstance(handler, notify._AppriseLogHandler):
                logging.getLogger("webui").removeHandler(handler)


def test_app_settings_devices_page_most_recent_only_round_trips(client, tmp_path, monkeypatch):
    """Unlike the endpoint-level toggles (webui/forwarders/policy.py), this
    is a plain non-htmx checkbox - Form(False) is what correctly resolves
    "checkbox not posted at all" to off (see routers/auth.py's
    save_app_settings)."""
    from webui import config, notify, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    class FakeApprise:
        def add(self, url):
            return True

    monkeypatch.setattr(notify.apprise, "Apprise", FakeApprise)

    try:
        # Checked - actually posted.
        resp = client.post("/auth/settings", data={
            "query_throttle_max": "5", "query_throttle_window_s": "30", "query_min_spread_s": "0.5",
            "apprise_urls": "", "apprise_notify_level": "WARNING",
            "devices_page_most_recent_only": "true",
        })
        assert resp.status_code == 200
        assert settings_store.load()["devices_page_most_recent_only"] is True
        assert "checked" in resp.text

        # Unchecked - a real browser simply wouldn't post this field at all.
        resp = client.post("/auth/settings", data={
            "query_throttle_max": "5", "query_throttle_window_s": "30", "query_min_spread_s": "0.5",
            "apprise_urls": "", "apprise_notify_level": "WARNING",
        })
        assert resp.status_code == 200
        assert settings_store.load()["devices_page_most_recent_only"] is False
    finally:
        _remove_apprise_handlers()


def test_app_settings_semantic_location_map_round_trips(client, tmp_path, monkeypatch):
    """The semantic-name/lat/lon rows (see routers/auth.py's
    _parse_semantic_map_form) are a dynamic table, posted as parallel
    semantic_name[]/semantic_lat[]/semantic_lon[] lists rather than named
    Form(...) params - a blank name (an untouched "+ Add row" row left
    empty) is dropped rather than saved as a bogus entry."""
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    _stub_apprise(monkeypatch)

    try:
        resp = client.post("/auth/settings", data={
            "query_throttle_max": "5", "query_throttle_window_s": "30", "query_min_spread_s": "0.5",
            "apprise_urls": "", "apprise_notify_level": "WARNING",
            "semantic_name": ["Nest Mini - Living Room", ""],
            "semantic_lat": ["45.0", ""],
            "semantic_lon": ["9.0", ""],
            "semantic_match_mode": ["partial", "full"],
        })
        assert resp.status_code == 200
        assert "Nest Mini - Living Room" in resp.text

        saved = settings_store.load()
        assert saved["semantic_location_map"] == {
            "Nest Mini - Living Room": {"latitude": 45.0, "longitude": 9.0, "match_mode": "partial"},
        }

        # A fresh GET of the Config page reflects the saved mapping too.
        page = client.get("/auth")
        assert "Nest Mini - Living Room" in page.text
    finally:
        _remove_apprise_handlers()


def test_app_settings_semantic_location_map_defaults_match_mode_to_full(client, tmp_path, monkeypatch):
    """A row posted with no semantic_match_mode value (or an unrecognized
    one) falls back to "full" rather than dropping the row - see
    routers/auth.py's _parse_semantic_map_form."""
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    _stub_apprise(monkeypatch)

    try:
        resp = client.post("/auth/settings", data={
            "query_throttle_max": "5", "query_throttle_window_s": "30", "query_min_spread_s": "0.5",
            "apprise_urls": "", "apprise_notify_level": "WARNING",
            "semantic_name": ["Home"],
            "semantic_lat": ["1.0"],
            "semantic_lon": ["2.0"],
            # No semantic_match_mode posted at all for this row.
        })
        assert resp.status_code == 200
        assert settings_store.load()["semantic_location_map"] == {
            "Home": {"latitude": 1.0, "longitude": 2.0, "match_mode": "full"},
        }
    finally:
        _remove_apprise_handlers()


def test_app_settings_semantic_location_map_drops_a_row_with_non_numeric_coordinates(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    _stub_apprise(monkeypatch)

    try:
        resp = client.post("/auth/settings", data={
            "query_throttle_max": "5", "query_throttle_window_s": "30", "query_min_spread_s": "0.5",
            "apprise_urls": "", "apprise_notify_level": "WARNING",
            "semantic_name": ["Bad Row"], "semantic_lat": ["not-a-number"], "semantic_lon": ["9.0"],
        })
        assert resp.status_code == 200
        assert settings_store.load()["semantic_location_map"] == {}
    finally:
        _remove_apprise_handlers()


def _stub_apprise(monkeypatch):
    from webui import notify

    class FakeApprise:
        def add(self, url):
            return True

    monkeypatch.setattr(notify.apprise, "Apprise", FakeApprise)


def _remove_apprise_handlers():
    import logging

    from webui import notify

    for handler in list(logging.getLogger("webui").handlers):
        if isinstance(handler, notify._AppriseLogHandler):
            logging.getLogger("webui").removeHandler(handler)


def test_app_settings_yaml_view_shows_current_settings(client, tmp_path, monkeypatch):
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    resp = client.get("/auth/settings/yaml")
    assert resp.status_code == 200
    assert "query_throttle_max:" in resp.text
    assert "Edit as form" in resp.text


def test_app_settings_form_route_switches_back_from_yaml_view(client):
    resp = client.get("/auth/settings")
    assert resp.status_code == 200
    assert "Edit as YAML" in resp.text
    assert 'name="query_throttle_max"' in resp.text


def test_save_app_settings_yaml_persists_and_switches_back_to_form(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    _stub_apprise(monkeypatch)

    try:
        yaml_text = (
            "query_throttle_max: 9\n"
            "query_throttle_window_s: 45.0\n"
            "query_min_spread_s: 2.0\n"
            "apprise_urls: json://yaml.example/hook\n"
            "apprise_notify_level: CRITICAL\n"
            "devices_page_most_recent_only: false\n"
            "staleness_sweep_interval_s: 900\n"
            "semantic_location_map: {}\n"
        )
        resp = client.post("/auth/settings/yaml", data={"yaml_text": yaml_text})
        assert resp.status_code == 200
        assert 'value="9"' in resp.text  # switched back to the form view
        assert "Edit as YAML" in resp.text

        saved = settings_store.load()
        assert saved["query_throttle_max"] == 9
        assert saved["apprise_urls"] == "json://yaml.example/hook"
        assert saved["apprise_notify_level"] == "CRITICAL"
        assert saved["devices_page_most_recent_only"] is False
    finally:
        _remove_apprise_handlers()


def test_save_app_settings_yaml_persists_a_semantic_location_map(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    _stub_apprise(monkeypatch)

    try:
        yaml_text = (
            "query_throttle_max: 9\n"
            "query_throttle_window_s: 45.0\n"
            "query_min_spread_s: 2.0\n"
            "apprise_urls: \"\"\n"
            "apprise_notify_level: WARNING\n"
            "devices_page_most_recent_only: false\n"
            "staleness_sweep_interval_s: 900\n"
            "semantic_location_map:\n"
            "  Nest Mini - Living Room:\n"
            "    latitude: 45.0\n"
            "    longitude: 9.0\n"
        )
        resp = client.post("/auth/settings/yaml", data={"yaml_text": yaml_text})
        assert resp.status_code == 200

        saved = settings_store.load()
        # No match_mode in the posted YAML - defaults to "full".
        assert saved["semantic_location_map"] == {
            "Nest Mini - Living Room": {"latitude": 45.0, "longitude": 9.0, "match_mode": "full"},
        }
    finally:
        _remove_apprise_handlers()


def test_save_app_settings_yaml_persists_a_partial_match_semantic_location_map(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    _stub_apprise(monkeypatch)

    try:
        yaml_text = (
            "query_throttle_max: 9\n"
            "query_throttle_window_s: 45.0\n"
            "query_min_spread_s: 2.0\n"
            "apprise_urls: \"\"\n"
            "apprise_notify_level: WARNING\n"
            "devices_page_most_recent_only: false\n"
            "staleness_sweep_interval_s: 900\n"
            "semantic_location_map:\n"
            "  Living Room:\n"
            "    latitude: 45.0\n"
            "    longitude: 9.0\n"
            "    match_mode: partial\n"
        )
        resp = client.post("/auth/settings/yaml", data={"yaml_text": yaml_text})
        assert resp.status_code == 200

        saved = settings_store.load()
        assert saved["semantic_location_map"] == {
            "Living Room": {"latitude": 45.0, "longitude": 9.0, "match_mode": "partial"},
        }
    finally:
        _remove_apprise_handlers()


def test_save_app_settings_yaml_rejects_an_invalid_match_mode(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    before = settings_store.load()
    yaml_text = (
        "query_throttle_max: 9\n"
        "query_throttle_window_s: 45.0\n"
        "query_min_spread_s: 2.0\n"
        "apprise_urls: \"\"\n"
        "apprise_notify_level: WARNING\n"
        "devices_page_most_recent_only: false\n"
        "staleness_sweep_interval_s: 900\n"
        "semantic_location_map:\n"
        "  Nest Mini - Living Room:\n"
        "    latitude: 45.0\n"
        "    longitude: 9.0\n"
        "    match_mode: sometimes\n"
    )
    resp = client.post("/auth/settings/yaml", data={"yaml_text": yaml_text})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert settings_store.load() == before


def test_save_app_settings_yaml_rejects_a_malformed_semantic_location_map(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    before = settings_store.load()
    yaml_text = (
        "query_throttle_max: 9\n"
        "query_throttle_window_s: 45.0\n"
        "query_min_spread_s: 2.0\n"
        "apprise_urls: \"\"\n"
        "apprise_notify_level: WARNING\n"
        "devices_page_most_recent_only: false\n"
        "staleness_sweep_interval_s: 900\n"
        "semantic_location_map:\n"
        "  Nest Mini - Living Room: not-a-mapping\n"
    )
    resp = client.post("/auth/settings/yaml", data={"yaml_text": yaml_text})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert settings_store.load() == before


def test_save_app_settings_yaml_rejects_invalid_yaml_without_persisting(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    before = settings_store.load()
    resp = client.post("/auth/settings/yaml", data={"yaml_text": "not: valid: yaml: ["})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert "Edit as form" in resp.text  # still in the YAML view

    assert settings_store.load() == before


def test_save_app_settings_yaml_rejects_a_missing_key(client, tmp_path, monkeypatch):
    from webui import config, settings_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    before = settings_store.load()
    resp = client.post("/auth/settings/yaml", data={"yaml_text": "query_throttle_max: 5\n"})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert settings_store.load() == before
