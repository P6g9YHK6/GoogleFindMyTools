#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import _status_name
from ProtoDecoders import Common_pb2


def test_status_name_resolves_known_statuses():
    assert _status_name(Common_pb2.Status.LAST_KNOWN) == "LAST_KNOWN"
    assert _status_name(Common_pb2.Status.SEMANTIC) == "SEMANTIC"


def test_status_name_survives_an_unrecognized_status():
    # Google occasionally rolls out new Status values before this enum is
    # updated to match (same situation as SpotDeviceType, see
    # tests/test_decoder.py) - one unrecognized status shouldn't take down
    # location decoding for the rest of the device's reports.
    assert _status_name(99) == "STATUS_UNKNOWN_99"
