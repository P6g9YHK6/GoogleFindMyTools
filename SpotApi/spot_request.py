#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import logging

import httpx
from bs4 import BeautifulSoup

from Auth.spot_token_retrieval import get_spot_token
from Auth.username_provider import get_username
from NovaApi.query_throttle import query_throttle
from SpotApi.grpc_parser import GrpcParser

logger = logging.getLogger(__name__)


def spot_request(api_scope: str, payload: bytes) -> bytes:
    url = "https://spot-pa.googleapis.com/google.internal.spot.v1.SpotService/" + api_scope
    spot_oauth_token = get_spot_token(get_username())

    headers = {
        "User-Agent": "com.google.android.gms/244433022 grpc-java-cronet/1.69.0-SNAPSHOT",
        "Content-Type": "application/grpc",
        "Te": "trailers",
        "Authorization": "Bearer " + spot_oauth_token,
        "Grpc-Accept-Encoding": "gzip"
    }

    payload = GrpcParser.construct_grpc(payload)

    # httpx is necessary because requests does not support the Te header
    query_throttle.wait_turn()
    with httpx.Client(http2=True, timeout=30.0) as client:
        response = client.post(url, headers=headers, content=payload)

        if response.status_code == 200:
            result = GrpcParser.extract_grpc_payload(response.content)
            return result
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            logger.warning("Spot request to %s failed with %s: %s", api_scope, response.status_code, soup.get_text())

    return b''