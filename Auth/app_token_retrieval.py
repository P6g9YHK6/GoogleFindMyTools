#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import gpsoauth

from Auth.aas_token_retrieval import get_aas_token
from Auth.android_id_generator import get_android_id

def request_fmdn_app_token(username, scope):

    print("[AppTokenRetrieval] Asking Server for " + scope + " token.")

    aas_token = get_aas_token()
    android_id = get_android_id()

    auth_response = gpsoauth.perform_oauth(
        username, aas_token, android_id,
        service='oauth2:https://www.googleapis.com/auth/' + scope,
        app='com.google.android.apps.adm',
        client_sig='38918a453d07199354f8b19af05ec6562ced5788')
    token = auth_response['Auth']

    return token