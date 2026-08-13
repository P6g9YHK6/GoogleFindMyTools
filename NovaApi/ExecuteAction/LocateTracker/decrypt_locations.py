#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import datetime
import hashlib
import logging

from Auth.token_cache import get_cached_values_with_prefix
from FMDNCrypto.foreign_tracker_cryptor import decrypt
from KeyBackup.cloud_key_decryptor import decrypt_aes_gcm, decrypt_eik
from NovaApi.ExecuteAction.LocateTracker.decrypted_location import WrappedLocation
from ProtoDecoders import Common_pb2, DeviceUpdate_pb2
from ProtoDecoders.decoder import parse_device_update_protobuf
from ProtoDecoders.DeviceUpdate_pb2 import DeviceRegistration
from SpotApi.CreateBleDevice.config import mcu_fast_pair_model_id
from SpotApi.CreateBleDevice.util import flip_bits
from SpotApi.GetEidInfoForE2eeDevices.get_eid_info_request import get_eid_info
from SpotApi.GetEidInfoForE2eeDevices.get_owner_key import get_owner_key, get_owner_key_from_wrapped_blob

logger = logging.getLogger(__name__)


def create_map_links(latitude, longitude):
    """One link per major map provider for a single location, OpenStreetMap
    first (the default/primary one) - returned as a dict rather than a
    single URL so callers can offer a choice instead of being locked into
    whichever provider used to be hardcoded here. None of these need an API
    key; each is just a deep-link URL built straight from the coordinates.
    Returns {} for invalid coordinates instead of a link, rather than the
    old behavior of quietly handing back an error string as if it were one."""
    try:
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid latitude or longitude values.")
    except ValueError:
        return {}

    return {
        "OSM": f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=17/{latitude}/{longitude}",
        "Google": f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}",
        "Apple": f"https://maps.apple.com/?ll={latitude},{longitude}&q=Location",
        "Bing": f"https://www.bing.com/maps?cp={latitude}~{longitude}&lvl=16",
        "Waze": f"https://waze.com/ul?ll={latitude},{longitude}&navigate=yes",
    }

# Indicates if the device is a custom microcontroller
def is_mcu_tracker(device_registration: DeviceRegistration) -> bool:
    return device_registration.fastPairModelId == mcu_fast_pair_model_id


def retrieve_identity_key(device_registration: DeviceRegistration) -> bytes:
    is_mcu = is_mcu_tracker(device_registration)
    encrypted_user_secrets = device_registration.encryptedUserSecrets

    encrypted_identity_key = flip_bits(
        encrypted_user_secrets.encryptedIdentityKey,
        is_mcu)

    try:
        return decrypt_eik(get_owner_key(), encrypted_identity_key)
    except Exception as e:
        logger.debug("Current owner key didn't decrypt this tracker's identity key (%s), trying next.", e)

    # The account-level "current" owner key (owner_key_version=-1) didn't decrypt
    # this tracker's identity key - retry by asking explicitly for the version the
    # tracker's own data says it needs, instead of trusting whatever "-1" happened
    # to resolve to. An account can have trackers on more than one owner key
    # generation; see SpotApi/GetEidInfoForE2eeDevices/get_owner_key.py.
    needed_version = encrypted_user_secrets.ownerKeyVersion
    try:
        return decrypt_eik(get_owner_key(owner_key_version=needed_version), encrypted_identity_key)
    except Exception as e:
        logger.debug("Owner key version %s didn't decrypt this tracker's identity key (%s), trying next.",
                      needed_version, e)

    # Last resort: GetEidInfoForE2eeDevices always hands back its own idea of
    # "current" regardless of which version we ask it for (both attempts
    # above confirmed that empirically) - so try every owner-key blob fetched
    # directly from the real Find My Device web app's own API during sign-in
    # instead (see KeyBackup/vault_web_api.py). Each is still encrypted with
    # this account's one stable shared key; verified that unwrapping the
    # "current" version's blob this way reproduces the exact owner key the
    # normal path above already derives, so the same unwrap applied to every
    # other cached version is expected to yield each of those real keys too.
    for name, blob_hex in get_cached_values_with_prefix("encrypted_owner_key_v").items():
        try:
            owner_key = get_owner_key_from_wrapped_blob(bytes.fromhex(blob_hex))
            identity_key = decrypt_eik(owner_key, encrypted_identity_key)
            logger.info("Decrypted using %s.", name)
            return identity_key
        except Exception:
            continue

    e2eeData = get_eid_info()
    current_owner_key_version = e2eeData.encryptedOwnerKeyAndMetadata.ownerKeyVersion

    if encrypted_user_secrets.ownerKeyVersion < current_owner_key_version:
        message = (
            f"Failed to decrypt E2EE data. This tracker was encrypted with owner key version "
            f"{encrypted_user_secrets.ownerKeyVersion}, but the current owner key version is "
            f"{current_owner_key_version}.\nThis happens if you reset your end-to-end-encrypted "
            f"data in the past.\nThe tracker cannot be decrypted anymore, and it is recommended "
            f"to remove it in the Find My Device app."
        )
    else:
        tried_versions = ", ".join(sorted(get_cached_values_with_prefix("encrypted_owner_key_v").keys())) or "none cached"
        message = (
            f"Failed to decrypt identity key encrypted with owner key version "
            f"{encrypted_user_secrets.ownerKeyVersion}, current owner key version is "
            f"{current_owner_key_version}. Also retried by explicitly requesting owner key "
            f"version {needed_version}, and by trying every vault key version fetched from the "
            f"Find My Device web app during sign-in ({tried_versions}) - all failed to decrypt."
            f"\nThis may happen if the cached owner key is stale (e.g. after re-doing the Google "
            f"sign-in). To resolve this issue, clear the 'owner_key' entry from "
            f"'Auth/secrets.json' so it gets re-derived, or delete the whole file to sign in "
            f"again from scratch."
        )
    logger.error(message)
    # exit(1) here would raise SystemExit, which is fine for the CLI scripts this
    # was originally written for but fatal when called from a web request thread
    # (asyncio.to_thread) - it doesn't stop the server, just crashes that one
    # request with a bare "Internal Server Error" and no indication why. Raise a
    # normal exception instead so callers (e.g. the web UI's locate endpoint) can
    # show `message` to the user.
    raise RuntimeError(message)


def decrypt_location_response_locations(device_update_protobuf):

    device_registration = device_update_protobuf.deviceMetadata.information.deviceRegistration

    identity_key = retrieve_identity_key(device_registration)
    locations_proto = device_update_protobuf.deviceMetadata.information.locationInformation.reports.recentLocationAndNetworkLocations
    is_mcu = is_mcu_tracker(device_registration)

    # At All Areas Reports or Own Reports
    recent_location = locations_proto.recentLocation
    recent_location_time = locations_proto.recentLocationTimestamp

    # High Traffic Reports
    network_locations = list(locations_proto.networkLocations)
    network_locations_time = list(locations_proto.networkLocationTimestamps)

    if locations_proto.HasField("recentLocation"):
        network_locations.append(recent_location)
        network_locations_time.append(recent_location_time)

    location_time_array = []
    for loc, time in zip(network_locations, network_locations_time):

        if loc.status == Common_pb2.Status.SEMANTIC:
            wrapped_location = WrappedLocation(
                decrypted_location=b'',
                time=int(time.seconds),
                accuracy=0,
                status=loc.status,
                is_own_report=True,
                name=loc.semanticLocation.locationName
            )
            location_time_array.append(wrapped_location)
        else:

            encrypted_location = loc.geoLocation.encryptedReport.encryptedLocation
            public_key_random = loc.geoLocation.encryptedReport.publicKeyRandom

            if public_key_random == b"":  # Own Report
                identity_key_hash = hashlib.sha256(identity_key).digest()
                decrypted_location = decrypt_aes_gcm(identity_key_hash, encrypted_location)
            else:
                time_offset = 0 if is_mcu else loc.geoLocation.deviceTimeOffset
                decrypted_location = decrypt(identity_key, encrypted_location, public_key_random, time_offset)

            wrapped_location = WrappedLocation(
                decrypted_location=decrypted_location,
                time=int(time.seconds),
                accuracy=loc.geoLocation.accuracy,
                status=loc.status,
                is_own_report=loc.geoLocation.encryptedReport.isOwnReport,
                name=""
            )
            location_time_array.append(wrapped_location)

    if not location_time_array:
        logger.info("No locations found.")
        return []

    logger.info("Decrypted %d location report(s).", len(location_time_array))
    results = []

    for loc in location_time_array:

        is_semantic = loc.status == Common_pb2.Status.SEMANTIC
        latitude = longitude = altitude = None
        loc_time_str = datetime.datetime.fromtimestamp(loc.time).strftime("%Y-%m-%d %H:%M:%S")

        if is_semantic:
            logger.info("Semantic location %r at %s (status=%s, own_report=%s)",
                        loc.name, loc_time_str, loc.status, loc.is_own_report)
        else:
            proto_loc = DeviceUpdate_pb2.Location()
            proto_loc.ParseFromString(loc.decrypted_location)

            latitude = proto_loc.latitude / 1e7
            longitude = proto_loc.longitude / 1e7
            altitude = proto_loc.altitude

            logger.info("Location %s, %s (altitude=%s) at %s (status=%s, own_report=%s) - %s",
                        latitude, longitude, altitude, loc_time_str, loc.status, loc.is_own_report,
                        create_map_links(latitude, longitude).get("OSM"))

        results.append({
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "time": loc.time,
            "is_semantic": is_semantic,
            "semantic_name": loc.name if is_semantic else None,
            "status": Common_pb2.Status.Name(loc.status),
            "accuracy": loc.accuracy,
            "is_own_report": loc.is_own_report,
            "map_links": create_map_links(latitude, longitude) if not is_semantic else None,
        })

    return results


if __name__ == '__main__':
    res = parse_device_update_protobuf("")
    decrypt_location_response_locations(res)