"""Canned starting points for the generic query-builder endpoint config.

Picking one of these in the settings UI just pre-fills method/url/headers/
body with a sensible default for that destination - nothing about actually
sending an endpoint (see webui/forwarders/custom.py) branches on which
preset, if any, it came from, and nothing about which preset was used is
ever saved (see webui/routers/settings.py's update_device_settings, which
always writes "type": "custom") - a preset is a one-time template for
starting a *new* endpoint, not an ongoing property of one. Query params
aren't a separate concept either: they're baked directly into each preset's
"url" as a literal querystring, same as a user would type one by hand.
Adding a new destination here needs no new Python function, just a new
entry below.
"""

PRESETS: dict[str, dict] = {
    "custom": {
        "label": "Custom",
        "hint": "A blank request - set the method, URL (add ?query=params directly in it if you need them) and whatever headers or body it needs.",
        "method": "GET",
        "url": "",
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "traccar": {
        "label": "Traccar (OsmAnd protocol)",
        "hint": (
            "Traccar's OsmAnd protocol: a GET with the fix as query params. "
            "Replace REPLACE_WITH_YOUR_DEVICE_ID with the id Traccar expects, and add a header if your server needs one."
        ),
        "method": "GET",
        "url": (
            "http://traccar.local:5055/?id=REPLACE_WITH_YOUR_DEVICE_ID&lat={{latitude}}&lon={{longitude}}"
            "&timestamp={{google_timestamp}}&altitude={{altitude_m}}&accuracy={{accuracy_m}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "phonetrack": {
        "label": "Nextcloud PhoneTrack",
        "hint": (
            "Nextcloud PhoneTrack's log endpoint: the device name is part of the URL, the fix is sent as query params. "
            "useragent is PhoneTrack's own per-point field (LogController.php's logGet(), unrelated to the HTTP "
            "User-Agent header) - its default is the literal string \"unknown GET logger\" when left out, so it's "
            "filled in here instead. It's a plain string field; PhoneTrack's other log endpoints (OsmAnd, GpsLogger, "
            "...) don't read a useragent param at all, so this is only ever added here. sat is PhoneTrack's "
            "satellite-count field, repurposed here to carry Google's numeric status_id (1=LAST_KNOWN, "
            "2=CROWDSOURCED, 3=AGGREGATED) since PhoneTrack has no dedicated status field of its own."
        ),
        "method": "GET",
        "url": (
            "https://nc.local/apps/phonetrack/logGet/<token>/{{device_alias}}"
            "?lat={{latitude}}&lon={{longitude}}&timestamp={{google_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
            "&useragent=gfmtForwarding{{type}}&sat={{status_id}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    # The six presets below match PhoneTrack's other protocol-specific log
    # endpoints (see its LogController.php), each meant for a particular
    # tracking app but happy to take a GET/POST from anything that speaks
    # the same param names. Same battery/speed/bearing caveat as "phonetrack"
    # above: those fields aren't in BUILTIN_VARIABLES, so they're left out.
    "phonetrack_osmand": {
        "label": "Nextcloud PhoneTrack (OsmAnd endpoint)",
        "hint": "PhoneTrack's OsmAnd-compatible log endpoint: a GET with the fix as query params.",
        "method": "GET",
        "url": (
            "https://nc.local/apps/phonetrack/log/osmand/<token>/{{device_alias}}"
            "?lat={{latitude}}&lon={{longitude}}&timestamp={{google_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "phonetrack_gpslogger": {
        "label": "Nextcloud PhoneTrack (GpsLogger endpoint)",
        "hint": "PhoneTrack's GpsLogger-compatible log endpoint: a GET with the fix as query params.",
        "method": "GET",
        "url": (
            "https://nc.local/apps/phonetrack/log/gpslogger/<token>/{{device_alias}}"
            "?lat={{latitude}}&lon={{longitude}}&timestamp={{google_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "phonetrack_locusmap": {
        "label": "Nextcloud PhoneTrack (Locus Map endpoint)",
        "hint": (
            "PhoneTrack's Locus Map-compatible log endpoint: a GET with the fix as query params. "
            "Note it's ?time=, not ?timestamp= like the other endpoints."
        ),
        "method": "GET",
        "url": (
            "https://nc.local/apps/phonetrack/log/locusmap/<token>/{{device_alias}}"
            "?lat={{latitude}}&lon={{longitude}}&time={{google_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "phonetrack_ulogger": {
        "label": "Nextcloud PhoneTrack (uLogger endpoint)",
        "hint": (
            "PhoneTrack's uLogger-compatible log endpoint: a GET with the fix as query params. "
            "Needs the literal action=addpos, and spells out accuracy/altitude instead of acc/alt."
        ),
        "method": "GET",
        "url": (
            "https://nc.local/apps/phonetrack/log/ulogger/<token>/{{device_alias}}"
            "?action=addpos&lat={{latitude}}&lon={{longitude}}&time={{google_timestamp}}"
            "&altitude={{altitude_m}}&accuracy={{accuracy_m}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "phonetrack_owntracks": {
        "label": "Nextcloud PhoneTrack (OwnTracks endpoint)",
        "hint": (
            "PhoneTrack's OwnTracks-compatible log endpoint. OwnTracks' own HTTP mode sends a JSON "
            "body instead of query params, so this one's a POST with a JSON body rather than a GET."
        ),
        "method": "POST",
        "url": "https://nc.local/apps/phonetrack/log/owntracks/<token>/{{device_alias}}",
        "headers": {},
        "body_type": "json",
        "body": (
            '{"_type": "location", "lat": {{latitude}}, "lon": {{longitude}}, '
            '"tst": {{google_timestamp}}, "acc": {{accuracy_m}}, "alt": {{altitude_m}}}'
        ),
    },
    "phonetrack_overland": {
        "label": "Nextcloud PhoneTrack (Overland endpoint)",
        "hint": (
            "PhoneTrack's Overland-compatible log endpoint: a POST with a GeoJSON-shaped body. "
            "The timestamp uses PHP's \"@<unix-seconds>\" DateTime shorthand, since that's what "
            "PhoneTrack parses it with."
        ),
        "method": "POST",
        "url": "https://nc.local/apps/phonetrack/log/overland/<token>/{{device_alias}}",
        "headers": {},
        "body_type": "json",
        "body": (
            '{"locations": [{"type": "Feature", "geometry": {"type": "Point", '
            '"coordinates": [{{longitude}}, {{latitude}}]}, "properties": {"device_id": "{{device_alias}}", '
            '"timestamp": "@{{google_timestamp}}", "horizontal_accuracy": {{accuracy_m}}, "altitude": {{altitude_m}}}}]}'
        ),
    },
}

DEFAULT_PRESET_KEY = "custom"

# (variable name, human description) - shown as clickable chips in the
# Variables panel, split into two groups there (see webui/routers/
# settings.py's _TEMPLATE_CONTEXT and settings/_endpoint_fields.html) so
# it's clear at a glance which ones come straight from Google's own fix/
# account data versus which are generated or configured locally by this
# app. Substituted from the location/device context at send time either
# way (see custom.build_context). Keep names explicit/unambiguous: e.g.
# "tracker_id" (this app's own internal id) is deliberately not called
# "device_id", to stay unambiguous next to a service's own per-device id
# (like Traccar's, which today is baked into the URL as a literal
# placeholder - see the "traccar" preset above).
BUILTIN_VARIABLES_FROM_FIX: list[tuple[str, str]] = [
    ("latitude", "Latitude of the fix, decimal degrees"),
    ("longitude", "Longitude of the fix, decimal degrees"),
    ("altitude_m", "Altitude in meters, if Google reported one"),
    ("accuracy_m", "Google's radius of uncertainty for the fix, in meters"),
    ("status", "Google's fix-quality flag: LAST_KNOWN, CROWDSOURCED, or AGGREGATED (coarse/low-accuracy)"),
    ("status_id", "Same flag as status, as Google's raw numeric id: 1=LAST_KNOWN, 2=CROWDSOURCED, 3=AGGREGATED"),
    ("is_semantic", "True if this is a named-location reading rather than a GPS fix (Google's SEMANTIC status) - a plain boolean alternative to checking status/status_id"),
    ("semantic_name", "The named place Google reported when is_semantic is true, e.g. \"Nest Mini - Living Room\" (blank otherwise)"),
    ("own_report", "True if this fix came from the tracker's own GPS rather than a nearby device's crowdsourced report"),
    ("google_timestamp", "Unix timestamp (seconds) of when Google recorded this fix - not when it was sent"),
    ("device_name", "This tracker's real name from your Google account (fixed, not editable here)"),
    ("manufacturer", "This device's manufacturer, from Google's own response (e.g. \"Chipolo\")"),
    ("model", "This device's model, from Google's own response (e.g. \"ONE Point\")"),
    ("type", "This device's category from Google's own response - Phone, Beacon, Keys, Wallet, etc."),
    ("image_url", "URL of Google's own product photo for this device"),
]

BUILTIN_VARIABLES_FROM_APP: list[tuple[str, str]] = [
    ("current_timestamp", "Unix timestamp (seconds) right now, at send time - not when Google recorded the fix"),
    ("device_alias", "This tracker's local nickname, set on the Settings page (blank if none is set)"),
    ("endpoint_alias", "This endpoint's own alias, as set above"),
    ("tracker_id", "This app's own internal id for the tracker (not a target service's device id)"),
]

# Flat combined list - still exported for anything that just needs every
# variable name/description without caring which group it's in (e.g.
# custom.build_context's docstring points here as the canonical list).
BUILTIN_VARIABLES: list[tuple[str, str]] = BUILTIN_VARIABLES_FROM_FIX + BUILTIN_VARIABLES_FROM_APP

# Mirrors custom.py's own private _NAMED_DEVICE_META_KEYS - duplicated
# rather than imported since that one's private to the send-time renderer;
# both need to draw the same "these four are always named, everything else
# becomes label_<key>" line.
NAMED_DEVICE_META_KEYS = ("manufacturer", "model", "type", "image_url")

# Hand-written descriptions for the phone-only device_meta fields, reused by
# device_label_variables() below so a chip's tooltip stays in sync with what
# build_context actually flattens it to. Used to live as unconditional
# label_* entries in BUILTIN_VARIABLES_FROM_FIX above - moved here since
# whether one's actually offered as a chip now depends on this device's own
# last-synced data (a non-phone tracker has none of these).
_LABEL_DESCRIPTIONS: dict[str, str] = {
    "carrier": "Phone-only: mobile carrier name, if Google reported one",
    "codename": "Phone-only: the manufacturer's internal codename for the device",
    "imei": "Phone-only: the device's IMEI - a real hardware identifier, handle with care",
    "registered_at": "Unix timestamp (seconds) of when this device was registered to the account",
    "shared_with": "Comma-separated emails of anyone else with access to this device (blank if just you)",
}


def device_label_variables(device_meta: dict | None) -> list[tuple[str, str]]:
    """{{label_<key>}} chips actually available for THIS device, based on
    its last-synced device_meta (see webui/routers/settings.py's
    _device_meta_from_detail) - unlike the four NAMED_DEVICE_META_KEYS
    fields above (always shown, even blank), a label_<key> chip is only
    offered when this device actually has a truthy value for it, so a
    non-phone tracker doesn't get five chips that would only ever resolve
    to an empty string. Falls back to a generic description for a
    device_meta key added later that hasn't been given a hand-written one
    in _LABEL_DESCRIPTIONS yet - same spirit as custom.py build_context's
    own "a field added later needs no matching change" comment for the
    same field."""
    meta = device_meta or {}
    return [
        (f"label_{key}", _LABEL_DESCRIPTIONS.get(key, f"This device's {key.replace('_', ' ')}, from Google's own response"))
        for key, value in meta.items()
        if key not in NAMED_DEVICE_META_KEYS and value
    ]


def blank_endpoint(cron: str) -> dict:
    """A fresh, unconfigured endpoint dict for the "+ Add endpoint" button,
    starting from the Custom preset."""
    preset = PRESETS[DEFAULT_PRESET_KEY]
    return {
        "type": DEFAULT_PRESET_KEY,
        "alias": "",
        "method": preset["method"],
        "url": preset["url"],
        "headers": dict(preset["headers"]),
        "body_type": preset["body_type"],
        "body": preset["body"],
        "cron": cron,
    }
