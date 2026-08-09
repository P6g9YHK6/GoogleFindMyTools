#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from Auth.token_retrieval import request_token
from Auth.username_provider import get_username


def get_spot_token(username):
    return request_token(username, "spot", True)

if __name__ == '__main__':
    # This is a live Google auth token - don't pipe/redirect this into a log
    # file, CI output, or anything else that might end up somewhere less
    # trusted than your own terminal.
    print(get_spot_token(get_username()))