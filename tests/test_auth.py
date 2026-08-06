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
