from tests.conftest import FAKE_CANONIC_ID


def test_locate_success(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})
    assert resp.status_code == 200
    assert "map" in resp.text  # a google maps link is rendered for a non-semantic location


def test_locate_failure_renders_error_fragment_not_bare_500(client, monkeypatch):
    from webui.routers import locate

    async def boom(canonic_id, name, timeout=None):
        raise RuntimeError("decrypt failed")

    monkeypatch.setattr(locate, "locate_device", boom)

    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/locate", params={"name": "My Tracker"})
    assert resp.status_code == 200  # error is rendered inline, not a 500 - htmx doesn't swap those in
    assert "decrypt failed" in resp.text
