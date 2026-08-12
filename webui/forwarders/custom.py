"""The one forwarder every endpoint sends through, generic HTTP with
{{variable}} templating - Traccar and Nextcloud PhoneTrack are just presets
that pre-fill this (see presets.py), not separate code paths."""

import logging
import re
import time

import httpx

logger = logging.getLogger("webui.forwarders.custom")

TIMEOUT_S = 10
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


def build_context(
    endpoint_cfg: dict, location: dict, device_name: str, device_alias: str | None = None,
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
    apart (device_cfg's "google_name" vs "display_name")."""
    ctx = {
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "altitude_m": location.get("altitude"),
        "accuracy_m": location.get("accuracy"),
        # google_timestamp: when Google recorded this fix. current_timestamp:
        # right now, at send time - always fresh even when Google keeps
        # re-serving the same cached fix (see skip_if_stale in policy.py,
        # which is exactly the case that makes the two worth telling apart).
        "google_timestamp": location.get("time"),
        "current_timestamp": int(time.time()),
        "device_name": device_name or "",
        "device_alias": (device_alias if device_alias is not None else device_name) or "",
        "endpoint_alias": endpoint_cfg.get("alias") or "",
    }
    # No UI writes "variables" anymore (see webui/forwarders/presets.py's
    # module docstring) - this merge only still matters for an endpoint
    # saved before that change, so its {{device_id}}-style tokens keep
    # resolving exactly as before with nothing left to edit them.
    ctx.update(endpoint_cfg.get("variables") or {})
    return ctx


def forward_to_custom(
    endpoint_cfg: dict, location: dict, device_name: str = "", device_alias: str | None = None,
) -> bool:
    if location.get("is_semantic") or location.get("latitude") is None:
        return False

    url_template = (endpoint_cfg.get("url") or "").strip()
    if not url_template:
        return False

    ctx = build_context(endpoint_cfg, location, device_name, device_alias)
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
    request_kwargs = {"headers": headers, "timeout": TIMEOUT_S}

    if body_type == "json" and body_raw.strip():
        request_kwargs["content"] = _render(body_raw, ctx)
        headers.setdefault("Content-Type", "application/json")
    elif body_type == "raw" and body_raw.strip():
        request_kwargs["content"] = _render(body_raw, ctx)
    elif body_type == "form" and body_raw.strip():
        # One "key=value" pair per line, same {{variable}} substitution as
        # everything else - kept as plain text rather than a key/value
        # table, since GET/POST-style key/value needs are already covered
        # by putting them straight in the URL's own querystring.
        form_data = {}
        for line in body_raw.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                form_data[k.strip()] = _render(v.strip(), ctx)
        request_kwargs["data"] = form_data

    response = httpx.request(method, url, **request_kwargs)
    response.raise_for_status()
    return True


def preview_request(
    endpoint_cfg: dict, location: dict, device_name: str = "", device_alias: str | None = None,
) -> dict:
    """Non-sending dry-run of the above, for the "Send now" confirmation /
    debugging - not currently wired into a route, kept alongside
    forward_to_custom so the two can't drift apart on how templating works."""
    ctx = build_context(endpoint_cfg, location, device_name, device_alias)
    url = _render((endpoint_cfg.get("url") or "").strip(), ctx)
    headers = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("headers") or {}).items()}
    body_type = endpoint_cfg.get("body_type") or "none"
    body = _render(endpoint_cfg.get("body") or "", ctx) if body_type != "none" else ""
    return {
        "method": (endpoint_cfg.get("method") or "GET").strip().upper() or "GET",
        "url": url, "headers": headers, "body_type": body_type, "body": body,
    }


__all__ = ["forward_to_custom", "build_context", "preview_request", "TIMEOUT_S"]
