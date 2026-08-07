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
