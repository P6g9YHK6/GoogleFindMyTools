from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from webui import firmware_store, identity_validation
from webui.deps import register_tracker
from webui.templating import templates

router = APIRouter()

_DEFAULT_IDENTITY = firmware_store.DEFAULT_IDENTITY


@router.get("/register")
async def register_form():
    # The standalone Register page is now the "Register Tracker" section at
    # the top of the Firmware page - redirect old links/bookmarks there
    # instead of serving a page that no longer exists on its own.
    return RedirectResponse("/firmware")


@router.post("/register")
async def register_submit(
    request: Request,
    display_name: str = Form(_DEFAULT_IDENTITY["display_name"]),
    device_type: str = Form(_DEFAULT_IDENTITY["device_type"]),
    manufacturer_name: str = Form(_DEFAULT_IDENTITY["manufacturer_name"]),
    model_name: str = Form(_DEFAULT_IDENTITY["model_name"]),
    image_url: str = Form(_DEFAULT_IDENTITY["image_url"]),
    # An unchecked checkbox isn't posted at all - Form(False) is what
    # correctly resolves that absence to False (same pattern as
    # webui/routers/auth.py's devices_page_most_recent_only).
    experimental_official_app_compat: bool = Form(False),
    # Same "unchecked checkbox posts nothing" story as the one above -
    # Form(False) has to stay the server-side default regardless of the
    # checkbox's own checked-by-default *appearance* in the form (see
    # firmware/page.html): an HTML checkbox never distinguishes "present and
    # unchecked" from "absent", so the moment a user actually unchecks it,
    # it drops out of the POST body just the same. Defaulting to True here
    # instead would mean unchecking it silently did nothing.
    keep_track: bool = Form(False),
):
    display_name, manufacturer_name = display_name.strip(), manufacturer_name.strip()
    model_name, image_url = model_name.strip(), image_url.strip()

    # Pre-flight validation only - never reaches Google's API on bad input.
    # register_esp32() itself still raises straight through on a genuine
    # backend failure (see webui/deps.py's register_tracker() comment); this
    # only guards against malformed input reaching it in the first place.
    for error in (
        identity_validation._validate_display_name(display_name),
        identity_validation._validate_device_type(device_type),
        identity_validation._validate_manufacturer(manufacturer_name),
        identity_validation._validate_model(model_name),
        identity_validation._validate_image_url(image_url),
    ):
        if error:
            return templates.TemplateResponse(request, "firmware/_register_result.html",
                                               {"result": None, "error": error})

    result = await register_tracker(display_name=display_name, device_type=device_type,
                                      manufacturer_name=manufacturer_name, model_name=model_name,
                                      image_url=image_url,
                                      experimental_official_app_compat=experimental_official_app_compat)
    # Remember the (public) EID so the Firmware page can offer it again later
    # instead of requiring it be copy-pasted from this one-time display -
    # plus the identity actually submitted and the Keep track flag, so a
    # tracked entry is a standalone record (see firmware_store.py's
    # record_registration docstring / webui/tracked_registrations.py).
    firmware_store.record_registration(
        result["eid_hex"], result.get("pair_date", 0),
        display_name=display_name, device_type=device_type,
        manufacturer_name=manufacturer_name, model_name=model_name, image_url=image_url,
        experimental_official_app_compat=experimental_official_app_compat, keep_track=keep_track,
    )
    firmware_store.record_identity(display_name, device_type, manufacturer_name, model_name, image_url,
                                    experimental_official_app_compat)
    return templates.TemplateResponse(request, "firmware/_register_result.html",
                                       {"result": result, "error": None,
                                        "experimental_official_app_compat": experimental_official_app_compat})
