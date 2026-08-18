#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import logging
import threading

from google.protobuf import text_format

from Auth.fcm_receiver import FcmReceiver
from example_data_provider import get_example_data
from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations
from NovaApi.ExecuteAction.nbe_execute_action import create_action_request, serialize_action_request
from NovaApi.nova_request import nova_request
from NovaApi.scopes import NOVA_ACTION_API_SCOPE
from NovaApi.util import generate_random_uuid
from ProtoDecoders import DeviceUpdate_pb2
from ProtoDecoders.decoder import custom_message_formatter, parse_device_update_protobuf

logger = logging.getLogger(__name__)


def create_location_request(canonic_device_id, fcm_registration_id, request_uuid):

    action_request = create_action_request(canonic_device_id, fcm_registration_id, request_uuid=request_uuid)

    # Random values, can be arbitrary
    action_request.action.locateTracker.lastHighTrafficEnablingTime.seconds = 1732120060
    action_request.action.locateTracker.contributorType = DeviceUpdate_pb2.SpotContributorType.FMDN_ALL_LOCATIONS

    # Convert to hex string
    hex_payload = serialize_action_request(action_request)

    return hex_payload


def get_location_data_for_device(canonic_device_id, name, timeout: float = 60, capture: dict | None = None):
    """`capture`, if given, is filled in with the raw wire data behind the
    returned (decrypted) locations - the hex FCM payload and a human-readable
    protobuf text dump - so a caller that needs the underlying response for
    debugging (see webui/routers/debug_export.py) doesn't have to duplicate
    this whole request/FCM-wait dance to get at it. Purely additive: with the
    default capture=None this behaves exactly as before."""

    logger.info("Requesting location data for %s...", name)

    result = None
    received = threading.Event()
    request_uuid = generate_random_uuid()
    receiver = FcmReceiver()

    def handle_location_response(response):
        nonlocal result
        device_update = parse_device_update_protobuf(response)

        if device_update.fcmMetadata.requestUuid == request_uuid:
            logger.info("Location request for %s successful. Decrypting locations...", name)
            result = device_update
            if capture is not None:
                # `response` is already the raw hex string handed up from
                # Auth/fcm_receiver.py's notification callback.
                capture["raw_hex"] = response
            #print_device_update_protobuf(response)
            received.set()

    fcm_token = receiver.register_for_location_updates(handle_location_response)

    try:
        hex_payload = create_location_request(canonic_device_id, fcm_token, request_uuid)
        nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

        if not received.wait(timeout=timeout):
            # This is the only signal of a "no FCM push ever arrived" failure -
            # WARNING (not just a print) so it actually reaches logging-based
            # monitoring/alerting (see webui/notify.py) instead of only ever
            # showing up in a terminal someone happens to be watching.
            logger.warning("Timed out after %ss waiting for %s.", timeout, name)
            if capture is not None:
                capture["timed_out"] = True
            return []

        if capture is not None:
            capture["device_update_text"] = text_format.MessageToString(
                result, message_formatter=custom_message_formatter,
            )
        return decrypt_location_response_locations(result)
    finally:
        receiver.unregister_callback(handle_location_response)

if __name__ == '__main__':
    get_location_data_for_device(get_example_data("sample_canonic_device_id"), "Test")