""""Export debug info" button on the Config page (see GitHub issue #23) - a
downloadable snapshot of a fresh device-list query plus a locate attempt for
every device, for attaching to a bug report instead of asking someone to
copy-paste logs by hand.

Bundled as a 7z archive (not zip - the stdlib's zipfile can't write encrypted
archives at all, and 7z's AES-256 is meaningfully stronger than zip's legacy
ZipCrypto anyway) via py7zr, built entirely in memory. A password is
optional: leave it blank for a plain local download, or set one so the
archive is safe to attach to a public issue or hand to someone else without
exposing device locations/emails in the clear.

Three independent toggles shape what actually goes in:
- include_live_query: run a fresh device-list + locate-all query. Off lets
  someone grab just the recent logs without touching Google's API at all
  (and without needing to be signed in for it).
- include_logs: fold in the last _LOG_LINES_LIMIT lines of both the system
  and forwarding logs - the Logs page already shows these, so this defaults
  off; a report that's just the API payload is sometimes all that's wanted.
- anonymize_locations: replaces each decrypted location's real coordinates/
  accuracy/altitude with random numbers and any semantic place name with
  random characters (regenerating map_links to match), so the *shape* of the
  decoded location data is still visible for debugging parsing/forwarding
  logic without exposing where the device actually was. Since that scrubbing
  only touches the decoded JSON, each device's locate/*/raw_hex.txt and
  protobuf_text.txt (the still-encrypted E2EE wire format underneath) are
  left out of the archive entirely rather than included un-scrubbed - see
  _ANONYMIZATION_NOTICE, which is also dropped into the archive itself as
  ANONYMIZATION_NOTICE.txt so this isn't a silent omission.
At least one of include_live_query/include_logs must be set - an archive
with neither would just be an empty manifest.

This route must never surface an actual account credential - it only goes
through request_device_list()/get_location_data_for_device(), which pull
tokens internally (via nova_request()) but never return them to the caller.
Never import Auth.token_cache/Auth.aas_token_retrieval/Auth.adm_token_retrieval
here.
"""

import asyncio
import io
import json
import random
import re
import string
import time
from urllib.parse import urlsplit

import py7zr
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse, Response
from google.protobuf import text_format

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import create_map_links
from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import custom_message_formatter, get_device_details, parse_device_list_protobuf
from SpotApi.UploadPrecomputedPublicKeyIds.upload_precomputed_public_key_ids import refresh_custom_trackers
from webui import config, settings_store, system_log_store
from webui.auth_state import is_logged_in
from webui.deps import locate_device_with_capture, run_blocking
from webui.device_list_cache import device_list_cache
from webui.forwarders import log_store as forward_log_store

router = APIRouter()

# Newest-first cap on each log store pulled into the archive - generous
# enough to cover "what happened around the time the issue occurred" without
# ballooning the download into the store's full multi-thousand-entry cap.
_LOG_LINES_LIMIT = 500

_URL_RE = re.compile(r"https?://[^\s)]+")


def _redact_urls(text: str) -> str:
    """Collapses any http(s) URL down to just its scheme+host, dropping path
    and query - some built-in forwarding presets embed an access token
    directly in the URL path (see webui/forwarders/policy.py's
    _redacted_endpoint_target, the same technique applied here), and
    webui/forwarders/log_store.py's stored entries are NOT already redacted
    for that. Applied uniformly to every forward-log string field, not just
    `target`, since it's cheap and a token could in principle end up
    reflected into `response` too."""
    def _strip(match: re.Match) -> str:
        parsed = urlsplit(match.group(0))
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/...(redacted)"
        return "(redacted-url)"
    return _URL_RE.sub(_strip, text or "")


async def _fetch_device_list_debug() -> dict:
    """Same request/parse/refresh_custom_trackers/get_device_details sequence
    webui/routers/devices.py's get_devices() uses - deliberately NOT read
    from webui/device_list_cache.py, since this export exists specifically to
    capture a fresh query, not whatever the last page load happened to see."""
    def _fetch():
        result_hex = request_device_list()
        device_list_proto = parse_device_list_protobuf(result_hex)
        refresh_custom_trackers(device_list_proto)
        text_dump = text_format.MessageToString(device_list_proto, message_formatter=custom_message_formatter)
        details = get_device_details(device_list_proto)
        return {"raw_hex": result_hex, "text_dump": text_dump, "details": details}

    result = await run_blocking(_fetch)
    # The Devices/Settings pages' own short-lived cache (webui/device_list_cache.py)
    # would otherwise keep serving a slightly-older copy for a few more
    # seconds after this fresh pull - invalidate it so they pick this one up
    # on their very next load too.
    device_list_cache.invalidate()
    return result


async def _locate_all(devices: list[dict]) -> dict[str, dict]:
    """Fires locate_device_with_capture() for every device concurrently
    (bounded by the same semaphore every other locate path shares - see
    webui/deps.py). One device's failure/timeout is recorded against just
    that device and never aborts the rest of the export."""
    async def _one(device: dict) -> tuple[str, dict]:
        canonic_id = device["canonic_id"]
        name = device.get("name") or canonic_id
        try:
            locations, capture = await locate_device_with_capture(canonic_id, name, timeout=config.LOCATE_TIMEOUT_S)
            outcome = "timeout" if capture.get("timed_out") else "ok"
            return canonic_id, {"outcome": outcome, "locations": locations, **capture}
        except Exception as e:
            return canonic_id, {"outcome": "error", "error": str(e)}

    if not devices:
        return {}
    results = await asyncio.gather(*(_one(d) for d in devices))
    return dict(results)


def _non_secret_settings_summary() -> dict:
    """Only the harmless, non-secret pieces of settings_store.load() - never
    the raw apprise_urls string, which can carry tokens in apprise's own
    non-http URL schemes (discord://, telegram://, ntfy://, ...) that
    _redact_urls's http(s)-only regex wouldn't catch."""
    settings = settings_store.load()
    return {
        "apprise_configured": bool(settings.get("apprise_urls")),
        "apprise_notify_level": settings.get("apprise_notify_level"),
        "query_throttle_max": settings.get("query_throttle_max"),
        "query_throttle_window_s": settings.get("query_throttle_window_s"),
        "query_min_spread_s": settings.get("query_min_spread_s"),
        "devices_page_most_recent_only": settings.get("devices_page_most_recent_only"),
        "staleness_sweep_interval_s": settings.get("staleness_sweep_interval_s"),
    }


def _random_text_like(value: str) -> str:
    """Same length as the original, so the archive still shows roughly what
    kind of thing was there (a short label vs. a full street address)
    without carrying any of the actual characters over."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(max(len(value), 6)))


def _anonymize_location(location: dict) -> dict:
    """Replaces one decrypted location's real coordinates/accuracy/altitude
    with random-but-plausible numbers, and any semantic place name with
    random characters - see this module's docstring for the full rationale.
    status/status_id/is_own_report/is_semantic/time are left alone: they're
    categorical/timing fields needed to debug parsing logic, not GPS data."""
    anon = dict(location)
    if anon.get("latitude") is not None:
        anon["latitude"] = round(random.uniform(-90, 90), 6)
    if anon.get("longitude") is not None:
        anon["longitude"] = round(random.uniform(-180, 180), 6)
    if anon.get("altitude") is not None:
        anon["altitude"] = round(random.uniform(-100, 3000), 2)
    if anon.get("accuracy") is not None:
        anon["accuracy"] = round(random.uniform(1, 500), 1)
    if anon.get("semantic_name"):
        anon["semantic_name"] = _random_text_like(anon["semantic_name"])
    if anon.get("map_links") and anon.get("latitude") is not None and anon.get("longitude") is not None:
        # Regenerated from the now-scrambled coordinates - the real ones
        # were baked into these URLs by the same create_map_links() call
        # decrypt_location_response_locations() itself uses.
        anon["map_links"] = create_map_links(anon["latitude"], anon["longitude"])
    return anon


_ANONYMIZATION_NOTICE = (
    "Location data in this export was anonymized: each device's decoded_locations.json has its real "
    "coordinates/accuracy/altitude replaced with random numbers and any semantic place name replaced with "
    "random characters.\n\n"
    "Because of that, this export deliberately leaves out locate/<device>/raw_hex.txt and "
    "protobuf_text.txt: they are the wire-format response the anonymization step doesn't touch, so "
    "including them anyway would defeat the point of anonymizing in the first place. Only the "
    "anonymized decoded_locations.json and status.json are included per device.\n\n"
    "Re-run the export with Anonymize location data turned off if you need the raw dumps too."
)


def _build_archive(
    device_list_debug: dict | None, locate_results: dict, include_logs: bool,
    anonymize_locations: bool, password: str,
) -> bytes:
    manifest = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "live_query_included": device_list_debug is not None,
        "device_count": len(device_list_debug["details"]) if device_list_debug else 0,
        "locate_outcomes": {cid: r["outcome"] for cid, r in locate_results.items()},
        "logs_included": include_logs,
        "locations_anonymized": anonymize_locations,
        "raw_location_dumps_omitted": anonymize_locations,
        "settings": _non_secret_settings_summary(),
    }

    buf = io.BytesIO()
    with py7zr.SevenZipFile(
        buf, "w", password=password or None,
        # Also hides filenames/archive structure, not just member content -
        # only worth the extra overhead when a password was actually given.
        header_encryption=bool(password),
    ) as archive:
        archive.writestr(json.dumps(manifest, indent=2, default=str), "manifest.json")
        if anonymize_locations:
            # A plain-text callout too, not just a manifest.json field - so
            # the reason locate/<device>/raw_hex.txt is missing is obvious
            # to whoever opens this archive without having to go dig through
            # the manifest first.
            archive.writestr(_ANONYMIZATION_NOTICE, "ANONYMIZATION_NOTICE.txt")

        if device_list_debug is not None:
            archive.writestr(device_list_debug["raw_hex"], "device_list/raw_hex.txt")
            archive.writestr(device_list_debug["text_dump"], "device_list/protobuf_text.txt")
            archive.writestr(
                json.dumps(device_list_debug["details"], indent=2, default=str), "device_list/decoded.json",
            )

            for canonic_id, r in locate_results.items():
                base = f"locate/{canonic_id}"
                archive.writestr(
                    json.dumps({"outcome": r["outcome"], "error": r.get("error")}, indent=2), f"{base}/status.json",
                )
                # The raw hex/protobuf text dumps carry the location as
                # still-encrypted E2EE ciphertext, not plaintext coordinates -
                # normally harmless to include. But anonymize_locations
                # promises a scrubbed export, and these two are the one
                # thing that promise can't actually cover, so they're left
                # out entirely rather than included un-scrubbed (see
                # _ANONYMIZATION_NOTICE above).
                if not anonymize_locations:
                    if "raw_hex" in r:
                        archive.writestr(r["raw_hex"], f"{base}/raw_hex.txt")
                    if "device_update_text" in r:
                        archive.writestr(r["device_update_text"], f"{base}/protobuf_text.txt")
                if "locations" in r:
                    locations = r["locations"]
                    if anonymize_locations:
                        locations = [_anonymize_location(loc) for loc in locations]
                    archive.writestr(json.dumps(locations, indent=2, default=str), f"{base}/decoded_locations.json")

        if include_logs:
            system_lines = system_log_store.recent_entries(limit=_LOG_LINES_LIMIT)
            forward_lines = forward_log_store.recent_entries(limit=_LOG_LINES_LIMIT)

            system_text = "\n".join(
                f"{e['time']}\t{e['level']}\t{e['logger']}\t{e['message']}" for e in system_lines
            )
            forward_text = "\n".join(
                f"{e['time']}\t{e['canonic_id']}\t{e['device_name']}\t{e['endpoint_type']}\t"
                f"{_redact_urls(e['target'])}\t{e['status']}\t{_redact_urls(e.get('payload', ''))}\t"
                f"{_redact_urls(e.get('response', ''))}"
                for e in forward_lines
            )
            archive.writestr(system_text, "logs/system_log.txt")
            archive.writestr(forward_text, "logs/forward_log.txt")

    return buf.getvalue()


@router.post("/auth/debug-export")
async def debug_export(
    password: str = Form(""),
    include_logs: bool = Form(False),
    # Defaults False, not True, deliberately - FastAPI/pydantic's bool
    # coercion for Form fields treats an empty-string value ("" - what the
    # frontend's JS always sends for an unchecked box, see
    # webui/static/debug_export.js) as "use the field's default" rather than
    # False, but only when that default is True. Keeping every boolean
    # toggle here defaulted to False sidesteps that quirk entirely: "" and
    # "true"/omitted then behave the same, predictable way for all three.
    include_live_query: bool = Form(False),
    anonymize_locations: bool = Form(False),
):
    # POST (not GET/<a download>) specifically so `password` never lands in
    # the URL - query strings end up in browser history and server access
    # logs, a form body doesn't.
    if not include_live_query and not include_logs:
        return JSONResponse({"error": "Select at least one of Live query or Logs to export."}, status_code=400)

    device_list_debug = None
    locate_results: dict = {}
    if include_live_query:
        # Only needed for the live query - a logs-only export needs no
        # Google account at all, so this check is skipped entirely when
        # include_live_query is off.
        if not is_logged_in():
            return JSONResponse({"error": "Not signed in - sign in first."}, status_code=400)

        try:
            device_list_debug = await _fetch_device_list_debug()
        except Exception as e:
            return JSONResponse({"error": f"Device list query failed: {e}"}, status_code=502)

        locate_results = await _locate_all(device_list_debug["details"])

    archive_bytes = _build_archive(device_list_debug, locate_results, include_logs, anonymize_locations, password)
    filename = f"gfmt-debug-export-{time.strftime('%Y%m%d-%H%M%S')}.7z"
    return Response(
        archive_bytes,
        media_type="application/x-7z-compressed",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
