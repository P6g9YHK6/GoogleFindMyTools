import asyncio
import json
import logging
import os
import shutil
import urllib.request
import zipfile

from Auth import auth_flow
from Auth.aas_token_retrieval import get_aas_token
from Auth.token_cache import get_cached_value
from KeyBackup.shared_key_retrieval import get_shared_key
from webui import config
from webui.ws import provision_manager

logger = logging.getLogger("webui.browser_provisioning")

CHROME_FOR_TESTING_JSON_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
)
X_PACKAGES = ["xvfb", "x11vnc", "novnc", "websockify"]
# Chrome for Testing is downloaded as a bare binary (see _download_chrome), so
# the shared libraries it dlopen's at startup have to come from apt instead -
# without these the launch fails with a "Chrome was not detected" error even
# though the binary is right there and executable.
CHROME_DEPS = [
    "fonts-liberation", "libasound2", "libatk-bridge2.0-0", "libatk1.0-0",
    "libcups2", "libdrm2", "libgbm1", "libgtk-3-0", "libnspr4", "libnss3",
    "libpango-1.0-0", "libpangocairo-1.0-0", "libx11-xcb1", "libxcomposite1",
    "libxdamage1", "libxfixes3", "libxkbcommon0", "libxrandr2", "xdg-utils",
]
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

        await _set_state(
            "ready",
            f"Ready - complete the Google sign-in below within {auth_flow.SIGN_IN_WAIT_S // 60} minutes.",
            95,
        )

        logged_in = False
        timeout_message = None
        try:
            await asyncio.wait_for(
                asyncio.to_thread(get_aas_token),
                timeout=config.GFMT_BROWSER_IDLE_TIMEOUT_S,
            )
            account_signed_in = bool(get_cached_value("aas_token") and get_cached_value("fcm_credentials"))

            if account_signed_in:
                # Locating a device also needs a "shared key" to decrypt its
                # end-to-end encrypted location reports, which requires its own
                # separate Google sign-in (see KeyBackup/shared_key_flow.py) -
                # do it now, in the same browser/VNC session, rather than
                # leaving it to fail later the first time something calls
                # locate_device outside of any browser session at all.
                await _set_state(
                    "logging_in",
                    "Signed in. Google needs one more confirmation to allow decrypting "
                    f"end-to-end encrypted location reports - complete it below within "
                    f"{auth_flow.SIGN_IN_WAIT_S // 60} minutes.",
                    97,
                )
                await asyncio.wait_for(
                    asyncio.to_thread(get_shared_key),
                    timeout=config.GFMT_BROWSER_IDLE_TIMEOUT_S,
                )
                logged_in = bool(get_cached_value("shared_key"))
        except TimeoutError as e:
            # Note: since Python 3.11, asyncio.TimeoutError *is* TimeoutError, so this
            # catches both the sign-in flows' own "you took too long" TimeoutErrors
            # (each with its own specific message, whichever step it came from) and
            # asyncio.wait_for's outer safety-net timeout (which doesn't) - fall back
            # to a generic message only for the latter, rather than showing a blank
            # or misleading one for either.
            timeout_message = str(e) or (
                f"Timed out waiting for sign-in - no sign-in activity detected within "
                f"{config.GFMT_BROWSER_IDLE_TIMEOUT_S}s of the browser being ready. "
                f"Click \"Sign in with Google\" again to retry."
            )

        if logged_in:
            await _teardown("done", "Signed in successfully. Removing the temporary browser...")
        elif timeout_message:
            await _teardown("timeout", timeout_message)
        else:
            await _teardown("timeout", "Sign-in did not complete. Click \"Sign in with Google\" again to retry.")
    except Exception as e:
        logger.exception("Browser provisioning failed")
        detail = str(e) or "no further details available, check server logs"
        await _teardown(
            "error",
            f"Provisioning failed ({type(e).__name__}): {detail}",
            error=str(e),
        )


async def _report_apt_progress(proc: asyncio.subprocess.Process, packages: list[str]):
    """Turns apt's "Setting up <pkg>" lines into incremental phase updates, so
    a ~20-package install doesn't just sit on one static message for the
    better part of a minute. Runs concurrently with _wait(proc) below, since
    something has to keep draining stdout or apt can deadlock writing to a
    full pipe once its output outgrows the OS pipe buffer."""
    total = len(packages)
    installed = 0
    base_percent, cap_percent = 8, 33
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text.startswith("Setting up "):
                installed += 1
                # "Setting up libgtk-3-0:amd64 (3.24.38-2ubuntu1) ..." -> "libgtk-3-0"
                name = text[len("Setting up "):].split(" ", 1)[0].split(":")[0]
                # Transitive dependencies not in our own list also print a
                # "Setting up" line, so `installed` can exceed `total` - clamp
                # both the percent and the displayed counter for that case.
                percent = min(base_percent + round(installed / total * (cap_percent - base_percent)), cap_percent)
                await _set_state(
                    "installing",
                    f"Installing X server and VNC tools... ({min(installed, total)}/{total}: {name})",
                    percent,
                )
    except asyncio.CancelledError:
        pass


async def _install_x_stack():
    await _set_state("installing", "Updating package lists...", 5)
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

    proc = await asyncio.create_subprocess_exec(
        "apt-get", "update",
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await _wait(proc)

    packages = [*X_PACKAGES, *CHROME_DEPS]
    await _set_state("installing", f"Installing X server and VNC tools... (0/{len(packages)})", 8)

    proc = await asyncio.create_subprocess_exec(
        "apt-get", "install", "-y", "--no-install-recommends", *packages,
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    progress_task = asyncio.create_task(_report_apt_progress(proc, packages))
    rc = await _wait(proc)
    progress_task.cancel()
    try:
        await progress_task
    except asyncio.CancelledError:
        pass
    if rc != 0:
        raise RuntimeError("apt-get install of xvfb/x11vnc/novnc/websockify/chrome-deps failed")

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
            "apt-get", "purge", "-y", "--autoremove", *X_PACKAGES, *CHROME_DEPS,
            env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await _wait(proc)
    except FileNotFoundError:
        pass

    chrome_dir = os.path.join(config.GFMT_BROWSER_RUNTIME_DIR, "chrome-linux64")
    shutil.rmtree(chrome_dir, ignore_errors=True)
    _chrome_bin = None

    await _set_state(final_phase, message, 100, error)
