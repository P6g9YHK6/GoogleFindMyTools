import asyncio
import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict):
        payload = json.dumps(message)
        async with self._lock:
            connections = list(self._connections)

        for connection in connections:
            try:
                await connection.send_text(payload)
            except Exception:
                await self.disconnect(connection)


manager = ConnectionManager()
# Separate channel for browser-provisioning progress (see browser_provisioning.py),
# kept distinct from device-locate broadcasts above.
provision_manager = ConnectionManager()
# Separate channel for firmware build progress (see firmware_build.py).
firmware_manager = ConnectionManager()
