"""Builds a flashable ESP32/ESP32-C3 binary with a given advertisement key
(EID) and Advanced-section values (device name, advertising interval, TX
power, unwanted-tracking-protection flag) baked in, driven from the Firmware
page (webui/routers/firmware.py). Same background-job shape as
webui/browser_provisioning.py: a module-level _state dict, an async
start()/_run_build() pair, and progress broadcast over a websocket
(webui/ws.py::firmware_manager) with a poll-endpoint backstop.

The ESP-IDF toolchain itself isn't baked into the Docker image - it's fetched
on demand and cached the first time anyone actually builds, see
webui/esp_idf_provisioning.py.

Never builds against the checked-in ESP32Firmware/ tree directly - each build
runs in its own throwaway copy under DATA_DIR/firmware_builds/, so concurrent
or repeated builds can never corrupt the repo's own source or each other. All
per-build values are injected by (re)writing main/build_config.h in that
throwaway copy - see _write_build_config() and ESP32Firmware/main/build_config.h's
own docstring.
"""

import asyncio
import json
import logging
import pathlib
import re
import shutil
import tempfile

from webui import config, esp_idf_provisioning
from webui.ws import firmware_manager

logger = logging.getLogger("webui.firmware_build")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIRMWARE_SRC = REPO_ROOT / "ESP32Firmware"

_BOARDS = {
    "esp32": "esp32",
    "esp32c3": "esp32c3",
}
_EID_RE = re.compile(r"[0-9a-fA-F]{40}")

# Advanced-section build values, and the bounds/defaults main/build_config.h ships
# with (see that file) - an unmodified Advanced section builds identically to the
# firmware's historical hardcoded behavior.
_DEVICE_NAME_MAX_LEN = 20
_ADV_INTERVAL_MIN_MS = 20
_ADV_INTERVAL_MAX_MS = 10240
_ADV_INTERVAL_UNIT_MS = 0.625

# Mirrors esp_power_level_t in ESP-IDF's esp_gap_ble_api.h - ESP32 (Bluedroid) only,
# NimBLE's equivalent for ESP32-C3 isn't wired up yet.
_TX_POWER_ENUM = {
    -12: "ESP_PWR_LVL_N12", -9: "ESP_PWR_LVL_N9", -6: "ESP_PWR_LVL_N6", -3: "ESP_PWR_LVL_N3",
    0: "ESP_PWR_LVL_N0", 3: "ESP_PWR_LVL_P3", 6: "ESP_PWR_LVL_P6", 9: "ESP_PWR_LVL_P9",
}

# Keep at most this many past build directories around (see _prune_old_builds)
# so DATA_DIR/firmware_builds doesn't grow without bound.
_MAX_KEPT_BUILDS = 5

_ACTIVE_PHASES = {"provisioning", "cloning", "installing_toolchain", "preparing", "building", "merging"}

_state = {
    "phase": "idle", "message": "", "percent": 0, "error": None,
    "artifact_path": None, "download_name": None,
}


def get_state() -> dict:
    return dict(_state)


def is_active() -> bool:
    return _state["phase"] in _ACTIVE_PHASES


async def start(board: str, eid_hex: str, device_name: str = "GFMT Tracker",
                 adv_interval_ms: int = 20, tx_power_dbm: int = 9,
                 tracking_protection: bool = True) -> dict:
    if _state["phase"] in _ACTIVE_PHASES:
        return {"started": False, "state": get_state()}

    if board not in _BOARDS:
        return {"started": False, "error": f"Unknown board {board!r}"}
    if not _EID_RE.fullmatch(eid_hex or ""):
        return {"started": False, "error": "Advertisement key must be exactly 40 hex characters"}

    device_name = (device_name or "").strip()
    for error in (
        _validate_device_name(device_name),
        _validate_adv_interval(adv_interval_ms),
        _validate_tx_power(tx_power_dbm),
    ):
        if error:
            return {"started": False, "error": error}

    await _set_state("preparing", "Preparing build...", 0, artifact_path=None, download_name=None)
    asyncio.create_task(_run_build(board, eid_hex, device_name, adv_interval_ms,
                                    tx_power_dbm, tracking_protection))
    return {"started": True, "state": get_state()}


def _validate_device_name(name: str) -> str | None:
    if not (1 <= len(name) <= _DEVICE_NAME_MAX_LEN):
        return f"Device name must be 1-{_DEVICE_NAME_MAX_LEN} characters"
    if any(ch in ('"', "\\") or not (0x20 <= ord(ch) <= 0x7e) for ch in name):
        return "Device name must be printable ASCII without quotes or backslashes"
    return None


def _validate_adv_interval(ms: int) -> str | None:
    if not isinstance(ms, int) or not (_ADV_INTERVAL_MIN_MS <= ms <= _ADV_INTERVAL_MAX_MS):
        return f"Advertising interval must be between {_ADV_INTERVAL_MIN_MS} and {_ADV_INTERVAL_MAX_MS} ms"
    return None


def _validate_tx_power(dbm: int) -> str | None:
    if dbm not in _TX_POWER_ENUM:
        levels = ", ".join(str(d) for d in sorted(_TX_POWER_ENUM))
        return f"TX power must be one of: {levels} dBm"
    return None


async def _set_state(phase: str, message: str, percent: int, error: str | None = None,
                      **extra):
    _state.update(phase=phase, message=message, percent=percent, error=error, **extra)
    await firmware_manager.broadcast({"type": "firmware", **_state})


async def _run_build(board: str, eid_hex: str, device_name: str = "GFMT Tracker",
                      adv_interval_ms: int = 20, tx_power_dbm: int = 9,
                      tracking_protection: bool = True):
    try:
        await _set_state("provisioning", "Checking ESP-IDF installation...", 0)
        await esp_idf_provisioning.provision(on_progress=_set_state)
        idf_env = await esp_idf_provisioning.get_env()
        idf_py = esp_idf_provisioning.idf_py_path()

        target = _BOARDS[board]
        builds_dir = config.DATA_DIR / "firmware_builds"
        builds_dir.mkdir(parents=True, exist_ok=True)
        _prune_old_builds(builds_dir)

        job_dir = pathlib.Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="build-", dir=str(builds_dir)))
        src_dir = job_dir / "ESP32Firmware"
        await asyncio.to_thread(shutil.copytree, FIRMWARE_SRC, src_dir)

        _write_build_config(src_dir, board, eid_hex, device_name, adv_interval_ms,
                             tx_power_dbm, tracking_protection)
        if target == "esp32c3":
            # The checked-in sdkconfig is generated for plain "esp32" - drop
            # the copy and run set-target so a fresh one gets generated for
            # this target instead. -D SDKCONFIG_DEFAULTS is required, not
            # optional: ESP-IDF does NOT auto-apply a sdkconfig.defaults.<target>
            # file just from its name/presence - that convention only kicks in
            # alongside a plain sdkconfig.defaults (which this project doesn't
            # have), so without spelling it out here CONFIG_BT_ENABLED/
            # CONFIG_BT_NIMBLE_ENABLED are silently never set and main.c fails
            # to compile on a missing esp_nimble_hci.h.
            (src_dir / "sdkconfig").unlink(missing_ok=True)
            await _set_state("preparing", f"Setting build target to {target}...", 15)
            await _run_cmd(
                ["python3", idf_py, "-D", "SDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32c3", "set-target", target],
                idf_env, src_dir, "preparing", 15, 25,
            )
        else:
            # esp32's checked-in sdkconfig already targets esp32, with custom
            # options (CONFIG_BT_ENABLED, Bluedroid, ...) main.c depends on
            # baked in. Running set-target here anyway would still "succeed"
            # (same target either way) but forces a fullclean + full
            # sdkconfig regen from bare Kconfig defaults - there's no
            # sdkconfig.defaults.esp32 to restore those custom options from,
            # so it silently disables BT and the build fails on a missing
            # esp_bt.h. `idf.py build` below reconciles the existing
            # sdkconfig against this IDF version on its own, non-
            # destructively, without needing set-target at all.
            await _set_state("preparing", "Using the checked-in build config for esp32...", 15)

        await _set_state("building", "Building firmware...", 25)
        await _run_cmd(["python3", idf_py, "build"], idf_env, src_dir, "building", 25, 85)

        await _set_state("merging", "Merging into a single flashable image...", 90)
        artifact_path = src_dir / "artifact.bin"
        await _merge_bin(idf_env, src_dir, artifact_path)

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


def _write_build_config(src_dir: pathlib.Path, board: str, eid_hex: str, device_name: str,
                         adv_interval_ms: int, tx_power_dbm: int, tracking_protection: bool):
    """Overwrites main/build_config.h (see that file) in this build's throwaway copy
    with the values chosen on the Firmware page - main.c #includes it, so this is the
    one place any of them get baked into the binary. Never touches the checked-in
    copy under ESP32Firmware/, only the copy under src_dir made by _run_build."""
    adv_interval_units = round(adv_interval_ms / _ADV_INTERVAL_UNIT_MS)
    frame_type = 0x41 if tracking_protection else 0x40
    lines = [
        "// Generated by webui/firmware_build.py for this build - overwritten on",
        "// every build, don't edit by hand.",
        "#pragma once",
        "",
        f'#define GFMT_EID_STRING "{eid_hex}"',
        f'#define GFMT_DEVICE_NAME "{device_name}"',
        f"#define GFMT_ADV_FRAME_TYPE 0x{frame_type:02x}",
        f"#define GFMT_ADV_INTERVAL_UNITS 0x{adv_interval_units:04x}",
    ]
    if board == "esp32":
        lines.append(f"#define GFMT_TX_POWER_LEVEL {_TX_POWER_ENUM[tx_power_dbm]}")
    (src_dir / "main" / "build_config.h").write_text("\n".join(lines) + "\n")


async def _run_cmd(cmd: list[str], env: dict, cwd: pathlib.Path, phase: str,
                    base_percent: int, cap_percent: int):
    """Runs one build step to completion, streaming its output into
    incremental phase updates (parsing ninja's "[123/456] ..." lines for a
    percent, same idea as browser_provisioning.py's apt-progress parsing)
    instead of sitting on one static message for the whole build. `env` is
    the on-demand ESP-IDF install's own environment (PATH/IDF_PATH/etc.) -
    see esp_idf_provisioning.get_env() - not this process's own, since
    idf.py/esptool.py aren't on this container's normal PATH."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd), env=env,
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
        raise RuntimeError(f"`{' '.join(cmd)}` timed out after "
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
        raise RuntimeError(f"`{' '.join(cmd)}` exited with code {rc}\n{tail}")


async def _merge_bin(idf_env: dict, src_dir: pathlib.Path, artifact_path: pathlib.Path):
    """Merges the built bootloader/app/partition-table into one flashable
    image via esptool.py directly, driven by the build's own
    build/flasher_args.json - idf.py's own "merge-bin" convenience action
    doesn't exist at all in ESP-IDF 5.1 (no CMake target, no Python action
    registered anywhere - it was added in a later release; running it just
    falls through to idf.py's generic "unknown target" passthrough, which
    doesn't accept an -o/--output flag). flasher_args.json's shape has been
    stable across ESP-IDF versions, so driving esptool.py from it directly
    works regardless of which version ends up provisioned."""
    build_dir = src_dir / "build"
    flasher_args = json.loads((build_dir / "flasher_args.json").read_text())
    settings = flasher_args["flash_settings"]
    chip = flasher_args["extra_esptool_args"]["chip"]

    cmd = [
        "esptool.py", "--chip", chip, "merge_bin",
        "--output", str(artifact_path),
        "--flash_mode", settings["flash_mode"],
        "--flash_size", settings["flash_size"],
        "--flash_freq", settings["flash_freq"],
    ]
    for offset, filename in flasher_args["flash_files"].items():
        cmd += [offset, filename]

    await _run_cmd(cmd, idf_env, build_dir, "merging", 90, 98)


def _prune_old_builds(builds_dir: pathlib.Path):
    dirs = sorted((d for d in builds_dir.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    for stale in dirs[:-_MAX_KEPT_BUILDS] if len(dirs) >= _MAX_KEPT_BUILDS else []:
        shutil.rmtree(stale, ignore_errors=True)
