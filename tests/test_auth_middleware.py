import base64

from webui import config


def _basic(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_no_auth_configured_passes_through(client, monkeypatch):
    monkeypatch.setattr(config, "HTTP_USER", None)
    monkeypatch.setattr(config, "HTTP_PASSWORD", None)

    resp = client.get("/auth/login/poll")
    assert resp.status_code == 200


def test_http_user_and_password_require_both_to_match(client, monkeypatch):
    monkeypatch.setattr(config, "HTTP_USER", "alice")
    monkeypatch.setattr(config, "HTTP_PASSWORD", "secret")

    assert client.get("/auth/login/poll").status_code == 401
    assert client.get("/auth/login/poll", headers=_basic("alice", "secret")).status_code == 200
    assert client.get("/auth/login/poll", headers=_basic("bob", "secret")).status_code == 401
    assert client.get("/auth/login/poll", headers=_basic("alice", "wrong")).status_code == 401


def test_partial_config_leaves_auth_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "HTTP_USER", "alice")
    monkeypatch.setattr(config, "HTTP_PASSWORD", None)

    assert client.get("/auth/login/poll").status_code == 200
