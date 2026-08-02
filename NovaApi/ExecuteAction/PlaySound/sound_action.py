#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from Auth.fcm_receiver import FcmReceiver
from NovaApi.ExecuteAction.PlaySound.sound_request import create_sound_request
from NovaApi.nova_request import nova_request
from NovaApi.scopes import NOVA_ACTION_API_SCOPE


def play_sound(canonic_device_id, should_start):
    gcm_registration_id = FcmReceiver().get_fcm_token()

    hex_payload = create_sound_request(should_start, canonic_device_id, gcm_registration_id)
    nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

    return {"ok": True, "should_start": should_start}
