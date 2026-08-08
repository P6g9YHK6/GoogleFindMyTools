#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
import logging
import os
from binascii import unhexlify

from Auth.token_cache import get_cached_value_or_set
from KeyBackup.shared_key_flow import request_shared_key_flow

logger = logging.getLogger(__name__)


def _retrieve_shared_key():
    logger.info("You need to log in again to access end-to-end encrypted keys to decrypt "
                "location reports. This will now open Google Chrome on your device. "
                "For macOS users only: allow Python (or PyCharm) to control Chrome.")

    # Press enter to continue (skipped when driven non-interactively, e.g. from the web UI's browser container)
    if os.environ.get("GFMT_NONINTERACTIVE") != "1":
        input("[SharedKeyRetrieval] Press 'Enter' to continue...")

    shared_key = request_shared_key_flow()

    return shared_key


def get_shared_key() -> bytes:
    return unhexlify(get_cached_value_or_set('shared_key', _retrieve_shared_key))


if __name__ == '__main__':
    print(get_shared_key())