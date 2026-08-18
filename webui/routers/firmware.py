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
    return templates.TemplateResponse(request, "firmware/page.html", {
        "registered": registered,
        "state": firmware_build.get_state(),
    })


@router.post("/firmware/build/start")
async def firmware_build_start(board: str = Form(...), eid_hex: str = Form(...)):
    return await firmware_build.start(board, eid_hex.strip())


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
