"""The one forwarder every endpoint sends through, generic HTTP with
{{variable}} templating - Traccar and Nextcloud PhoneTrack are just presets
that pre-fill this (see presets.py), not separate code paths."""

import logging
import re
import time

import httpx

logger = logging.getLogger("webui.forwarders.custom")

TIMEOUT_S = 10
# A destination's error page/body can be arbitrarily large (an HTML error
# page from a misconfigured reverse proxy, say) - bounded here so one bad
# response can't blow up the forwarding log file (see log_store.py's own
# FORWARD_LOG_MAX_ENTRIES cap for the same concern applied to entry count).
MAX_LOGGED_RESPONSE_CHARS = 2000
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")


def _render(template: str, ctx: dict) -> str:
    """Substitutes {{name}} tokens from ctx. A token with no matching value
    (e.g. a typo) is left in place rather than silently dropped, so a bad
    template is obvious in the actual request/response instead of quietly
    sending garbage - see the "Preview" panel in the settings UI, which
    flags the same unresolved tokens before you ever save.

    A token that *does* resolve, but to an empty string (e.g. {{device_alias}}
    on a device with no alias set) is a different, quieter kind of mistake -
    nothing looks broken in the request, it just silently sends less than
    intended. That's easy to miss without a log line, so it gets a warning
    even though (unlike an unresolved token) it's left substituted rather
    than blocked."""
    if not template:
        return ""

    def repl(m: re.Match) -> str:
        key = m.group(1)
        value = ctx.get(key)
        if value is None:
            return m.group(0)
        rendered = str(value)
        if rendered == "":
            logger.warning("Template variable {{%s}} resolved to an empty value", key)
        return rendered

    return _TOKEN_RE.sub(repl, template)


# The device_meta fields with a dedicated, hand-picked template name - see
# the device_meta paragraph in build_context's docstring below. Anything
# else present in device_meta gets a generic "label_<key>" name instead,
# so a field added to get_device_details later needs no change here to
# become available as a variable.
_NAMED_DEVICE_META_KEYS = ("manufacturer", "model", "type", "image_url")


def build_context(
    endpoint_cfg: dict, location: dict, device_name: str, device_alias: str | None = None,
    tracker_id: str = "", device_meta: dict | None = None,
) -> dict:
    """Every {{variable}} available to this endpoint's templates - the
    location fix, this endpoint's own alias, and (for endpoints saved before
    the settings UI dropped the "Custom variables" table) its own leftover
    custom variables, e.g. a Traccar endpoint's device_id.

    device_name is this tracker's real name straight from the Google
    account; device_alias is the (optional) local nickname set on the
    Settings page, falling back to device_name when no caller passes one
    explicitly - callers that only ever had one name to give (older code,
    tests) still get sensible identical values for both, same as before
    device_alias existed as its own concept. Neither is overridable per
    endpoint - see webui/scheduler.py for where the two are actually told
    apart (device_cfg's "google_name" vs "display_name").

    tracker_id is this app's own internal id for the tracker (its
    canonic_id) - see BUILTIN_VARIABLES_FROM_APP in presets.py, which has
    offered it as a chip since that variable existed but, until now, this
    function never actually set it.

    device_meta is the rest of what ProtoDecoders.decoder.get_device_details
    knows about the device (manufacturer, model, its category, a product
    photo URL, and phone-only hardware/sharing info), synced into
    forwarding.yaml by webui/routers/settings.py's _rows() the same way
    google_name already is - see that function's own comment for why this
    can't just be fetched fresh here instead. _NAMED_DEVICE_META_KEYS above
    get their own {{name}}; everything else in the dict becomes
    {{label_<key>}}, generically - see the loop below."""
    ctx = {
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "altitude_m": location.get("altitude"),
        "accuracy_m": location.get("accuracy"),
        # status is Google's own fix-quality flag (see Common.proto's Status
        # enum) as the string name decrypt_locations.py already names it -
        # LAST_KNOWN/CROWDSOURCED/AGGREGATED for a real fix, or SEMANTIC for
        # a named-location reading with a configured mapping (see
        # webui/forwarders/semantic_map.py - forward_to_custom still bails
        # out on any semantic reading with no mapped coordinates). own_report
        # tells apart this tracker's own GPS fix from one crowdsourced by a
        # nearby device.
        "status": location.get("status") or "",
        # status_id is the same flag as status above, but as the raw numeric
        # enum value (see Common.proto's Status: LAST_KNOWN=1, CROWDSOURCED=2,
        # AGGREGATED=3) for endpoints that want to key off it without string
        # matching.
        "status_id": location.get("status_id") if location.get("status_id") is not None else "",
        "own_report": bool(location.get("is_own_report")),
        # google_timestamp: when Google recorded this fix. current_timestamp:
        # right now, at send time - always fresh even when Google keeps
        # re-serving the same cached fix (see skip_if_stale in policy.py,
        # which is exactly the case that makes the two worth telling apart).
        "google_timestamp": location.get("time"),
        "current_timestamp": int(time.time()),
        # fix_timestamp was google_timestamp's old name - not offered as a
        # chip anymore (see BUILTIN_VARIABLES in presets.py) and no preset
        # writes it, but silently kept resolving here so an endpoint saved
        # before the rename doesn't go quietly broken (see _render()'s
        # empty-value warning above for why "quietly broken" specifically
        # is worth avoiding).
        "fix_timestamp": location.get("time"),
        "device_name": device_name or "",
        "device_alias": (device_alias if device_alias is not None else device_name) or "",
        "endpoint_alias": endpoint_cfg.get("alias") or "",
        "tracker_id": tracker_id or "",
    }
    meta = device_meta or {}
    for key in _NAMED_DEVICE_META_KEYS:
        ctx[key] = meta.get(key) or ""
    for key, value in meta.items():
        if key not in _NAMED_DEVICE_META_KEYS:
            ctx[f"label_{key}"] = value if value is not None else ""
    # No UI writes "variables" anymore (see webui/forwarders/presets.py's
    # module docstring) - this merge only still matters for an endpoint
    # saved before that change, so its {{device_id}}-style tokens keep
    # resolving exactly as before with nothing left to edit them.
    ctx.update(endpoint_cfg.get("variables") or {})
    return ctx


def forward_to_custom(
    endpoint_cfg: dict, location: dict, device_name: str = "", device_alias: str | None = None,
    tracker_id: str = "", device_meta: dict | None = None, response_out: dict | None = None,
) -> bool:
    """response_out, if given, is filled in with whatever the destination
    actually answered ("status_code"/"body", body truncated to
    MAX_LOGGED_RESPONSE_CHARS) - the return value only ever says whether the
    request was *sent* (raise_for_status() turns a non-2xx into the caller's
    "error: ..." status), which isn't enough to debug a destination that
    itself answers 200 while silently rejecting the point (see the Forwarding
    Log's "Response" column, webui/forwarders/log_store.py). Left None by
    every caller that doesn't care (most existing tests included) - the
    request/response handling itself is unchanged either way."""
    if location.get("latitude") is None:
        # Covers both a real fix that somehow has no coordinates and a
        # SEMANTIC reading with no configured mapping (see
        # webui/forwarders/semantic_map.py) - either way there's nothing to
        # send. A semantic reading that *does* have a mapped latitude falls
        # through and sends normally, is_semantic and all.
        return False

    url_template = (endpoint_cfg.get("url") or "").strip()
    if not url_template:
        return False

    ctx = build_context(endpoint_cfg, location, device_name, device_alias, tracker_id, device_meta)
    # Query params live in the URL itself now (a literal "?key=value"), not
    # a separate table - _render() already substitutes {{var}} tokens
    # anywhere in this string, querystring included, so passing the
    # rendered URL straight to httpx and letting it parse its own query
    # string is all that's needed. (This used to also pass a `params=`
    # kwarg, which httpx treats as a full replacement of the URL's query
    # string rather than a merge - even an empty dict wiped it - so a
    # literal "?..." typed into the URL used to be silently discarded.)
    url = _render(url_template, ctx)
    headers = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("headers") or {}).items()}
    method = (endpoint_cfg.get("method") or "GET").strip().upper() or "GET"

    body_type = endpoint_cfg.get("body_type") or "none"
    body_raw = endpoint_cfg.get("body") or ""
    content: str | None = None
    data: dict[str, str] | None = None

    if body_type == "json" and body_raw.strip():
        content = _render(body_raw, ctx)
        headers.setdefault("Content-Type", "application/json")
    elif body_type == "raw" and body_raw.strip():
        content = _render(body_raw, ctx)
    elif body_type == "form" and body_raw.strip():
        # One "key=value" pair per line, same {{variable}} substitution as
        # everything else - kept as plain text rather than a key/value
        # table, since GET/POST-style key/value needs are already covered
        # by putting them straight in the URL's own querystring.
        data = {}
        for line in body_raw.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip()] = _render(v.strip(), ctx)

    response = httpx.request(method, url, headers=headers, timeout=TIMEOUT_S, content=content, data=data)
    if response_out is not None:
        # Captured before raise_for_status() below - a non-2xx's body is
        # exactly what's most worth seeing in the log, not just its status.
        body = response.text
        if len(body) > MAX_LOGGED_RESPONSE_CHARS:
            body = body[:MAX_LOGGED_RESPONSE_CHARS] + "... (truncated)"
        response_out["status_code"] = response.status_code
        response_out["body"] = body
    response.raise_for_status()
    return True


def preview_request(
    endpoint_cfg: dict, location: dict, device_name: str = "", device_alias: str | None = None,
    tracker_id: str = "", device_meta: dict | None = None,
) -> dict:
    """Non-sending dry-run of the above, for the "Send now" confirmation /
    debugging - not currently wired into a route, kept alongside
    forward_to_custom so the two can't drift apart on how templating works."""
    ctx = build_context(endpoint_cfg, location, device_name, device_alias, tracker_id, device_meta)
    url = _render((endpoint_cfg.get("url") or "").strip(), ctx)
    headers = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("headers") or {}).items()}
    body_type = endpoint_cfg.get("body_type") or "none"
    body = _render(endpoint_cfg.get("body") or "", ctx) if body_type != "none" else ""
    return {
        "method": (endpoint_cfg.get("method") or "GET").strip().upper() or "GET",
        "url": url, "headers": headers, "body_type": body_type, "body": body,
    }


__all__ = ["forward_to_custom", "build_context", "preview_request", "TIMEOUT_S"]
