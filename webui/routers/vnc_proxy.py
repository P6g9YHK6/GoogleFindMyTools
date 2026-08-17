import asyncio
import logging

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from websockets.exceptions import ConnectionClosed

from webui import config

logger = logging.getLogger("webui.vnc_proxy")

router = APIRouter(prefix="/vnc")

_http_client = httpx.AsyncClient()


@router.get("/{path:path}")
async def proxy_static(path: str):
    """Reverse-proxies the browser container's noVNC static assets (vnc.html,
    app/, core/, ...) through the web UI's own origin, so the embedded Chrome
    login view is part of this app rather than a separately exposed port."""
    upstream = await _http_client.get(f"{config.BROWSER_NOVNC_URL}/{path}", timeout=10)
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


@router.websocket("/websockify")
async def proxy_websocket(websocket: WebSocket):
    """Relays the noVNC/websockify WebSocket through the web UI's own origin."""
    ws_url = config.BROWSER_NOVNC_URL.replace("http://", "ws://").replace("https://", "wss://") + "/websockify"
    requested_subprotocols = websocket.scope.get("subprotocols") or None

    try:
        async with websockets.connect(ws_url, subprotocols=requested_subprotocols) as backend:
            await websocket.accept(subprotocol=backend.subprotocol)

            async def client_to_backend():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await backend.send(data)
                except WebSocketDisconnect:
                    pass

            async def backend_to_client():
                try:
                    async for message in backend:
                        await websocket.send_bytes(message)
                except ConnectionClosed:
                    pass

            tasks = [asyncio.create_task(client_to_backend()), asyncio.create_task(backend_to_client())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except Exception:
        logger.debug("VNC relay ended", exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            logger.debug("VNC websocket close failed", exc_info=True)
