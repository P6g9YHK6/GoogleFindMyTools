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
            "&timestamp={{fix_timestamp}}&altitude={{altitude_m}}&accuracy={{accuracy_m}}"
        ),
        "headers": {},
        "body_type": "none",
        "body": "",
    },
    "phonetrack": {
        "label": "Nextcloud PhoneTrack",
        "hint": "Nextcloud PhoneTrack's log endpoint: the device name is part of the URL, the fix is sent as query params.",
        "method": "GET",
        "url": (
            "https://nc.local/apps/phonetrack/logGet/<token>/{{device_alias}}"
            "?lat={{latitude}}&lon={{longitude}}&timestamp={{fix_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
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
            "?lat={{latitude}}&lon={{longitude}}&timestamp={{fix_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
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
            "?lat={{latitude}}&lon={{longitude}}&timestamp={{fix_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
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
            "?lat={{latitude}}&lon={{longitude}}&time={{fix_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
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
            "?action=addpos&lat={{latitude}}&lon={{longitude}}&time={{fix_timestamp}}"
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
            '"tst": {{fix_timestamp}}, "acc": {{accuracy_m}}, "alt": {{altitude_m}}}'
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
            '"timestamp": "@{{fix_timestamp}}", "horizontal_accuracy": {{accuracy_m}}, "altitude": {{altitude_m}}}}]}'
        ),
    },
}

DEFAULT_PRESET_KEY = "custom"

# (variable name, human description) - shown as clickable chips in the
# Variables panel, and substituted from the location/device context at send
# time (see custom.build_context). Keep names explicit/unambiguous: e.g.
# "tracker_id" (this app's own internal id) is deliberately not called
# "device_id", to stay unambiguous next to a service's own per-device id
# (like Traccar's, which today is baked into the URL as a literal
# placeholder - see the "traccar" preset above).
BUILTIN_VARIABLES: list[tuple[str, str]] = [
    ("latitude", "Latitude of the fix, decimal degrees"),
    ("longitude", "Longitude of the fix, decimal degrees"),
    ("altitude_m", "Altitude in meters, if Google reported one"),
    ("accuracy_m", "Google's radius of uncertainty for the fix, in meters"),
    ("fix_timestamp", "Unix timestamp (seconds) of when Google recorded this fix - not when it was sent"),
    ("device_name", "This tracker's real name from your Google account (fixed, not editable here)"),
    ("device_alias", "This tracker's local nickname, set on the Settings page (falls back to device_name until you set one)"),
    ("endpoint_alias", "This endpoint's own alias, as set above"),
    ("tracker_id", "This app's own internal id for the tracker (not a target service's device id)"),
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
