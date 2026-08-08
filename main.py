#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import logging

from NovaApi.ListDevices.nbe_list_devices import list_devices

if __name__ == '__main__':

    # Without this, only WARNING+ would reach Python's built-in last-resort
    # stderr handler, and anything at INFO (most of what the underlying
    # Auth/NovaApi/KeyBackup/... modules log) would be silently dropped
    # instead of showing up on the console the way the print()s they replaced
    # used to - see webui/main.py for the same reasoning on the web app side.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    list_devices()