#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import gpsoauth

from Auth.aas_token_retrieval import get_aas_token
from Auth.fcm_receiver import FcmReceiver


def request_token(username, scope, play_services = False):

    aas_token = get_aas_token()
    android_id = FcmReceiver().get_android_id()
    request_app = 'com.google.android.gms' if play_services else 'com.google.android.apps.adm'

    auth_response = gpsoauth.perform_oauth(
        username, aas_token, android_id,
        service='oauth2:https://www.googleapis.com/auth/' + scope,
        app=request_app,
        client_sig='38918a453d07199354f8b19af05ec6562ced5788')

    if 'Auth' not in auth_response:
        # Google rejected the exchange outright (e.g. {'Error': 'BadAuthentication'})
        # instead of returning a token - surfaced this as a bare KeyError before,
        # which gave no indication anything had actually gone wrong with the
        # sign-in itself rather than a bug in this code.
        raise RuntimeError(
            f"Google rejected the sign-in for scope '{scope}': {auth_response}"
        )

    return auth_response['Auth']