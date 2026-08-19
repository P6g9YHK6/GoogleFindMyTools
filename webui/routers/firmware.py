from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse

from webui import firmware_build, firmware_store
from webui.firmware_build import REPO_ROOT
from webui.templating import templates

router = APIRouter()


@router.get("/firmware")
async def firmware_page(request: Request):
    registered = [
        {**entry, "pair_date_str": datetime.fromtimestamp(entry["pair_date"]).strftime("%Y-%m-%d %H:%M:%S")}
        for entry in firmware_store.list_registered()
    ]
    # Lets firmware.js pre-fill the Advanced section when a known EID is
    # picked/typed, instead of resetting to defaults every time.
    build_settings_by_eid = {
        entry["eid_hex"]: {
            "device_name": entry["device_name"], "adv_interval_ms": entry["adv_interval_ms"],
            "tx_power_dbm": entry["tx_power_dbm"], "tracking_protection": entry["tracking_protection"],
        }
        for entry in registered
    }
    return templates.TemplateResponse(request, "firmware/page.html", {
        "registered": registered,
        "build_settings_by_eid": build_settings_by_eid,
        "state": firmware_build.get_state(),
    })


@router.post("/firmware/build/start")
async def firmware_build_start(
    board: str = Form(...), eid_hex: str = Form(...),
    device_name: str = Form("GFMT Tracker"), adv_interval_ms: int = Form(20),
    tx_power_dbm: int = Form(9), tracking_protection: str = Form("1"),
):
    eid_hex = eid_hex.strip()
    device_name = device_name.strip()
    protection = tracking_protection == "1"
    result = await firmware_build.start(board, eid_hex, device_name, adv_interval_ms,
                                         tx_power_dbm, protection)
    if result.get("started"):
        # Remember this EID's settings so picking it again pre-fills the same
        # values instead of resetting to defaults - see firmware_store.py.
        firmware_store.record_build_settings(eid_hex, device_name, adv_interval_ms,
                                              tx_power_dbm, protection)
    return result


@router.get("/firmware/build/poll")
async def firmware_build_poll():
    return firmware_build.get_state()


@router.get("/firmware/build/download")
async def firmware_build_download():
    state = firmware_build.get_state()
    if state["phase"] != "done" or not state["artifact_path"]:
        raise HTTPException(404, "No completed build available - build one on the Firmware page first.")
    return FileResponse(state["artifact_path"], filename=state["download_name"],
                         media_type="application/octet-stream")


@router.get("/firmware/zephyr-readme")
async def zephyr_readme(request: Request):
    readme_text = (REPO_ROOT / "ZephyrFirmware" / "README.md").read_text()
    return templates.TemplateResponse(request, "firmware/zephyr_readme.html", {
        "readme_text": readme_text,
    })
