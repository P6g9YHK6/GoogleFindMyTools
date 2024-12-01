#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from Auth.token_cache import get_cached_value

def get_username():
    return get_cached_value('username', lambda: input("[UsernameProvider] Username was not setup yet. Enter your Google Username (Email without @gmail.com)') and hit enter:"))

if __name__ == '__main__':
    get_username()