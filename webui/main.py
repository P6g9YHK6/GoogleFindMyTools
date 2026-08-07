import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from webui import browser_provisioning, notify, scheduler, settings_store, ws
from webui.auth_middleware import BasicAuthMiddleware
from webui.routers import auth, devices, locate, logs, register, settings, sound, vnc_proxy

BASE_DIR = pathlib.Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    notify.configure_apprise_logging(env=settings_store.apprise_env())
    scheduler.start_all()
    yield
    scheduler.stop_all()
    await browser_provisioning.on_shutdown()


app = FastAPI(title="GoogleFindMyTools Web UI", lifespan=lifespan)
app.add_middleware(BasicAuthMiddleware)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(devices.router)
app.include_router(locate.router)
app.include_router(sound.router)
app.include_router(register.router)
app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(logs.router)
app.include_router(vnc_proxy.router)


@app.websocket("/ws/locations")
async def ws_locations(websocket: WebSocket):
    await ws.manager.connect(websocket)
    try:
        while True:
            # Client doesn't send anything meaningful; just keep the socket open.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws.manager.disconnect(websocket)


@app.websocket("/ws/provision")
async def ws_provision(websocket: WebSocket):
    await ws.provision_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws.provision_manager.disconnect(websocket)
