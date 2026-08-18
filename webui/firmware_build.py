"""Builds a flashable ESP32/ESP32-C3 binary with a given advertisement key
(EID) baked in, driven from the Firmware page (webui/routers/firmware.py).
Same background-job shape as webui/browser_provisioning.py: a module-level
_state dict, an async start()/_run_build() pair, and progress broadcast over
a websocket (webui/ws.py::firmware_manager) with a poll-endpoint backstop.

Never builds against the checked-in ESP32Firmware/ tree directly - each build
runs in its own throwaway copy under DATA_DIR/firmware_builds/, so concurrent
or repeated builds can never corrupt the repo's own source or each other.
"""

import asyncio
import logging
import pathlib
import re
import shutil
import tempfile

from webui import config
from webui.ws import firmware_manager

logger = logging.getLogger("webui.firmware_build")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIRMWARE_SRC = REPO_ROOT / "ESP32Firmware"

_BOARDS = {
    "esp32": "esp32",
    "esp32c3": "esp32c3",
}
_EID_RE = re.compile(r"[0-9a-fA-F]{40}")
_EID_LITERAL_RE = re.compile(r'const char \*eid_string = "[^"]*";')

# Keep at most this many past build directories around (see _prune_old_builds)
# so DATA_DIR/firmware_builds doesn't grow without bound.
_MAX_KEPT_BUILDS = 5

_ACTIVE_PHASES = {"preparing", "building", "merging"}

_state = {
    "phase": "idle", "message": "", "percent": 0, "error": None,
    "artifact_path": None, "download_name": None,
}


def get_state() -> dict:
    return dict(_state)


def is_active() -> bool:
    return _state["phase"] in _ACTIVE_PHASES


async def start(board: str, eid_hex: str) -> dict:
    if _state["phase"] in _ACTIVE_PHASES:
        return {"started": False, "state": get_state()}

    if board not in _BOARDS:
        return {"started": False, "error": f"Unknown board {board!r}"}
    if not _EID_RE.fullmatch(eid_hex or ""):
        return {"started": False, "error": "Advertisement key must be exactly 40 hex characters"}

    await _set_state("preparing", "Preparing build...", 0, artifact_path=None, download_name=None)
    asyncio.create_task(_run_build(board, eid_hex))
    return {"started": True, "state": get_state()}


async def _set_state(phase: str, message: str, percent: int, error: str | None = None,
                      **extra):
    _state.update(phase=phase, message=message, percent=percent, error=error, **extra)
    await firmware_manager.broadcast({"type": "firmware", **_state})


async def _run_build(board: str, eid_hex: str):
    try:
        idf_py = shutil.which("idf.py")
        if not idf_py:
            await _set_state(
                "error", "not-found", 0,
                error="ESP-IDF (idf.py) is not available on this server, so firmware can't be "
                      "built here. See ESP32Firmware/README.md to build and flash it manually "
                      "instead - the same source tree, just run by hand.",
            )
            return

        target = _BOARDS[board]
        builds_dir = config.DATA_DIR / "firmware_builds"
        builds_dir.mkdir(parents=True, exist_ok=True)
        _prune_old_builds(builds_dir)

        job_dir = pathlib.Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="build-", dir=str(builds_dir)))
        src_dir = job_dir / "ESP32Firmware"
        await asyncio.to_thread(shutil.copytree, FIRMWARE_SRC, src_dir)

        _inject_eid(src_dir, eid_hex)
        if target == "esp32c3":
            # The checked-in sdkconfig is generated for plain "esp32" - drop
            # the copy so `idf.py set-target` regenerates it and picks up
            # sdkconfig.defaults.esp32c3 for this target instead.
            (src_dir / "sdkconfig").unlink(missing_ok=True)

        await _set_state("preparing", f"Setting build target to {target}...", 5)
        await _run_idf(idf_py, src_dir, ["set-target", target], "preparing", 5, 20)

        await _set_state("building", "Building firmware...", 20)
        await _run_idf(idf_py, src_dir, ["build"], "building", 20, 85)

        await _set_state("merging", "Merging into a single flashable image...", 90)
        artifact_path = src_dir / "artifact.bin"
        await _run_idf(idf_py, src_dir, ["merge-bin", "-o", str(artifact_path)], "merging", 90, 98)

        if not artifact_path.exists():
            raise RuntimeError("Build finished but no merged artifact.bin was produced")

        download_name = f"gfmt-{board}-{eid_hex[:8]}.bin"
        await _set_state(
            "done", "Firmware built successfully.", 100,
            artifact_path=str(artifact_path), download_name=download_name,
        )
    except Exception as e:
        logger.exception("Firmware build failed")
        detail = str(e) or "no further details available, check server logs"
        await _set_state("error", f"Build failed ({type(e).__name__}): {detail}", 100, error=str(e))


def _inject_eid(src_dir: pathlib.Path, eid_hex: str):
    main_c = src_dir / "main" / "main.c"
    text = main_c.read_text()
    new_text, count = _EID_LITERAL_RE.subn(f'const char *eid_string = "{eid_hex}";', text)
    if count != 1:
        # main.c no longer has the exact literal this was written against -
        # fail loudly instead of silently shipping the placeholder EID.
        raise RuntimeError(
            f"Expected exactly one eid_string literal in main.c, found {count} - "
            "ESP32Firmware/main/main.c may have changed upstream."
        )
    main_c.write_text(new_text)


async def _run_idf(idf_py: str, cwd: pathlib.Path, args: list[str], phase: str,
                    base_percent: int, cap_percent: int):
    """Runs one `idf.py <args>` step, streaming its output into incremental
    phase updates (parsing ninja's "[123/456] ..." lines for a percent, same
    idea as browser_provisioning.py's apt-progress parsing) instead of
    sitting on one static message for the whole build."""
    proc = await asyncio.create_subprocess_exec(
        idf_py, *args, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    log_tail: list[str] = []
    ninja_step_re = re.compile(r"^\[(\d+)/(\d+)]")

    async def _drain():
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            log_tail.append(text)
            del log_tail[:-50]  # keep only the most recent lines for error reporting
            m = ninja_step_re.match(text)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                percent = base_percent + round(done / max(total, 1) * (cap_percent - base_percent))
                await _set_state(phase, f"{_state['message'].split(' (')[0]} ({done}/{total})",
                                  min(percent, cap_percent))

    drain_task = asyncio.create_task(_drain())
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=config.GFMT_FIRMWARE_BUILD_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"`idf.py {' '.join(args)}` timed out after "
                            f"{config.GFMT_FIRMWARE_BUILD_TIMEOUT_S}s")
    finally:
        # _drain() already exits on its own once stdout hits EOF (which
        # follows proc exiting above) - cancel only as a backstop against
        # that never happening, same discipline as browser_provisioning.py's
        # _report_apt_progress teardown.
        drain_task.cancel()
        try:
            await drain_task
        except asyncio.CancelledError:
            pass
    if rc != 0:
        tail = "\n".join(log_tail[-20:])
        raise RuntimeError(f"`idf.py {' '.join(args)}` exited with code {rc}\n{tail}")


def _prune_old_builds(builds_dir: pathlib.Path):
    dirs = sorted((d for d in builds_dir.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    for stale in dirs[:-_MAX_KEPT_BUILDS] if len(dirs) >= _MAX_KEPT_BUILDS else []:
        shutil.rmtree(stale, ignore_errors=True)
