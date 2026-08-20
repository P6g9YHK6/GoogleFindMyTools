from collections.abc import Callable
from itertools import zip_longest
from typing import Any

import yaml
from fastapi import APIRouter, Form, Request

from Auth.fcm_receiver import FcmReceiver
from Auth.token_cache import clear_all_cached_values, get_cached_value
from webui import browser_provisioning, notify, settings_store
from webui.auth_state import is_logged_in
from webui.deps import query_gate
from webui.templating import templates


def _to_bool(value) -> bool:
    """Used as an _APP_SETTINGS_SCHEMA caster - plain bool(value) would
    treat any non-empty string (including the literal text "false", if
    someone quotes it that way editing the YAML view) as True. A real YAML
    boolean already comes out of yaml.safe_load as an actual bool, so this
    only has to special-case the string form."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


_SEMANTIC_MATCH_MODES = ("full", "partial")


def _to_semantic_map(value) -> dict:
    """Used as an _APP_SETTINGS_SCHEMA caster for the YAML-edit path - see
    _parse_semantic_map_form for the structured-form equivalent. Expects
    {name: {"latitude": ..., "longitude": ..., "match_mode": "full"|
    "partial"}}; raises (caught by _validate_app_settings, same as every
    other caster here) on anything else, including a name with no
    coordinates, a non-numeric one, or an unrecognized match_mode.
    match_mode itself is optional and defaults to "full" - entries saved
    before this field existed still validate."""
    if not isinstance(value, dict):
        raise TypeError("not a mapping")
    result = {}
    for name, coords in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("semantic name must be a non-empty string")
        if not isinstance(coords, dict):
            raise TypeError("coordinates must be a mapping")
        match_mode = coords.get("match_mode", "full")
        if match_mode not in _SEMANTIC_MATCH_MODES:
            raise ValueError(f"match_mode must be one of {_SEMANTIC_MATCH_MODES}")
        result[name] = {
            "latitude": float(coords["latitude"]),
            "longitude": float(coords["longitude"]),
            "match_mode": match_mode,
        }
    return result


def _parse_semantic_map_form(form) -> dict:
    """Structured-form equivalent of _to_semantic_map above - reads the
    semantic_name[]/semantic_lat[]/semantic_lon[]/semantic_match_mode[]
    quadruples posted by the "Semantic location mapping" table (see
    auth/_app_settings.html), same parallel-list convention as
    webui/forwarders/settings_service.py's parse_kv_rows for endpoint
    headers. A row with a blank name or a non-numeric lat/lon is silently
    dropped rather than rejecting the whole save - the same "just skip a
    genuinely empty row" leniency an unchecked checkbox or blank text field
    gets elsewhere on this form. An unrecognized/missing match_mode falls
    back to "full" instead of dropping the row - coordinates are what make
    a row valid, not the match type."""
    names = form.getlist("semantic_name")
    lats = form.getlist("semantic_lat")
    lons = form.getlist("semantic_lon")
    match_modes = form.getlist("semantic_match_mode")
    result = {}
    for name, lat, lon, match_mode in zip_longest(names, lats, lons, match_modes, fillvalue=""):
        name = name.strip()
        if not name:
            continue
        try:
            result[name] = {
                "latitude": float(lat),
                "longitude": float(lon),
                "match_mode": match_mode if match_mode in _SEMANTIC_MATCH_MODES else "full",
            }
        except (TypeError, ValueError):
            continue
    return result


_APP_SETTINGS_SCHEMA: dict[str, Callable[[Any], Any]] = {
    "query_throttle_max": int,
    "query_throttle_window_s": float,
    "query_min_spread_s": float,
    "apprise_urls": str,
    "apprise_notify_level": str,
    "devices_page_most_recent_only": _to_bool,
    "staleness_sweep_interval_s": int,
    "semantic_location_map": _to_semantic_map,
}

router = APIRouter()

# Every credential the sign-in flow can produce - shown as a per-key present/
# missing breakdown on the Config page instead of just one pass/fail bit, so
# a partial failure (e.g. aas_token cached but fcm_credentials never got
# written) is visible at a glance instead of needing to shell in and read
# secrets.json by hand to find out, as happened repeatedly while chasing that
# exact bug.
_DIAGNOSTIC_KEYS = ["username", "aas_token", "fcm_credentials", "shared_key", "owner_key"]


def _auth_status() -> dict:
    return {
        "logged_in": is_logged_in(),
        "username": get_cached_value("username"),
        # The account sign-in and the E2EE shared-key confirmation are two
        # separate steps (see webui/browser_provisioning.py) - surface both,
        # since being "logged in" alone doesn't mean locate will work yet.
        "shared_key_ready": get_cached_value("shared_key") is not None,
        "diagnostics": [
            {"name": name, "present": get_cached_value(name) is not None}
            for name in _DIAGNOSTIC_KEYS
        ],
        # Set if the browser/X11 processes from the last sign-in attempt
        # didn't all exit cleanly on their own - see _teardown() in
        # webui/browser_provisioning.py.
        "cleanup_warning": browser_provisioning.get_state().get("cleanup_warning"),
    }


@router.get("/auth")
async def auth_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {
        "status": _auth_status(),
        "app_settings": settings_store.load(),
    })


@router.post("/auth/settings")
async def save_app_settings(
    request: Request,
    query_throttle_max: int = Form(...),
    query_throttle_window_s: float = Form(...),
    query_min_spread_s: float = Form(...),
    apprise_urls: str = Form(""),
    apprise_notify_level: str = Form("WARNING"),
    # An unchecked checkbox simply isn't posted at all - Form(False) is what
    # correctly resolves that absence to False, same as every other missing-
    # field default here (nothing browser-side to distinguish "off" from
    # "never touched" for a plain, non-htmx form like this one).
    devices_page_most_recent_only: bool = Form(False),
    staleness_sweep_interval_s: int = Form(3600),
):
    # The semantic-name/lat/lon rows are a dynamic, variable-length table
    # (see auth/_app_settings.html) - posted as parallel
    # semantic_name[]/semantic_lat[]/semantic_lon[] lists, so they're read
    # straight off the raw form rather than as individual Form(...) params
    # like everything else above (same reason
    # webui/forwarders/settings_service.py's endpoint headers/blocked
    # statuses go through raw form parsing instead).
    form = await request.form()
    app_settings = {
        "query_throttle_max": query_throttle_max,
        "query_throttle_window_s": query_throttle_window_s,
        "query_min_spread_s": query_min_spread_s,
        "apprise_urls": apprise_urls,
        "apprise_notify_level": apprise_notify_level,
        "devices_page_most_recent_only": devices_page_most_recent_only,
        "staleness_sweep_interval_s": staleness_sweep_interval_s,
        "semantic_location_map": _parse_semantic_map_form(form),
    }
    _apply_app_settings(app_settings)

    return templates.TemplateResponse(request, "auth/_app_settings.html", {
        "app_settings": app_settings,
        "saved": True,
    })


def _apply_app_settings(app_settings: dict):
    settings_store.save(app_settings)
    # Apply the (possibly new) Apprise settings immediately, same as the
    # throttle settings take effect on QueryGate's very next wait_turn() call
    # - no restart needed for either.
    notify.configure_apprise_logging(env=settings_store.apprise_env())


def _validate_app_settings(parsed) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("must be a mapping, not a list or a bare value")
    result = {}
    for key, caster in _APP_SETTINGS_SCHEMA.items():
        if key not in parsed:
            raise ValueError(f"missing key {key!r}")
        try:
            result[key] = caster(parsed[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key!r} must be a {caster.__name__}") from None
    return result


@router.get("/auth/settings")
async def app_settings_form_route(request: Request):
    """Re-renders just the structured form - the "Edit as form" button's
    target when switching back out of the YAML view below."""
    return templates.TemplateResponse(request, "auth/_app_settings.html", {
        "app_settings": settings_store.load(),
    })


@router.get("/auth/settings/yaml")
async def app_settings_yaml_route(request: Request):
    yaml_text = yaml.safe_dump(settings_store.load(), sort_keys=False, allow_unicode=True)
    return templates.TemplateResponse(request, "auth/_app_settings_yaml.html", {
        "yaml_text": yaml_text,
    })


@router.post("/auth/settings/yaml")
async def save_app_settings_yaml_route(request: Request, yaml_text: str = Form(...)):
    try:
        app_settings = _validate_app_settings(yaml.safe_load(yaml_text))
    except (yaml.YAMLError, ValueError) as e:
        return templates.TemplateResponse(request, "auth/_app_settings_yaml.html", {
            "yaml_text": yaml_text,
            "error": f"Invalid YAML: {e}",
        })

    _apply_app_settings(app_settings)

    return templates.TemplateResponse(request, "auth/_app_settings.html", {
        "app_settings": app_settings,
        "saved": True,
    })


@router.get("/auth/queue")
async def auth_queue_status(request: Request):
    # Polled independently of /auth/status (see auth/login.html) - the queue
    # depth changes far more often than sign-in status, and shouldn't compete
    # with the sign-in flow's own hx-swaps into #login-status.
    return templates.TemplateResponse(request, "auth/_queue_status.html", {
        "waiting": query_gate.waiting,
    })


@router.get("/auth/status")
async def auth_status(request: Request):
    # Returns the same HTML fragment used on /auth (not raw JSON) - its only
    # caller is the "Refresh status" button's hx-get/hx-swap into #login-status.
    return templates.TemplateResponse(request, "auth/_status.html", {
        "status": _auth_status(),
    })


@router.post("/auth/clear")
async def auth_clear(request: Request):
    if browser_provisioning.is_active():
        # Clearing mid-flow is exactly how the "aas_token present but
        # fcm_credentials missing" split-brain state kept happening: a sign-in
        # already past its own FCM registration step gets its cache wiped out
        # from under it, then goes on to write a fresh aas_token into the now-
        # empty file with nothing left to re-populate fcm_credentials. Refuse
        # instead, matching the same guard start() already uses.
        return templates.TemplateResponse(request, "auth/_status.html", {
            "status": _auth_status(),
            "clear_error": "A sign-in is currently in progress - let it finish, time out, "
                            "or fail before clearing credentials.",
        })

    clear_all_cached_values()
    # FcmReceiver is an in-process singleton that reads fcm_credentials from
    # the cache once, at first use, and never again - clearing the file alone
    # would leave it silently serving its old in-memory copy forever, so the
    # very next sign-in would look successful but never actually re-register
    # (exactly the bug chased earlier: aas_token comes back fine, fcm_credentials
    # never does, with no error either time). Reset it too so a fresh sign-in
    # right after this button actually starts clean.
    FcmReceiver().clear()
    return templates.TemplateResponse(request, "auth/_status.html", {
        "status": _auth_status(),
    })


@router.post("/auth/login/start")
async def auth_login_start():
    return await browser_provisioning.start()


@router.get("/auth/login/poll")
async def auth_login_poll():
    return browser_provisioning.get_state()
