#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json
import logging

from example_data_provider import get_example_data

logger = logging.getLogger(__name__)


def _transform_to_byte_array(json_object):
    """json_object is a JSON object used as a fake array - {"0": n, "1": n,
    ...} - which is how the vault API represents a byte string. Raise a
    clear error instead of a bare KeyError if it's not actually shaped that
    way."""
    if not isinstance(json_object, dict) or not all(str(i) in json_object for i in range(len(json_object))):
        raise ValueError(f"Expected a {{'0': n, '1': n, ...}}-shaped byte array, got {json_object!r}")
    return bytearray(json_object[str(i)] for i in range(len(json_object)))


def get_fmdn_shared_key(vault_keys):
    json_object = json.loads(vault_keys)

    for key in json_object:
        if key == "finder_hw":
            json_array = json_object[key]
            if not json_array:
                continue

            # Google's vault can hold multiple key generations ("epochs") for this
            # security domain if the account's FMDN owner key was ever rotated -
            # always take the newest one instead of whichever entry the array lists
            # first, or a stale/rotated-out epoch gets used and every decrypt against
            # current device data fails forever (see NovaApi's owner-key-version
            # mismatch error). The old code here unconditionally returned after the
            # first array entry and never compared epochs at all.
            latest = max(json_array, key=lambda item: int(item["epoch"]))
            logger.info("Selected vault key epoch %s (of %s available).", latest["epoch"], len(json_array))
            return _transform_to_byte_array(latest["key"])

    raise Exception("No suitable key found in the vault keys.")


if __name__ == '__main__':
    vault_keys = get_example_data("sample_vault_keys")
    print(get_fmdn_shared_key(vault_keys).hex())