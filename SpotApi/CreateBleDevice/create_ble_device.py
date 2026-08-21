#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import logging
import secrets
import time

from FMDNCrypto.eid_generator import ROTATION_PERIOD, generate_eid
from FMDNCrypto.key_derivation import FMDNOwnerOperations
from KeyBackup.cloud_key_decryptor import encrypt_aes_gcm
from ProtoDecoders.DeviceUpdate_pb2 import (
    DeviceComponentInformation,
    PublicKeyIdList,
    RegisterBleDeviceRequest,
    SpotDeviceType,
)
from SpotApi.CreateBleDevice.config import max_truncated_eid_seconds_server, mcu_fast_pair_model_id
from SpotApi.CreateBleDevice.util import flip_bits
from SpotApi.GetEidInfoForE2eeDevices.get_owner_key import get_owner_key
from SpotApi.spot_request import spot_request

logger = logging.getLogger(__name__)


def register_esp32(
    display_name: str = "GoogleFindMyTools µC",
    device_type: str = "DEVICE_TYPE_BEACON",
    manufacturer_name: str = "GoogleFindMyTools",
    model_name: str = "µC",
    image_url: str = "https://docs.espressif.com/projects/esp-idf/en/v4.3/esp32/_images/esp32-DevKitM-1-isometric.png",
    experimental_official_app_compat: bool = False,
):

    owner_key = get_owner_key()

    eik = secrets.token_bytes(32)
    eid = generate_eid(eik, 0)
    pair_date = int(time.time())

    register_request = RegisterBleDeviceRequest()
    register_request.fastPairModelId = mcu_fast_pair_model_id

    # Description
    register_request.description.userDefinedName = display_name
    register_request.description.deviceType = SpotDeviceType.Value(device_type)

    # Device Components Information
    component_information = DeviceComponentInformation()
    component_information.imageUrl = image_url
    register_request.description.deviceComponentsInformation.append(component_information)

    # Capabilities
    register_request.capabilities.isAdvertising = True
    register_request.capabilities.trackableComponents = 1
    register_request.capabilities.capableComponents = 1

    # E2EE Registration
    register_request.e2eePublicKeyRegistration.rotationExponent = 10
    register_request.e2eePublicKeyRegistration.pairingDate = pair_date

    # Encrypted User Secrets
    # By default, flip bits so the official Find My Device app cannot decrypt
    # this key - Google's client is deliberately handed an opaque blob it
    # can't act on for a tracker this project alone manages. When
    # experimental_official_app_compat is set, skip that corruption instead:
    # encryptedIdentityKey is then encrypted under owner_key exactly like a
    # real Android-registered device's would be, so the account's own owner
    # key (see get_owner_key() above) can in principle decrypt it - whether
    # the closed-source official app actually renders/locates it as a result
    # is unverified, this only controls what's sent. Either way,
    # SpotApi/identity_key.py's retrieve_identity_key() has to keep working,
    # since fastPairModelId below is identical in both cases and can't tell
    # them apart on its own.
    encrypted_identity_key = encrypt_aes_gcm(owner_key, eik)
    if not experimental_official_app_compat:
        encrypted_identity_key = flip_bits(encrypted_identity_key, True)
    register_request.e2eePublicKeyRegistration.encryptedUserSecrets.encryptedIdentityKey = encrypted_identity_key

    # Random keys, not used for ESP
    register_request.e2eePublicKeyRegistration.encryptedUserSecrets.encryptedAccountKey = secrets.token_bytes(44)
    register_request.e2eePublicKeyRegistration.encryptedUserSecrets.encryptedSha256AccountKeyPublicAddress = secrets.token_bytes(60)

    register_request.e2eePublicKeyRegistration.encryptedUserSecrets.ownerKeyVersion = 1
    register_request.e2eePublicKeyRegistration.encryptedUserSecrets.creationDate.seconds = pair_date

    time_counter = pair_date
    truncated_eid = eid[:10]

    # announce advertisements
    for _ in range(int(max_truncated_eid_seconds_server / ROTATION_PERIOD)):
        pub_key_id = PublicKeyIdList.PublicKeyIdInfo()
        pub_key_id.publicKeyId.truncatedEid = truncated_eid
        pub_key_id.timestamp.seconds = time_counter
        register_request.e2eePublicKeyRegistration.publicKeyIdList.publicKeyIdInfo.append(pub_key_id)

        time_counter += ROTATION_PERIOD

    # General
    register_request.manufacturerName = manufacturer_name
    register_request.modelName = model_name

    ownerKeys = FMDNOwnerOperations()
    ownerKeys.generate_keys(identity_key=eik)

    register_request.ringKey = ownerKeys.ringing_key
    register_request.recoveryKey = ownerKeys.recovery_key
    register_request.unwantedTrackingKey = ownerKeys.tracking_key

    bytes_data = register_request.SerializeToString()
    spot_request("CreateBleDevice", bytes_data)

    logger.info("Registered device successfully. Advertisement key: %s. Go to "
                "'GoogleFindMyToolsWebUi/ESP32Firmware' or 'GoogleFindMyToolsWebUi/ZephyrFirmware' and "
                "follow the instructions in the README.md file.", eid.hex())

    return {
        "eid_hex": eid.hex(),
        "advertisement_key": eid.hex(),
        "pair_date": pair_date,
    }