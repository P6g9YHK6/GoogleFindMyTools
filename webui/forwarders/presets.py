"""Canned starting points for the generic query-builder endpoint config.

Picking one of these in the settings UI just pre-fills method/url/params/etc
with a sensible default for that destination - nothing about actually sending
an endpoint (see webui/forwarders/custom.py) branches on which preset, if
any, it came from. "type" on a saved endpoint is kept purely so the UI can
default back to the right preset in its dropdown; adding a new destination
here needs no new Python function, just a new entry below.
"""

PRESETS: dict[str, dict] = {
    "custom": {
        "label": "Custom",
        "hint": "A blank request - set the method, URL and whatever params, headers or body it needs.",
        "method": "GET",
        "url": "",
        "params": {},
        "headers": {},
        "body_type": "none",
        "body": "",
        "variables": {},
    },
    "traccar": {
        "label": "Traccar (OsmAnd protocol)",
        "hint": (
            "Traccar's OsmAnd protocol: a GET with the fix as query params. "
            "Add a header or rename a param if your server expects something different."
        ),
        "method": "GET",
        "url": "http://traccar.local:5055/",
        "params": {
            "id": "{{device_id}}",
            "lat": "{{latitude}}",
            "lon": "{{longitude}}",
            "timestamp": "{{fix_timestamp}}",
            "altitude": "{{altitude_m}}",
            "accuracy": "{{accuracy_m}}",
        },
        "headers": {},
        "body_type": "none",
        "body": "",
        "variables": {"device_id": ""},
    },
    "phonetrack": {
        "label": "Nextcloud PhoneTrack",
        "hint": "Nextcloud PhoneTrack's log endpoint: the device name is part of the URL, the fix is sent as query params.",
        "method": "GET",
        "url": "https://nc.local/apps/phonetrack/logGet/<token>/{{device_name}}",
        "params": {
            "lat": "{{latitude}}",
            "lon": "{{longitude}}",
            "timestamp": "{{fix_timestamp}}",
            "alt": "{{altitude_m}}",
            "acc": "{{accuracy_m}}",
        },
        "headers": {},
        "body_type": "none",
        "body": "",
        "variables": {},
    },
}

DEFAULT_PRESET_KEY = "custom"

# (variable name, human description) - shown as clickable chips in the
# Variables panel, and substituted from the location/device context at send
# time (see custom.build_context). Keep names explicit/unambiguous: e.g.
# "tracker_id" (this app's own internal id) is deliberately not called
# "device_id", since a preset's own custom variable (Traccar's device_id, the
# id *it* knows the tracker by) is a completely different value.
BUILTIN_VARIABLES: list[tuple[str, str]] = [
    ("latitude", "Latitude of the fix, decimal degrees"),
    ("longitude", "Longitude of the fix, decimal degrees"),
    ("altitude_m", "Altitude in meters, if Google reported one"),
    ("accuracy_m", "Google's radius of uncertainty for the fix, in meters"),
    ("fix_timestamp", "Unix timestamp (seconds) of when Google recorded this fix - not when it was sent"),
    ("device_name", "This device's own alias/name (same value as device_alias below)"),
    ("device_alias", "This device's own alias/name (same value as device_name above)"),
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
        "params": dict(preset["params"]),
        "headers": dict(preset["headers"]),
        "body_type": preset["body_type"],
        "body": preset["body"],
        "variables": dict(preset["variables"]),
        "cron": cron,
    }
