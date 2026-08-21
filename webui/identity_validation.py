"""Validators for the Register form's identity fields (display name, device
type, manufacturer, model, image URL - see SpotApi/CreateBleDevice/
create_ble_device.py's register_esp32(), which these end up passed to).

Deliberately its own module rather than folded into create_ble_device.py
(that's the low-level Google-client layer, imported directly by main.py's
CLI register flow, which shouldn't have to carry UI-only policy like these
length bounds and browser-facing error strings) or into firmware_build.py
(that module is specifically about building/flashing binaries, a background
job with its own state machine - registration is an unrelated, plain
blocking call). Mirrors firmware_build.py's _validate_*(value) -> str | None
pattern.
"""

import re

from ProtoDecoders.DeviceUpdate_pb2 import SpotDeviceType

# These land in the HTTPS CreateBleDevice request, not the BLE advertisement,
# so they aren't constrained by BLE payload size the way firmware_build.py's
# 20-char device_name is - just kept short enough to stay sane in Google's UI.
_NAME_MAX_LEN = 40
_IMAGE_URL_MAX_LEN = 2048
_URL_RE = re.compile(r"^https?://\S+$")

# All SpotDeviceType names except DEVICE_TYPE_UNKNOWN - not something a user
# would ever deliberately pick when registering a new tracker.
DEVICE_TYPE_CHOICES = [name for name, _number in SpotDeviceType.items() if name != "DEVICE_TYPE_UNKNOWN"]


def _validate_name_field(value: str, label: str) -> str | None:
    # Unlike firmware_build.py's device_name (embedded in a C string literal
    # for the BLE advertisement, hence ASCII-only there), these land in a
    # protobuf string sent over HTTPS - full Unicode is fine, and the
    # historical default ("GoogleFindMyTools µC") already isn't ASCII. Still
    # block quotes/backslashes/control characters, just not on charset grounds.
    if not (1 <= len(value) <= _NAME_MAX_LEN):
        return f"{label} must be 1-{_NAME_MAX_LEN} characters"
    if any(ch in ('"', "\\") or not ch.isprintable() for ch in value):
        return f"{label} must be printable text without quotes or backslashes"
    return None


def _validate_display_name(value: str) -> str | None:
    return _validate_name_field(value, "Display name")


def _validate_manufacturer(value: str) -> str | None:
    return _validate_name_field(value, "Manufacturer name")


def _validate_model(value: str) -> str | None:
    return _validate_name_field(value, "Model name")


def _validate_device_type(value: str) -> str | None:
    if value not in DEVICE_TYPE_CHOICES:
        return "Unrecognized device type"
    return None


def _validate_image_url(value: str) -> str | None:
    if not (1 <= len(value) <= _IMAGE_URL_MAX_LEN):
        return f"Image URL must be 1-{_IMAGE_URL_MAX_LEN} characters"
    if not _URL_RE.match(value):
        return "Image URL must start with http:// or https://"
    return None
