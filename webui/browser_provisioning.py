import asyncio
import json
import logging
import os
import shutil
import urllib.request
import zipfile

from Auth.aas_token_retrieval import get_aas_token
from Auth.token_cache import get_cached_value
from webui import config
from webui.ws import provision_manager

logger = logging.getLogger("webui.browser_provisioning")

CHROME_FOR_TESTING_JSON_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
)
X_PACKAGES = ["xvfb", "x11vnc", "novnc", "websockify"]
# Bounds every apt-get/pkill call so a stuck lock, dead mirror, or hung
# process can never wedge the whole provisioning/teardown flow forever.
_SUBPROCESS_TIMEOUT_S = 180

_ACTIVE_PHASES = {"starting", "installing", "downloading", "extracting", "launching", "ready", "logging_in"}

_state = {"phase": "idle", "message": "", "percent": 0, "error": None}
_processes: dict[str, asyncio.subprocess.Process] = {}
_chrome_bin: str | None = None


def get_state() -> dict:
    return dict(_state)


async def start() -> dict:
    if _state["phase"] in _ACTIVE_PHASES:
        return {"started": False, "state": get_state()}

    await _set_state("starting", "Starting...", 0)
    asyncio.create_task(_run_flow())
    return {"started": True, "state": get_state()}


async def on_shutdown():
    if _state["phase"] in _ACTIVE_PHASES:
        await _teardown("error", "Shut down while provisioning.")


async def _set_state(phase: str, message: str, percent: int, error: str | None = None):
    _state.update(phase=phase, message=message, percent=percent, error=error)
    await provision_manager.broadcast({"type": "provision", **_state})


def _runtime_dir() -> str:
    d = config.GFMT_BROWSER_RUNTIME_DIR
    os.makedirs(d, exist_ok=True)
    return d


async def _wait(proc: asyncio.subprocess.Process, timeout: float = _SUBPROCESS_TIMEOUT_S) -> int:
    """Waits for a subprocess with a hard timeout, killing it if it hangs,
    instead of letting a stuck apt lock/pkill/etc. block forever."""
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Subprocess timed out after %ss, killing it", timeout)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return -1


async def _run_flow():
    global _chrome_bin
    try:
        await _install_x_stack()
        _chrome_bin = await _download_chrome()
        await _start_x_stack()

        runtime_dir = _runtime_dir()
        home_dir = os.path.join(runtime_dir, "home")
        os.makedirs(home_dir, exist_ok=True)
        os.environ["GFMT_CHROME_BINARY"] = _chrome_bin
        os.environ["GFMT_NONINTERACTIVE"] = "1"
        os.environ["HOME"] = home_dir

        await _set_state("ready", "Ready - complete the Google sign-in below.", 95)

        logged_in = False
        try:
            await asyncio.wait_for(
                asyncio.to_thread(get_aas_token),
                timeout=config.GFMT_BROWSER_IDLE_TIMEOUT_S,
            )
            logged_in = bool(get_cached_value("aas_token") and get_cached_value("fcm_credentials"))
        except asyncio.TimeoutError:
            logged_in = False

        if logged_in:
            await _teardown("done", "Signed in. Cleaning up...")
        else:
            await _teardown("timeout", "Timed out waiting for sign-in.")
    except Exception as e:
        logger.exception("Browser provisioning failed")
        await _teardown("error", f"Provisioning failed: {e}", error=str(e))


async def _install_x_stack():
    await _set_state("installing", "Installing X server and VNC tools...", 5)
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

    proc = await asyncio.create_subprocess_exec(
        "apt-get", "update",
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await _wait(proc)

    proc = await asyncio.create_subprocess_exec(
        "apt-get", "install", "-y", "--no-install-recommends", *X_PACKAGES,
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    rc = await _wait(proc)
    if rc != 0:
        raise RuntimeError("apt-get install of xvfb/x11vnc/novnc/websockify failed")

    await _set_state("installing", "X server and VNC tools installed.", 35)


async def _download_chrome() -> str:
    await _set_state("downloading", "Looking up the latest Chrome for Testing build...", 40)

    def _fetch_json():
        with urllib.request.urlopen(CHROME_FOR_TESTING_JSON_URL, timeout=30) as resp:
            return json.load(resp)

    data = await asyncio.to_thread(_fetch_json)
    stable = data["channels"]["Stable"]
    version = stable["version"]
    entry = next(d for d in stable["downloads"]["chrome"] if d["platform"] == "linux64")
    url = entry["url"]

    runtime_dir = _runtime_dir()
    zip_path = os.path.join(runtime_dir, "chrome-linux64.zip")

    await _set_state("downloading", f"Downloading Chrome for Testing {version}...", 45)
    await asyncio.to_thread(urllib.request.urlretrieve, url, zip_path)

    await _set_state("extracting", "Extracting Chrome...", 65)

    def _extract():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(runtime_dir)
        os.remove(zip_path)

    await asyncio.to_thread(_extract)

    chrome_bin = os.path.join(runtime_dir, "chrome-linux64", "chrome")
    os.chmod(chrome_bin, 0o755)

    await _set_state("extracting", "Chrome ready.", 70)
    return chrome_bin


async def _start_x_stack():
    await _set_state("launching", "Starting virtual display...", 75)
    _processes["xvfb"] = await asyncio.create_subprocess_exec(
        "Xvfb", ":99", "-screen", "0", "1280x900x24", "-nolisten", "tcp",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(1)

    await _set_state("launching", "Starting VNC server...", 82)
    _processes["x11vnc"] = await asyncio.create_subprocess_exec(
        "x11vnc", "-display", ":99", "-nopw", "-forever", "-shared", "-rfbport", "5900",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(1)

    await _set_state("launching", "Starting noVNC proxy...", 88)
    _processes["websockify"] = await asyncio.create_subprocess_exec(
        "websockify", "--web=/usr/share/novnc", "6901", "localhost:5900",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(1)


async def _teardown(final_phase: str, message: str, error: str | None = None):
    global _chrome_bin

    if _chrome_bin:
        try:
            proc = await asyncio.create_subprocess_exec("pkill", "-f", _chrome_bin)
            await _wait(proc, timeout=10)
        except FileNotFoundError:
            pass

    for proc in _processes.values():
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
    for proc in _processes.values():
        await _wait(proc, timeout=5)
    _processes.clear()

    try:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        proc = await asyncio.create_subprocess_exec(
            "apt-get", "purge", "-y", "--autoremove", *X_PACKAGES,
            env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await _wait(proc)
    except FileNotFoundError:
        pass

    chrome_dir = os.path.join(config.GFMT_BROWSER_RUNTIME_DIR, "chrome-linux64")
    shutil.rmtree(chrome_dir, ignore_errors=True)
    _chrome_bin = None

    await _set_state(final_phase, message, 100, error)
