import pytest

from FMDNCrypto.eid_generator import generate_eid
from KeyBackup.cloud_key_decryptor import decrypt_eik
from ProtoDecoders.DeviceUpdate_pb2 import RegisterBleDeviceRequest, SpotDeviceType
from SpotApi.CreateBleDevice import create_ble_device
from SpotApi.CreateBleDevice.config import mcu_fast_pair_model_id
from SpotApi.CreateBleDevice.util import flip_bits


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


def test_register_esp32_default_flips_identity_key_bits(monkeypatch):
    captured = _stub_backend(monkeypatch)
    owner_key = bytes(32)

    result = create_ble_device.register_esp32()

    request = RegisterBleDeviceRequest.FromString(captured["payload"])
    encrypted_identity_key = request.e2eePublicKeyRegistration.encryptedUserSecrets.encryptedIdentityKey

    # As sent, it's deliberately corrupted - the official Find My Device app
    # could never decrypt it even with the right owner key.
    with pytest.raises(Exception):
        decrypt_eik(owner_key, encrypted_identity_key)

    # Un-flipping recovers the real EIK, which is what generated the EID
    # actually returned/advertised.
    eik = decrypt_eik(owner_key, flip_bits(encrypted_identity_key, True))
    assert generate_eid(eik, 0).hex() == result["eid_hex"]


def test_register_esp32_experimental_official_app_compat_skips_bit_flip(monkeypatch):
    captured = _stub_backend(monkeypatch)
    owner_key = bytes(32)

    result = create_ble_device.register_esp32(experimental_official_app_compat=True)

    request = RegisterBleDeviceRequest.FromString(captured["payload"])
    encrypted_identity_key = request.e2eePublicKeyRegistration.encryptedUserSecrets.encryptedIdentityKey

    # No corruption this time - decrypts directly with the real owner key,
    # same as a legitimately-paired device's would.
    eik = decrypt_eik(owner_key, encrypted_identity_key)
    assert generate_eid(eik, 0).hex() == result["eid_hex"]
