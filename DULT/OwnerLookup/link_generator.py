#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
from binascii import unhexlify

from example_data_provider import get_example_data
from FMDNCrypto.eid_generator import ROTATION_PERIOD, generate_eid
from FMDNCrypto.key_derivation import FMDNOwnerOperations
from FMDNCrypto.sha import calculate_hmac_sha256


def get_owner_lookup_link(eik: bytes, offset: int) -> tuple[str, str]:

    ownerOperations = FMDNOwnerOperations()
    ownerOperations.generate_keys(eik)

    recoveryKey = ownerOperations.recovery_key
    eid = generate_eid(eik, offset)

    truncated_ephemeral_id = eid[:10]
    hmac = calculate_hmac_sha256(recoveryKey, truncated_ephemeral_id)

    hmac_truncated = hmac[:16]

    return (eid.hex(), 'https://spot-pa.googleapis.com/lookup?e=' + truncated_ephemeral_id.hex() + hmac_truncated)

if __name__ == '__main__':

    sample_identity_key = unhexlify(get_example_data("sample_identity_key"))

    # Generate a few URLs
    for i in range(1000):
        offset = i*ROTATION_PERIOD
        print(get_owner_lookup_link(sample_identity_key, offset))