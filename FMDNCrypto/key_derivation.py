#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from FMDNCrypto.sha import calculate_truncated_sha256


class FMDNOwnerOperations:

    def __init__(self):
        self.recovery_key = None
        self.ringing_key = None
        self.tracking_key = None

    def generate_keys(self, identity_key: bytes):
        # Deliberately no try/except here: both callers (create_ble_device.py,
        # link_generator.py) feed these keys straight into protobuf fields
        # right after this call with no None-check, so swallowing a failure
        # here used to just relocate the crash to a confusing TypeError far
        # from the real cause instead of preventing it. Let it raise.
        self.recovery_key = calculate_truncated_sha256(identity_key, 0x01)
        self.ringing_key = calculate_truncated_sha256(identity_key, 0x02)
        self.tracking_key = calculate_truncated_sha256(identity_key, 0x03)