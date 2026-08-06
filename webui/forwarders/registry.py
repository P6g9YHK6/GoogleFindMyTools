"""Single place that knows about every forwarding destination type.

Adding a new destination (beyond Traccar/PhoneTrack) means writing its
forward_to_X(...) function next to traccar.py/phonetrack.py, then adding one
ForwarderType entry below - nothing else needs to change. The settings form
(webui/templates/settings/_endpoint_fields.html), the router's form parsing
(webui/routers/settings.py) and the scheduler's dispatch/logging
(webui/scheduler.py) all read this registry instead of hardcoding per-type
branches.
"""

from dataclasses import dataclass, field
from typing import Callable

from webui.forwarders.phonetrack import forward_to_phonetrack
from webui.forwarders.traccar import forward_to_traccar


@dataclass(frozen=True)
class FieldSpec:
    name: str  # sub-key in the endpoint's config dict, and form field suffix
    label: str
    placeholder: str = ""
    wide: bool = False  # long values (URLs) get the full-width .url-input style


@dataclass(frozen=True)
class ForwarderType:
    key: str  # endpoint["type"] value, and form field prefix
    label: str
    fields: list[FieldSpec] = field(default_factory=list)
    # (this type's config sub-dict, location) -> True if a location was actually sent
    forward: Callable[[dict, dict], bool] = None
    # this type's config sub-dict -> short human-readable destination summary, for
    # the endpoint list and the forwarding log
    target_label: Callable[[dict], str] = None

    def form_field_name(self, field_name: str) -> str:
        return f"{self.key}_{field_name}"


def _traccar_forward(cfg: dict, location: dict) -> bool:
    return forward_to_traccar(cfg.get("url", ""), cfg.get("device_id", ""), location)


def _traccar_target(cfg: dict) -> str:
    return f"{cfg.get('url', '')} (device {cfg.get('device_id', '')})"


def _phonetrack_forward(cfg: dict, location: dict) -> bool:
    return forward_to_phonetrack(cfg.get("base_url", ""), cfg.get("device_name", ""), location)


def _phonetrack_target(cfg: dict) -> str:
    return f"{cfg.get('base_url', '')} ({cfg.get('device_name', '')})"


FORWARDER_TYPES: dict[str, ForwarderType] = {
    ft.key: ft
    for ft in [
        ForwarderType(
            key="traccar",
            label="Traccar (OsmAnd protocol)",
            fields=[
                FieldSpec("url", "Server URL", placeholder="http://traccar.local:5055", wide=True),
                FieldSpec("device_id", "Device ID"),
            ],
            forward=_traccar_forward,
            target_label=_traccar_target,
        ),
        ForwarderType(
            key="phonetrack",
            label="Nextcloud PhoneTrack",
            fields=[
                FieldSpec(
                    "base_url", "HTTP-GET base URL (from the PhoneTrack session)",
                    placeholder="https://nc.local/apps/phonetrack/logGet/<token>", wide=True,
                ),
                FieldSpec("device_name", "Device name"),
            ],
            forward=_phonetrack_forward,
            target_label=_phonetrack_target,
        ),
    ]
}


def blank_endpoint(cron: str) -> dict:
    """A fresh, unconfigured endpoint dict for the "+ Add endpoint" button -
    one empty config sub-dict per registered type, so the template can switch
    between them without any of the fields ever being undefined."""
    return {
        "type": next(iter(FORWARDER_TYPES)),
        **{key: {} for key in FORWARDER_TYPES},
        "cron": cron,
    }
