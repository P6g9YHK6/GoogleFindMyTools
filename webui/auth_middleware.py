import base64
import hmac
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from webui import config

logger = logging.getLogger("webui.auth_middleware")


class BasicAuthMiddleware:
    """Gates the whole app behind HTTP Basic Auth: HTTP_USER + HTTP_PASSWORD.

    No-op if either is unset, so the web UI stays usable without
    configuration for a trusted LAN. Plain ASGI (not BaseHTTPMiddleware) so
    it also covers WebSocket handshakes, not just regular HTTP requests.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _enabled() -> bool:
        return bool(config.HTTP_USER and config.HTTP_PASSWORD)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if not self._enabled() or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http" and scope.get("path") == "/health":
            # Docker's HEALTHCHECK (see docker/web/healthcheck.py) hits this
            # from inside the container with no credentials, and it reveals
            # nothing beyond "the process is up" - not worth making the
            # container orchestrator's liveness probe carry HTTP_USER/
            # HTTP_PASSWORD around to ask a question this trivial.
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")

        if self._is_authorized(auth_header):
            await self.app(scope, receive, send)
            return

        if auth_header:
            # Only log when credentials were actually sent and rejected - not
            # on every plain request, since a browser's very first hit of any
            # protected page has no Authorization header at all (that's what
            # prompts it to ask the user for one), and logging that as a
            # "failed login" would just be noise on every normal visit.
            client = scope.get("client")
            client_host = client[0] if client else "unknown"
            logger.warning("Rejected %s request from %s: invalid credentials", scope["type"], client_host)

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return

        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"www-authenticate", b'Basic realm="GoogleFindMyToolsWebUi"'),
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
            username, _, password = decoded.partition(":")
        except Exception:
            return False

        return (
            hmac.compare_digest(username, config.HTTP_USER)
            and hmac.compare_digest(password, config.HTTP_PASSWORD)
        )
