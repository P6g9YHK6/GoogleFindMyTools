from ProtoDecoders import DeviceUpdate_pb2
from ProtoDecoders.decoder import get_canonic_ids, get_last_seen


def _phone_device(canonic_id: str, name: str, last_seen: int | None) -> DeviceUpdate_pb2.DeviceMetadata:
    device = DeviceUpdate_pb2.DeviceMetadata()
    device.identifierInformation.type = DeviceUpdate_pb2.IDENTIFIER_ANDROID
    device.identifierInformation.phoneInformation.canonicIds.canonicId.add(id=canonic_id)
    device.userDefinedDeviceName = name
    if last_seen is not None:
        device.hardwareInfo.lastSeenTime.seconds = last_seen
    return device


def _tag_device(canonic_id: str, name: str, recent_location_time: int | None = None) -> DeviceUpdate_pb2.DeviceMetadata:
    device = DeviceUpdate_pb2.DeviceMetadata()
    device.identifierInformation.type = DeviceUpdate_pb2.IDENTIFIER_SPOT
    device.identifierInformation.canonicIds.canonicId.add(id=canonic_id)
    device.userDefinedDeviceName = name
    if recent_location_time is not None:
        reports = device.information.locationInformation.reports.recentLocationAndNetworkLocations
        reports.recentLocationTimestamp.seconds = recent_location_time
    return device


def test_get_last_seen_returns_none_when_nothing_is_present():
    device = _tag_device("tag-1", "My Tag")
    assert get_last_seen(device) is None


def test_get_last_seen_returns_none_when_hardware_info_present_but_unset():
    device = DeviceUpdate_pb2.DeviceMetadata()
    device.hardwareInfo.model = "some-model"  # touches hardwareInfo without setting lastSeenTime
    assert get_last_seen(device) is None


def test_get_last_seen_uses_hardware_info_time_for_phones():
    device = _phone_device("phone-1", "My Phone", last_seen=1786118431)
    assert get_last_seen(device) == 1786118431


def test_get_last_seen_falls_back_to_recent_location_time_for_tags():
    # Spot/BLE tags have no hardware-status concept - the real Find My
    # Device web app shows "last seen" for them too, sourced from the most
    # recent location report's own timestamp instead.
    device = _tag_device("tag-1", "My Tag", recent_location_time=1786118431)
    assert get_last_seen(device) == 1786118431


def test_get_last_seen_prefers_hardware_info_time_when_both_are_present():
    device = _phone_device("phone-1", "My Phone", last_seen=1786118431)
    reports = device.information.locationInformation.reports.recentLocationAndNetworkLocations
    reports.recentLocationTimestamp.seconds = 1  # much older - should be ignored
    assert get_last_seen(device) == 1786118431


def test_get_canonic_ids_includes_last_seen_per_row():
    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(_phone_device("phone-1", "My Phone", last_seen=1786118431))
    device_list.deviceMetadata.append(_tag_device("tag-1", "My Tag", recent_location_time=1786118000))

    result = get_canonic_ids(device_list)
    assert result == [
        ("My Phone", "phone-1", 1786118431),
        ("My Tag", "tag-1", 1786118000),
    ]
