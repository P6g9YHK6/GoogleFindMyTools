import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from webui import browser_provisioning, log_capture, notify, scheduler, settings_store, ws
from webui.auth_middleware import BasicAuthMiddleware
from webui.routers import auth, devices, locate, logs, register, settings, sound, vnc_proxy

# Every module across the app (webui.*, Auth.*, NovaApi.*, ...) logs through
# the standard `logging` module and propagates up to root - this is the one
# place that turns those calls into something visible at all. Without it,
# only WARNING+ would reach Python's built-in last-resort stderr handler and
# anything at INFO (e.g. "Requesting location data for X...") would be
# silently dropped instead of showing up in `docker logs` the way the prints
# they replaced used to. Set up before uvicorn's own dictConfig runs (this
# module is imported first), so it doesn't get skipped as a no-op.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = pathlib.Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    notify.configure_apprise_logging(env=settings_store.apprise_env())
    log_capture.configure_log_capture()
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


@app.get("/health")
async def health():
    """Liveness probe for Docker's HEALTHCHECK (see docker/web/healthcheck.py)
    - just confirms the app is up and answering, no real work done. Exempt
    from BasicAuthMiddleware (see webui/auth_middleware.py) since the
    container's own healthcheck can't practically carry credentials."""
    return {"status": "ok"}


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
