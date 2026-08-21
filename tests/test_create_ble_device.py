from ProtoDecoders.DeviceUpdate_pb2 import RegisterBleDeviceRequest, SpotDeviceType
from SpotApi.CreateBleDevice import create_ble_device
from SpotApi.CreateBleDevice.config import mcu_fast_pair_model_id


def _stub_backend(monkeypatch):
    captured = {}

    def fake_spot_request(api_scope, payload):
        captured["api_scope"] = api_scope
        captured["payload"] = payload
        return b""

    monkeypatch.setattr(create_ble_device, "spot_request", fake_spot_request)
    monkeypatch.setattr(create_ble_device, "get_owner_key", lambda: bytes(32))
    return captured


def test_register_esp32_defaults_match_historical_hardcoded_values(monkeypatch):
    captured = _stub_backend(monkeypatch)

    create_ble_device.register_esp32()

    request = RegisterBleDeviceRequest.FromString(captured["payload"])
    assert request.fastPairModelId == mcu_fast_pair_model_id
    assert request.description.userDefinedName == "GoogleFindMyTools µC"
    assert request.description.deviceType == SpotDeviceType.DEVICE_TYPE_BEACON
    assert request.description.deviceComponentsInformation[0].imageUrl == (
        "https://docs.espressif.com/projects/esp-idf/en/v4.3/esp32/_images/esp32-DevKitM-1-isometric.png"
    )
    assert request.manufacturerName == "GoogleFindMyTools"
    assert request.modelName == "µC"


def test_register_esp32_applies_custom_identity(monkeypatch):
    captured = _stub_backend(monkeypatch)

    create_ble_device.register_esp32(
        display_name="My Keys", device_type="DEVICE_TYPE_KEYS",
        manufacturer_name="Acme", model_name="Tag v2",
        image_url="https://example.com/tag.png",
    )

    request = RegisterBleDeviceRequest.FromString(captured["payload"])
    assert request.description.userDefinedName == "My Keys"
    assert request.description.deviceType == SpotDeviceType.DEVICE_TYPE_KEYS
    assert request.manufacturerName == "Acme"
    assert request.modelName == "Tag v2"
    assert request.description.deviceComponentsInformation[0].imageUrl == "https://example.com/tag.png"
    # fastPairModelId is never user-controllable, regardless of the other identity fields.
    assert request.fastPairModelId == mcu_fast_pair_model_id
