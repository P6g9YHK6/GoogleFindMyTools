"""Light coverage only - vnc_proxy relays an ephemeral browser container that
only exists during a live sign-in, so there's no real backend to test against
in CI. Just confirm the proxy route processes an upstream response correctly
without needing one running."""

import httpx


def test_static_proxy_relays_upstream_response(client, monkeypatch):
    from webui.routers import vnc_proxy

    async def fake_get(url, timeout=10):
        return httpx.Response(200, content=b"<html>vnc</html>", headers={"content-type": "text/html"})

    monkeypatch.setattr(vnc_proxy._http_client, "get", fake_get)

    resp = client.get("/vnc/vnc.html")
    assert resp.status_code == 200
    assert resp.content == b"<html>vnc</html>"
