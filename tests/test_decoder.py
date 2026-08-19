from ProtoDecoders import DeviceUpdate_pb2
from ProtoDecoders.decoder import get_canonic_ids, get_device_details, get_last_seen


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


def test_get_device_details_extracts_phone_hardware_info():
    device = _phone_device("phone-1", "My Phone", last_seen=1786118431)
    device.hardwareInfo.manufacturer = "Xiaomi"
    device.hardwareInfo.model = "M2007J17G"
    device.hardwareInfo.carrier = "No carrier"
    device.hardwareInfo.codename = "gauguin"
    device.hardwareInfo.imei = "864025058184054"
    device.hardwareInfo.registrationTime.seconds = 1785964218
    device.imageInformation.imageUrl = "https://example.com/phone.png"

    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    [detail] = get_device_details(device_list)
    assert detail["is_phone"] is True
    assert detail["manufacturer"] == "Xiaomi"
    assert detail["model"] == "M2007J17G"
    assert detail["carrier"] == "No carrier"
    assert detail["codename"] == "gauguin"
    assert detail["imei"] == "864025058184054"
    assert detail["registered_at"] == 1785964218
    assert detail["image_url"] == "https://example.com/phone.png"
    assert detail["device_type"] is None  # SpotDeviceType doesn't apply to phones
    assert detail["type_id"] is None


def test_get_device_details_extracts_spot_tag_registration_info():
    device = _tag_device("tag-1", "My Tag")
    reg = device.information.deviceRegistration
    reg.manufacturer = "Chipolo"
    reg.model = "Chipolo ONE Point"
    reg.deviceTypeInformation.deviceType = DeviceUpdate_pb2.DEVICE_TYPE_KEYS
    device.imageInformation.imageUrl = "https://example.com/tag.png"

    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    [detail] = get_device_details(device_list)
    assert detail["is_phone"] is False
    assert detail["manufacturer"] == "Chipolo"
    assert detail["model"] == "Chipolo ONE Point"
    assert detail["device_type"] == "DEVICE_TYPE_KEYS"
    assert detail["type_id"] == DeviceUpdate_pb2.DEVICE_TYPE_KEYS
    assert detail["image_url"] == "https://example.com/tag.png"
    # Phone-only fields must not leak onto a tag
    assert detail["carrier"] is None
    assert detail["imei"] is None


def test_get_device_details_survives_an_unrecognized_device_type():
    # Google occasionally rolls out new SpotDeviceType values before this
    # enum is updated to match (see decoder.py's comment) - one unrecognized
    # device shouldn't take down the whole device list.
    device = _tag_device("tag-1", "Mystery Tag")
    device.information.deviceRegistration.deviceTypeInformation.deviceType = 99

    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    [detail] = get_device_details(device_list)
    assert detail["device_type"] == "DEVICE_TYPE_UNKNOWN_99"
    assert detail["type_id"] == 99


def test_get_device_details_type_id_zero_is_a_real_value_not_a_missing_one():
    # DEVICE_TYPE_UNKNOWN is enum value 0, a legitimate reading (an
    # untyped/unrecognized Spot device) rather than "no type at all" - the
    # phone case above is the actual "no type at all" (type_id is None
    # there, never 0).
    device = _tag_device("tag-1", "Untyped Tag")
    device.information.deviceRegistration.deviceTypeInformation.deviceType = DeviceUpdate_pb2.DEVICE_TYPE_UNKNOWN

    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    [detail] = get_device_details(device_list)
    assert detail["device_type"] == "DEVICE_TYPE_UNKNOWN"
    assert detail["type_id"] == 0


def test_get_device_details_extracts_access_information():
    device = _tag_device("tag-1", "My Tag")
    device.information.accessInformation.add(
        email="me@example.com", hasAccess=True, isOwner=True, thisAccount=True,
    )
    device.information.accessInformation.add(
        email="family@example.com", hasAccess=True, isOwner=False, thisAccount=False,
    )

    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    [detail] = get_device_details(device_list)
    assert detail["access"] == [
        {"email": "me@example.com", "has_access": True, "is_owner": True, "this_account": True},
        {"email": "family@example.com", "has_access": True, "is_owner": False, "this_account": False},
    ]


def test_get_device_details_normalizes_unset_scalar_fields_to_none():
    # proto3 can't tell "unset" apart from "" on a plain (non-optional)
    # string field - hardwareInfo.manufacturer etc. are untouched here, so
    # they're "" at the protobuf level and must come back as None, not "".
    device = _phone_device("phone-1", "My Phone", last_seen=None)
    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    [detail] = get_device_details(device_list)
    assert detail["manufacturer"] is None
    assert detail["model"] is None
    assert detail["carrier"] is None
    assert detail["codename"] is None
    assert detail["imei"] is None
    assert detail["image_url"] is None
    assert detail["access"] == []


def test_get_canonic_ids_ignores_the_richer_fields_get_device_details_adds():
    device = _tag_device("tag-1", "My Tag")
    device.information.deviceRegistration.manufacturer = "Chipolo"
    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.deviceMetadata.append(device)

    assert get_canonic_ids(device_list) == [("My Tag", "tag-1", None)]
