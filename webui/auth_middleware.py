import base64
import hmac

from starlette.types import ASGIApp, Receive, Scope, Send

from webui import config


class BasicAuthMiddleware:
    """Gates the whole app behind a single shared password (WEBUI_PASSWORD).

    No-op if WEBUI_PASSWORD is unset, so the web UI stays usable without
    configuration for a trusted LAN. Any username is accepted; only the
    password is checked. Plain ASGI (not BaseHTTPMiddleware) so it also
    covers WebSocket handshakes, not just regular HTTP requests.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if not config.WEBUI_PASSWORD or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")

        if self._is_authorized(auth_header):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return

        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"www-authenticate", b'Basic realm="GoogleFindMyTools Web UI"'),
                (b"content-type", b"text/plain"),
            ],
        })
        await send({"type": "http.response.body", "body": b"Unauthorized"})

    @staticmethod
    def _is_authorized(auth_header: str) -> bool:
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[len("Basic "):]).decode("utf-8")
            _, _, password = decoded.partition(":")
        except Exception:
            return False
        return hmac.compare_digest(password, config.WEBUI_PASSWORD)
