import asyncio
import logging
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from webui import (
    auth_state,
    browser_provisioning,
    config,
    log_capture,
    notify,
    scheduler,
    settings_store,
    staleness,
    ws,
)
from webui.auth_middleware import BasicAuthMiddleware
from webui.forwarders import config_store
from webui.routers import (
    auth,
    debug_export,
    devices,
    firmware,
    locate,
    logs,
    metrics,
    register,
    settings,
    sound,
    vnc_proxy,
)
from webui.routers import staleness as staleness_router

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
    # Independent of scheduler.start_all() above - see webui/staleness.py's
    # own docstring for why a device with no forwarding endpoints (never
    # polled by any of that module's per-device loops) still needs this.
    staleness_task = asyncio.create_task(staleness.sweep_loop())
    yield
    scheduler.stop_all()
    staleness_task.cancel()
    await browser_provisioning.on_shutdown()


app = FastAPI(title="GoogleFindMyToolsWebUi", lifespan=lifespan)
app.add_middleware(BasicAuthMiddleware)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(devices.router)
app.include_router(locate.router)
app.include_router(sound.router)
app.include_router(register.router)
app.include_router(firmware.router)
app.include_router(auth.router)
app.include_router(debug_export.router)
app.include_router(settings.router)
app.include_router(logs.router)
app.include_router(metrics.router)
app.include_router(staleness_router.router)
app.include_router(vnc_proxy.router)


@app.get("/health")
async def health():
    """Readiness probe for Docker's HEALTHCHECK (see docker/web/healthcheck.py)
    - beyond just confirming the app is up and answering, checks a handful
    of ways it can keep answering fine while silently broken underneath:
    a device's polling task crashed (webui/scheduler.py), forwarding.yaml
    or auth.yaml failed to load (webui/forwarders/config_store.py,
    Auth/token_cache.py), or the data directory stopped being writable.
    Every check here is in-memory/stat-only - no blocking I/O, no network
    calls - so this stays safe to poll every 30s. Exempt from
    BasicAuthMiddleware (see webui/auth_middleware.py) since the
    container's own healthcheck can't practically carry credentials."""
    problems = []
    if dead := scheduler.dead_tasks():
        problems.append(f"{len(dead)} device polling task(s) crashed")
    if not config_store.last_load_ok():
        problems.append("forwarding.yaml failed to load")
    if not auth_state.auth_store_ok():
        problems.append("auth.yaml failed to load")
    if not os.access(config.DATA_DIR, os.W_OK):
        problems.append(f"{config.DATA_DIR} is not writable")

    if problems:
        return JSONResponse({"status": "unhealthy", "problems": problems}, status_code=503)
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


@app.websocket("/ws/firmware")
async def ws_firmware(websocket: WebSocket):
    await ws.firmware_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws.firmware_manager.disconnect(websocket)
