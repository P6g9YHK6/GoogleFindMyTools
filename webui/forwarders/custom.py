"""The one forwarder every endpoint sends through, generic HTTP with
{{variable}} templating - Traccar and Nextcloud PhoneTrack are just presets
that pre-fill this (see presets.py), not separate code paths."""

import re

import httpx

TIMEOUT_S = 10
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")


def _render(template: str, ctx: dict) -> str:
    """Substitutes {{name}} tokens from ctx. A token with no matching value
    (e.g. a typo) is left in place rather than silently dropped, so a bad
    template is obvious in the actual request/response instead of quietly
    sending garbage - see the "Preview" panel in the settings UI, which
    flags the same unresolved tokens before you ever save."""
    if not template:
        return ""

    def repl(m: re.Match) -> str:
        key = m.group(1)
        value = ctx.get(key)
        return str(value) if value is not None else m.group(0)

    return _TOKEN_RE.sub(repl, template)


def build_context(endpoint_cfg: dict, location: dict, device_display_name: str) -> dict:
    """Every {{variable}} available to this endpoint's templates - the
    location fix, this endpoint's own alias, and its own custom variables
    (Traccar's device_id, a bearer token, ...).

    device_name and device_alias are both just the device's own alias/name -
    two names for the same value (not overridable per endpoint), kept as
    two tokens so existing templates written against either name work."""
    ctx = {
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "altitude_m": location.get("altitude"),
        "accuracy_m": location.get("accuracy"),
        "fix_timestamp": location.get("time"),
        "device_name": device_display_name or "",
        "device_alias": device_display_name or "",
        "endpoint_alias": endpoint_cfg.get("alias") or "",
    }
    ctx.update(endpoint_cfg.get("variables") or {})
    return ctx


def forward_to_custom(endpoint_cfg: dict, location: dict, device_display_name: str = "") -> bool:
    if location.get("is_semantic") or location.get("latitude") is None:
        return False

    url_template = (endpoint_cfg.get("url") or "").strip()
    if not url_template:
        return False

    ctx = build_context(endpoint_cfg, location, device_display_name)
    url = _render(url_template, ctx)
    params = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("params") or {}).items()}
    headers = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("headers") or {}).items()}
    method = (endpoint_cfg.get("method") or "GET").strip().upper() or "GET"

    body_type = endpoint_cfg.get("body_type") or "none"
    body_raw = endpoint_cfg.get("body") or ""
    request_kwargs = {"params": params, "headers": headers, "timeout": TIMEOUT_S}

    if body_type == "json" and body_raw.strip():
        request_kwargs["content"] = _render(body_raw, ctx)
        headers.setdefault("Content-Type", "application/json")
    elif body_type == "raw" and body_raw.strip():
        request_kwargs["content"] = _render(body_raw, ctx)
    elif body_type == "form" and body_raw.strip():
        # One "key=value" pair per line, same {{variable}} substitution as
        # everything else - kept as plain text rather than another key/value
        # table, since the params table above already covers most GET/POST
        # form-style needs.
        form_data = {}
        for line in body_raw.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                form_data[k.strip()] = _render(v.strip(), ctx)
        request_kwargs["data"] = form_data

    response = httpx.request(method, url, **request_kwargs)
    response.raise_for_status()
    return True


def preview_request(endpoint_cfg: dict, location: dict, device_display_name: str = "") -> dict:
    """Non-sending dry-run of the above, for the "Send now" confirmation /
    debugging - not currently wired into a route, kept alongside
    forward_to_custom so the two can't drift apart on how templating works."""
    ctx = build_context(endpoint_cfg, location, device_display_name)
    url = _render((endpoint_cfg.get("url") or "").strip(), ctx)
    params = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("params") or {}).items()}
    headers = {k: _render(v, ctx) for k, v in (endpoint_cfg.get("headers") or {}).items()}
    body_type = endpoint_cfg.get("body_type") or "none"
    body = _render(endpoint_cfg.get("body") or "", ctx) if body_type != "none" else ""
    return {
        "method": (endpoint_cfg.get("method") or "GET").strip().upper() or "GET",
        "url": url, "params": params, "headers": headers, "body_type": body_type, "body": body,
    }


__all__ = ["forward_to_custom", "build_context", "preview_request", "TIMEOUT_S"]
