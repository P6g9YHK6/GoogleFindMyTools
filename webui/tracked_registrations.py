"""Correlates locally-tracked registrations (webui/firmware_store.py's
keep_track entries, from the Register form's "Keep track" checkbox) against
a live Google device list, for the Firmware page's Tracked Registrations
panel (see webui/routers/firmware.py).

Google's ListDevices response has no field carrying back the EID itself, or
a per-device registration timestamp, for Spot/BLE devices (see
ProtoDecoders/decoder.py's get_device_details - registered_at is only ever
populated in the is_phone branch). So there's no exact key to join on -
matching instead compares the identity actually submitted at registration
time (display name/manufacturer/model, plus device type when it's usable)
against what Google echoes back per device. This is reliable whenever each
registration used a distinct identity, the common case, especially with the
identity presets (see webui/registration_presets.py) - but two registrations
left at identical defaults are genuinely indistinguishable from Google's
response alone, see resolve_tracked_status's "ambiguous" status below.
"""

from ProtoDecoders import DeviceUpdate_pb2


def _device_type_id(device_type: str) -> int | None:
    """entry["device_type"] is stored as the enum name (e.g.
    "DEVICE_TYPE_KEYS" - see webui/identity_validation.py), while
    webui.routers.devices.get_devices() hands back the raw numeric type_id
    Google reports - translate so the two can be compared. None for an
    unset/unrecognized name, meaning this check is simply skipped for that
    entry rather than treated as a mismatch."""
    if not device_type:
        return None
    try:
        return DeviceUpdate_pb2.SpotDeviceType.Value(device_type)
    except ValueError:
        return None


def _matches(entry: dict, device: dict) -> bool:
    if device.get("is_phone"):
        return False
    if device.get("name") != entry.get("display_name"):
        return False
    if device.get("manufacturer") != entry.get("manufacturer_name"):
        return False
    if device.get("model") != entry.get("model_name"):
        return False
    entry_type_id = _device_type_id(entry.get("device_type", ""))
    if entry_type_id is not None and device.get("type_id") not in (None, entry_type_id):
        return False
    return True


def resolve_tracked_status(entries: list[dict], devices: list[dict]) -> list[dict]:
    """entries: firmware_store entries with keep_track set (already filtered
    by the caller - see webui/routers/firmware.py's firmware_tracked()).
    devices: the live list from webui.routers.devices.get_devices().

    Returns each entry augmented with a "status":
    - "not_found": no account device currently matches this identity -
      possibly deleted from the account, or never actually registered.
    - "found": exactly one match - "device" holds it.
    - "ambiguous": more than one account device shares this identity -
      Google's response can't tell them apart, so "devices" holds all of
      them rather than guessing which one this registration became.
    """
    results = []
    for entry in entries:
        matches = [device for device in devices if _matches(entry, device)]
        if not matches:
            status, extra = "not_found", {}
        elif len(matches) == 1:
            status, extra = "found", {"device": matches[0]}
        else:
            status, extra = "ambiguous", {"devices": matches}
        results.append({**entry, "status": status, **extra})
    return results
