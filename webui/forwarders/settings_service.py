"""Business logic behind the Settings page's routes
(webui/routers/settings.py): fetching+merging device rows, YAML<->form
conversion, and parsing the posted endpoints form. Split out of the router
itself so it stays thin, matching every other router in the app - this used
to be 681 lines of routing and parsing/conversion logic in one file.
"""

import json
from typing import Any

import yaml
from croniter import croniter
from starlette.datastructures import FormData

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_device_details, parse_device_list_protobuf
from webui import device_location_store, scheduler
from webui.deps import run_blocking
from webui.device_list_cache import device_list_cache
from webui.forwarders import build_context, config_store, device_label_variables, latest_values_store, policy
from webui.routers.devices import device_type_plain_label


def device_meta_from_detail(detail: dict) -> dict:
    """The subset of get_device_details' per-device dict worth persisting
    into devices.yaml so the poll loop can read it at forward time (see
    webui/forwarders/custom.py's device_meta handling, and rows()'s
    google_name sync just below for why persisting it here at all is
    necessary - webui/scheduler.py never talks to Google's device-list API
    itself). shared_with mirrors webui/routers/devices.py's own
    computation, but joined into a comma-separated string rather than a
    list - this ends up substituted directly into request text (a URL,
    header, or body), which a Python list never could be."""
    shared_with = ", ".join(a["email"] for a in detail["access"] if not a["this_account"])
    return {
        "manufacturer": detail["manufacturer"] or "",
        "model": detail["model"] or "",
        "type": device_type_plain_label(detail["device_type"], detail["is_phone"]) or "",
        # Same SpotDeviceType as "type" above, but the raw numeric enum value -
        # guarded with "is not None" rather than "or \"\"" since 0
        # (DEVICE_TYPE_UNKNOWN) is a legitimate value, not an absent one (see
        # custom.py's status_id for the identical situation).
        "type_id": detail["type_id"] if detail["type_id"] is not None else "",
        "image_url": detail["image_url"] or "",
        "carrier": detail["carrier"] or "",
        "codename": detail["codename"] or "",
        "imei": detail["imei"] or "",
        "registered_at": detail["registered_at"] or "",
        "shared_with": shared_with,
    }


def preview_values_json_for(canonic_id: str, google_name: str, device_meta: dict | None) -> str:
    """Real values the Preview panel should prefer over its hardcoded
    placeholders (see SAMPLE_VALUES in endpoint_fields.js), for whatever
    this device actually has last-reported/synced - built from the same
    build_context() forward_to_custom uses for real, so this can't drift
    from what an actual send would substitute. Fields with nothing real
    known are left out entirely (not set to "" or 0) so the client-side
    merge falls through to its own placeholder for just those - this must
    never be all-or-nothing for one device. Embedded into _device_form.html
    as JSON - "</" is escaped so a value that happens to contain "</script"
    can't end that block early (see forwarding.html's <script type=
    "application/json"> tag, which must not be HTML-escaped - its content
    is read back as raw JSON text, not markup)."""
    last = device_location_store.get_last_location(canonic_id)
    fix = None
    if last and last.get("locations"):
        candidates = device_location_store.most_recent_only(last["locations"])
        if candidates and not candidates[0].get("is_semantic"):
            fix = candidates[0]

    ctx = build_context({}, fix or {}, google_name or "", tracker_id=canonic_id, device_meta=device_meta)
    # device_name/device_alias/endpoint_alias/current_timestamp/
    # fix_timestamp are already handled correctly client-side (see
    # blockVars() in endpoint_fields.js) - leaving them out here avoids
    # this fighting that.
    skip = {"device_name", "device_alias", "endpoint_alias", "current_timestamp", "fix_timestamp"}
    values = {}
    for key, value in ctx.items():
        if key in skip:
            continue
        if key == "own_report":
            # bool(None) is False, same as a real "not this tracker's own
            # report" - only tell the two apart by whether a real fix was
            # found at all, not by own_report's own truthiness.
            if fix is not None:
                values[key] = value
            continue
        if value not in (None, ""):
            values[key] = value
    return json.dumps(values).replace("</", "<\\/")


async def rows(overrides: dict[str, dict] | None = None, saved_id: str | None = None) -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        return get_device_details(device_list)

    # Same richer per-device dicts webui/routers/devices.py fetches - not
    # because this page needs the rest of what's in them, but because both
    # pages share one underlying device_list_cache slot (see its own
    # docstring): whichever page loads first within the cache's TTL decides
    # what shape the other one gets back too, so both have to ask for the
    # same shape. Only name/canonic_id are actually used below.
    device_details = await run_blocking(device_list_cache.get_or_fetch, _fetch)
    devices = config_store.all_devices()

    result = []
    for detail in device_details:
        google_name, canonic_id = detail["name"], detail["canonic_id"]
        device_cfg = devices.get(canonic_id)
        if device_cfg is None:
            # Blank, not google_name - a device that's never actually been
            # saved must not have its alias field show up pre-filled with
            # the account name (see _device_form.html's "Device alias"
            # input comment for why that's wrong: it'd look deliberately
            # typed in, and a save with the field untouched would silently
            # pin display_name to it forever). row["name"] below still
            # falls back to google_name on its own for display purposes
            # (the heading etc.), so nothing here loses that.
            device_cfg = {"display_name": "", "endpoints": []}
        else:
            device_meta = device_meta_from_detail(detail)
            if device_cfg.get("google_name") != google_name or device_cfg.get("device_meta") != device_meta:
                # Keep the account's real name (and the rest of its device
                # metadata) in sync on local disk too (only for devices
                # actually saved already - this must never be what creates a
                # config entry for a device the user hasn't added).
                # webui/scheduler.py's poll loop never talks to Google's API
                # itself, so this is the only place {{device_name}}/
                # {{manufacturer}}/{{model}}/etc (see
                # webui/forwarders/custom.py) have anywhere to read their
                # real values from at forward time - {{device_alias}}
                # instead reads display_name, the separate local nickname
                # set below.
                device_cfg = dict(device_cfg, google_name=google_name, device_meta=device_meta)
                config_store.set_device_config(canonic_id, device_cfg)
                devices[canonic_id] = device_cfg
        save_error = None
        if overrides and canonic_id in overrides:
            device_cfg = overrides[canonic_id]["config"]
            save_error = overrides[canonic_id]["error"]
        # Runtime state (last forward status/time, last-sent position) isn't
        # config anymore - see webui/forwarders/latest_values_store.py - so
        # it never comes back from config_store above; merge it into each
        # endpoint here, display-only, so _endpoint_fields.html's "Last
        # forward: ..." line still has something to read. Safe to mutate in
        # place: device_cfg is always a fresh dict (freshly loaded, or a
        # freshly-built override above), never re-persisted after this point.
        for ep in device_cfg.get("endpoints", []):
            if isinstance(ep, dict):
                state = latest_values_store.get_endpoint_state(canonic_id, ep.get("url", ""))
                if state:
                    ep.update(state)
        # The stored display_name is a user-set alias (Google's own device name is
        # sometimes cryptic/confusing) - fall back to Google's name until one is set.
        alias = device_cfg.get("display_name") or google_name
        result.append({
            "name": alias,
            "google_name": google_name,
            "canonic_id": canonic_id,
            "config": device_cfg,
            "save_error": save_error,
            "saved": canonic_id == saved_id,
            "label_variables": device_label_variables(device_cfg.get("device_meta")),
            "preview_values_json": preview_values_json_for(canonic_id, google_name, device_cfg.get("device_meta")),
        })
    return result


async def row(canonic_id: str, overrides: dict[str, dict] | None = None, saved: bool = False) -> dict:
    """The single row a device's own save POST should come back as - saving one
    device's form must not hand the browser the whole page's worth of forms to
    swap into that one form's slot (see _device_row.html)."""
    all_rows = await rows(overrides=overrides, saved_id=canonic_id if saved else None)
    fallback = (overrides or {}).get(canonic_id, {})
    fallback_config = fallback.get("config", {"endpoints": []})
    return next(
        (r for r in all_rows if r["canonic_id"] == canonic_id),
        {
            "name": fallback_config.get("display_name", canonic_id),
            "google_name": None,
            "canonic_id": canonic_id,
            "config": fallback_config,
            "save_error": fallback.get("error"),
            "saved": saved,
            "label_variables": device_label_variables(fallback_config.get("device_meta")),
            "preview_values_json": preview_values_json_for(canonic_id, "", fallback_config.get("device_meta")),
        },
    )


def to_yaml_doc(display_name: str, endpoints: list[dict]) -> dict:
    """The YAML editor's view of a device: its alias and endpoints - no
    "google_name" (read-only, fed from Google's own device list, never
    user-configurable - see rows() above), and no per-endpoint "type" (see
    parse_endpoints_form below - always the same generic query-builder
    shape now, never a saved property, so it would never say anything a
    human didn't already know). "display_name" is the same value the
    "Device alias" field shows, kept in sync both ways (see
    webui/routers/settings.py's preview routes) - whichever view is
    actually saved from is what wins, so there's no second copy left to
    drift out of sync."""
    clean_endpoints = [{k: v for k, v in ep.items() if k != "type"} for ep in endpoints]
    return {"display_name": display_name, "endpoints": clean_endpoints}


def from_yaml_doc(yaml_text: str) -> tuple[list[dict], str, str | None]:
    """Inverse of to_yaml_doc: (endpoints, display_name, error). Shared by
    the real save route and the live "switch to form" preview (see
    webui/routers/settings.py), so both reject the same malformed input the
    same way and both pick up whatever alias is typed directly into the
    YAML text. Cron validity is deliberately not checked here - that's a
    save-time concern (see the matching check in the save route), not a
    parse-time one; a live preview should never refuse to just show you
    what you typed."""
    try:
        parsed = yaml.safe_load(yaml_text)
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            raise ValueError("must be a mapping (e.g. \"endpoints: [...]\"), not a list or a bare value")
        parsed.setdefault("endpoints", [])
        if not isinstance(parsed["endpoints"], list):
            raise ValueError("\"endpoints\" must be a list")
        for i, endpoint in enumerate(parsed["endpoints"]):
            if not isinstance(endpoint, dict):
                raise ValueError(f"endpoints[{i}] must be a mapping")
        parsed.setdefault("display_name", "")
        if not isinstance(parsed["display_name"], str):
            raise ValueError("\"display_name\" must be a string")
    except (yaml.YAMLError, ValueError) as e:
        return [], "", f"Invalid YAML: {e}"

    endpoints = [{k: v for k, v in ep.items() if k != "type"} for ep in parsed["endpoints"]]
    return endpoints, parsed["display_name"], None


def parse_kv_rows(keys: list[str], values: list[str]) -> dict:
    return {k.strip(): v for k, v in zip(keys, values) if k.strip()}


def parse_endpoints_form(form: FormData, existing_endpoints: list[dict]) -> tuple[list[dict], list[str]]:
    """(endpoints, errors) straight off a posted device form - shared by the
    real save route and the "switch to YAML view" preview (see
    webui/routers/settings.py), so switching to the YAML view while mid-edit
    reflects the same not-yet-saved values instead of whatever's still on
    disk.

    Every endpoint block's fields are namespaced "ep-{idx}-{field}", with idx
    unique per block (its saved position, or a fresh client-generated id for
    one just added via "+ Add endpoint" - see endpoint_fields.js). That,
    rather than one flat getlist() per field name shared across every
    endpoint, is what lets each block carry its own variable-length headers
    table without the rows of one block bleeding into another's."""
    ep_order = form.getlist("ep_order")

    endpoints: list[dict[str, Any]] = []
    errors = []
    for idx in ep_order:
        def field(name: str, default: str = "") -> str:
            # form.get() is typed str | UploadFile | None (FormData is also
            # used for file uploads) - every field here is a plain text
            # input, never a file, so this is always actually a str already.
            value = form.get(f"ep-{idx}-{name}", default)
            return str(value) if value else default

        def field_list(name: str) -> list[str]:
            return [str(v) for v in form.getlist(f"ep-{idx}-{name}")]

        url = field("url").strip()
        if not url:
            continue  # unfilled "+ Add endpoint" block, drop it silently

        # A preset (see the "Preset" dropdown, only ever shown on a
        # brand-new "+ Add endpoint" block - webui/forwarders/presets.py) is
        # a one-time template for starting an endpoint, never a saved
        # property of one - whatever the dropdown said (if it was even
        # posted at all) is ignored here. Endpoints don't carry a "type"
        # either - every one saved through this form is the same generic
        # query-builder shape, so a stored "type: custom" would never say
        # anything a human didn't already know.
        entry: dict[str, Any] = {
            "method": (field("method", "GET").strip().upper() or "GET"),
            "url": url,
        }

        # Each of these is genuinely optional (an endpoint with no custom
        # headers, no request body, or no alias is a normal, common config)
        # - only write the key when there's actually something in it, same
        # as the skip_if_close/skip_if_stale/alias fields below already do.
        # Every reader already treats "key missing" the same as "key present
        # but empty" (config_store.py's migrations, custom.py's headers/
        # body_type/body lookups, and _endpoint_fields.html's own field
        # defaults all already fall back with `or {}`/`or "none"`/`or ''`),
        # so this is safe to do without touching any of them.
        headers = parse_kv_rows(field_list("header_key"), field_list("header_value"))
        if headers:
            entry["headers"] = headers

        body_type = field("body_type", "none").strip() or "none"
        if body_type != "none":
            entry["body_type"] = body_type

        body = field("body")
        if body:
            entry["body"] = body

        alias = field("alias").strip()
        if alias:
            entry["alias"] = alias

        cron_expr = field("cron").strip()
        if not cron_expr or not croniter.is_valid(cron_expr):
            errors.append(f"Endpoint {len(endpoints) + 1}: \"{cron_expr}\" is not a valid cron expression")
        entry["cron"] = cron_expr or scheduler.DEFAULT_CRON

        if field("skip_if_close", "0") == "1":
            entry["skip_if_close"] = True
            try:
                entry["min_movement_m"] = float(field("min_movement_m") or policy.DEFAULT_MIN_MOVEMENT_M)
            except ValueError:
                entry["min_movement_m"] = policy.DEFAULT_MIN_MOVEMENT_M

        if field("skip_if_stale", "0") == "1":
            entry["skip_if_stale"] = True
            try:
                entry["min_update_gap_m"] = float(field("min_update_gap_m") or policy.DEFAULT_MIN_UPDATE_GAP_M)
            except ValueError:
                entry["min_update_gap_m"] = policy.DEFAULT_MIN_UPDATE_GAP_M

        # Opposite default from the two toggles above: this one is *on* by
        # default (see policy._skip_already_seen), so "off" has to be a real
        # persisted False rather than the key's absence - which is what the
        # other two toggles rely on for their own (off) default.
        if field("skip_if_already_seen", "1") != "1":
            entry["skip_if_already_seen"] = False

        # Same on-by-default convention as skip_if_already_seen above - see
        # policy._skip_not_most_recent.
        if field("only_most_recent", "1") != "1":
            entry["only_most_recent"] = False

        # Off by default, same convention as skip_if_close/skip_if_inaccurate
        # above - the per-type checkboxes stay collapsed in the settings UI
        # until this is turned on. Each status checkbox defaults to checked/
        # allowed (field absent == "1") once it's visible; only the ones the
        # owner actively unchecked get persisted. See policy._skip_blocked_status.
        if field("filter_by_status", "0") == "1":
            entry["filter_by_status"] = True
            blocked_statuses = [code for code, _ in policy.STATUS_CHOICES if field(f"status_{code}", "1") != "1"]
            if blocked_statuses:
                entry["blocked_statuses"] = blocked_statuses

        if field("skip_if_not_own_report", "0") == "1":
            entry["skip_if_not_own_report"] = True

        if field("skip_if_inaccurate", "0") == "1":
            entry["skip_if_inaccurate"] = True
            try:
                entry["max_accuracy_m"] = float(field("max_accuracy_m") or policy.DEFAULT_MAX_ACCURACY_M)
            except ValueError:
                entry["max_accuracy_m"] = policy.DEFAULT_MAX_ACCURACY_M

        # Best-effort: carry forward any leftover "variables" (from before
        # the settings UI dropped the "Custom variables" table - there's no
        # field left to re-post one, so without this a save would silently
        # erase e.g. a Traccar endpoint's device_id) if it still looks like
        # the same logical endpoint (same position, same URL). Last-forward
        # status/position isn't config at all anymore - see
        # webui/forwarders/latest_values_store.py, keyed by URL rather than
        # position, so it survives a save like this with no carry-forward
        # step needed here.
        position = len(endpoints)
        if position < len(existing_endpoints) and existing_endpoints[position].get("url") == url:
            if "variables" in existing_endpoints[position]:
                entry["variables"] = existing_endpoints[position]["variables"]

        endpoints.append(entry)

    return endpoints, errors
