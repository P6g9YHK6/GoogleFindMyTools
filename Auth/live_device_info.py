#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
"""On-demand client for Google's real-time "punctual" push channel
(signaler-pa.clients6.google.com), the only place battery percentage and
WiFi SSID for a device show up - the passive Nova DevicesList response
(ProtoDecoders/decoder.py) never carries them at all, confirmed against a
live account capture. Reverse-engineered from a browser HAR of the real
Find My Device web app (google.com/android/find); everything below is a
best-effort replication of undocumented, unofficial endpoints, so any
failure anywhere in this module is logged and swallowed rather than raised -
it must never break an actual locate.

Auth here is Google's "SAPISIDHASH" scheme (cookie-based, not the OAuth
tokens used everywhere else in this project) - see _sapisid_hash(). The
cookies it needs are captured once during the existing browser sign-in flow
(Auth/web_session.py) and persisted via Auth/token_cache.py.

Usage (see webui/scheduler.py): open a watch *before* triggering the actual
locate (the channel only ever delivers events to watches already open when
the update happens - a watch opened afterwards misses it), then wait for the
matching push once the locate is under way:

    watch = open_watch(canonic_id)
    ... trigger the locate through the normal Nova flow ...
    info = watch.wait_for_update() if watch else None
"""

import base64
import hashlib
import json
import logging
import os
import random
import re
import string
import time

import requests

from Auth.token_cache import get_cached_value

logger = logging.getLogger("Auth.live_device_info")

# Public API key embedded in the Find My Device web app's own page source -
# not a secret of ours, just an identifier for which Google product is
# calling this shared push infrastructure.
_CHANNEL_KEY = "AIzaSyBPOJ1lVLoR07Hc0LSSTPoe9SpvMf2xG4s"
_ORIGIN = "https://www.google.com"
_FMD_PAGE_URL = "https://www.google.com/android/find/?login=&device=1&rs=1"
_CHOOSE_SERVER_URL = "https://signaler-pa.clients6.google.com/punctual/v1/chooseServer"
_CHANNEL_URL = "https://signaler-pa.clients6.google.com/punctual/multi-watch/channel"
_TOPIC = "fmd_web"

_SAPISID_COOKIE_NAMES = ("SAPISID", "__Secure-3PAPISID")


def _sapisid_hash(sapisid: str, origin: str, timestamp: int | None = None) -> str:
    """https://developers.google.com/identity/sign-in/web/backend-auth's
    "SAPISIDHASH" scheme: proves possession of the (non-HttpOnly) SAPISID
    cookie without putting its value on the wire."""
    timestamp = timestamp if timestamp is not None else int(time.time())
    digest = hashlib.sha1(f"{timestamp} {sapisid} {origin}".encode()).hexdigest()
    return f"{timestamp}_{digest}"


def _random_token() -> str:
    """Shape-matches the opaque per-watch tokens the real web app generates
    client-side (~12 random bytes, base64url, no '=' padding). Purely our own
    value - nothing server-issued needs to be echoed back for this to work,
    since watches are matched by content (see _find_matching_blob), not by
    this token."""
    return base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")


def _random_zx() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=11))


def _build_session() -> tuple[requests.Session, str] | tuple[None, None]:
    cookies = get_cached_value("web_session_cookies")
    if not cookies:
        return None, None
    jar = requests.cookies.RequestsCookieJar()
    sapisid = None
    for c in cookies:
        name, value = c.get("name"), c.get("value")
        if not name or value is None:
            continue
        jar.set(name, value, domain=c.get("domain") or ".google.com", path=c.get("path") or "/")
        if sapisid is None and name in _SAPISID_COOKIE_NAMES:
            sapisid = value
    if sapisid is None:
        return None, None
    session = requests.Session()
    session.cookies = jar
    return session, sapisid


def _auth_headers(sapisid: str) -> dict:
    return {
        "Authorization": f"SAPISIDHASH {_sapisid_hash(sapisid, _ORIGIN)}",
        "Origin": _ORIGIN,
        "X-Goog-AuthUser": "0",
    }


_WIZ_FIELD_RE = {
    "FdrFJe": re.compile(r'"FdrFJe":(-?\d+)'),
    "cfb2h": re.compile(r'"cfb2h":"([^"]*)"'),
    "SNlM0e": re.compile(r'"SNlM0e":"([^"]*)"'),
}


def _get_page_tokens(session: requests.Session) -> dict | None:
    """window.WIZ_global_data is inlined as plain JS object literal in the
    page's own HTML - same values KeyBackup/vault_web_api.py reads via
    window.WIZ_global_data inside an actual browser; pulled out with a
    regex here since there's no browser in this path at all."""
    resp = session.get(_FMD_PAGE_URL, timeout=15)
    resp.raise_for_status()
    values = {}
    for key, pattern in _WIZ_FIELD_RE.items():
        m = pattern.search(resp.text)
        if not m:
            return None
        values[key] = m.group(1)
    return values


def _parse_chunked(text: str) -> list:
    """Google's streamed-array wire format shared by batchexecute and this
    channel: repeated <decimal-length>\\n<json-array> blocks. The declared
    length is only an approximate hint (see KeyBackup/vault_web_api.py's
    identical note) - json.JSONDecoder.raw_decode() finds the real end of
    each chunk regardless."""
    decoder = json.JSONDecoder()
    pos, n = 0, len(text)
    envelopes = []
    while pos < n:
        newline = text.find("\n", pos)
        if newline == -1 or not text[pos:newline].isdigit():
            break
        try:
            envelope, consumed = decoder.raw_decode(text, newline + 1)
        except ValueError:
            break
        envelopes.append(envelope)
        pos = consumed + 1 if consumed < n and text[consumed] == "\n" else consumed
    return envelopes


def _choose_server(session: requests.Session, sapisid: str, token: str) -> str | None:
    watch_entry = [None, None, None, [9, 5], None, [[_TOPIC], [1], [[[token]]]]]
    body = json.dumps([watch_entry, None, None, 0, 0])
    headers = {**_auth_headers(sapisid), "Content-Type": "application/json+protobuf"}
    resp = session.post(f"{_CHOOSE_SERVER_URL}?key={_CHANNEL_KEY}", data=body, headers=headers, timeout=10)
    resp.raise_for_status()
    decoded = json.loads(base64.b64decode(resp.text + "=="))
    return decoded[0] if decoded else None


def _open_channel(session: requests.Session, sapisid: str, gsessionid: str, token: str) -> str | None:
    watch_entry = [None, None, None, [9, 5], None, [[_TOPIC], [1], [[[token]]]]]
    req_data = json.dumps([[[1, watch_entry, None, None, 1], None, 3]])
    url = (f"{_CHANNEL_URL}?VER=8&gsessionid={gsessionid}&key={_CHANNEL_KEY}"
           f"&RID={random.randint(10000, 99999)}&CVER=22&zx={_random_zx()}&t=1")
    headers = {**_auth_headers(sapisid), "Content-Type": "application/x-www-form-urlencoded"}
    resp = session.post(url, data={"count": "1", "ofs": "0", "req0___data__": req_data}, headers=headers, timeout=10)
    resp.raise_for_status()
    for envelope in _parse_chunked(resp.text):
        for item in envelope:
            # [[0, ["c", "<channel sid>", "", 8, 14, 30000]]]
            if isinstance(item, list) and len(item) == 2 and isinstance(item[1], list) and item[1][:1] == ["c"]:
                return item[1][1]
    return None


def _find_matching_blob(obj, target: bytes) -> bytes | None:
    """Recursively hunts a parsed channel envelope for a base64 string that
    decodes to a protobuf blob mentioning our target canonic_id - simpler and
    more robust against the exact structural variation between chunks (seen
    across several captured samples) than hardcoding a fixed list-index path
    into every possible envelope shape."""
    if isinstance(obj, str):
        try:
            decoded = base64.b64decode(obj + "==")
        except Exception:
            return None
        return decoded if target in decoded else None
    if isinstance(obj, list):
        for item in obj:
            found = _find_matching_blob(item, target)
            if found is not None:
                return found
    return None


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    result, shift = 0, 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _decode_protobuf(buf: bytes) -> dict[int, list[tuple[int, object]]]:
    """Generic tag/wire-type walk, no schema - same technique used to
    reverse-engineer these fields in the first place. Returns
    {field_number: [(wire_type, value), ...]} since a field number can repeat
    (observed on this exact blob shape - see field 2 in the raw captures)."""
    i, out = 0, {}
    n = len(buf)
    while i < n:
        tag, i = _read_varint(buf, i)
        field_no, wire_type = tag >> 3, tag & 0x7
        if wire_type == 0:
            val, i = _read_varint(buf, i)
        elif wire_type == 1:
            val, i = buf[i:i + 8], i + 8
        elif wire_type == 2:
            length, i = _read_varint(buf, i)
            val, i = buf[i:i + length], i + length
        elif wire_type == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        out.setdefault(field_no, []).append((wire_type, val))
    return out


def _first_bytes(fields: dict, field_no: int) -> bytes | None:
    for wire_type, val in fields.get(field_no, []):
        if wire_type == 2:
            return val
    return None


def _first_varint(fields: dict, field_no: int) -> int | None:
    for wire_type, val in fields.get(field_no, []):
        if wire_type == 0:
            return val
    return None


# Fields under the phone-only status submessage (top-level field 3, nested
# field 3) confirmed against ground truth from a live account (battery: 95%,
# wifi: "Mordor") - see this session's HAR-based investigation notes.
_WIFI_FIELD, _BATTERY_FIELD = 30, 32


def parse_live_info(blob: bytes) -> dict | None:
    """Extracts whatever this project currently understands from one
    channel-push protobuf blob, plus a catch-all of anything else present
    but not yet confidently identified (raw_extra) rather than silently
    dropping it - see the Devices page. Returns None if the blob has no
    phone-style status section at all (e.g. it's a BLE tag - tags carry no
    battery/WiFi radio to report in the first place)."""
    device = _first_bytes(_decode_protobuf(blob), 3)
    if device is None:
        return None
    status = _first_bytes(_decode_protobuf(device), 3)
    if status is None:
        return None
    status_fields = _decode_protobuf(status)

    info: dict = {}

    wifi = _first_bytes(status_fields, _WIFI_FIELD)
    if wifi is not None:
        wifi_fields = _decode_protobuf(wifi)
        ssid_raw = _first_bytes(wifi_fields, 1)
        if ssid_raw is not None:
            info["wifi_ssid"] = ssid_raw.decode("utf-8", "replace").strip('"')
        signal = _first_varint(wifi_fields, 2)
        if signal is not None:
            info["wifi_signal"] = signal

    battery = _first_bytes(status_fields, _BATTERY_FIELD)
    if battery is not None:
        pct = _first_varint(_decode_protobuf(battery), 1)
        if pct is not None:
            info["battery_pct"] = pct

    # Everything else in this same status section - present on the wire but
    # not yet confidently identified. Kept as raw values (hex for bytes) so
    # nothing found gets silently thrown away before its meaning is nailed
    # down; see the Devices page's "Extra" column.
    handled = {_WIFI_FIELD, _BATTERY_FIELD}
    raw_extra = {
        str(field_no): [val.hex() if isinstance(val, bytes) else val for _wire_type, val in entries]
        for field_no, entries in status_fields.items()
        if field_no not in handled
    }
    if raw_extra:
        info["raw_extra"] = raw_extra

    return info or None


class LiveInfoWatch:
    """A channel watch opened for one device, waiting to be read exactly
    once. Blocking (like the rest of this project's Google calls) - callers
    run it via webui.deps.run_blocking."""

    def __init__(self, session: requests.Session, sapisid: str, gsessionid: str, channel_sid: str, canonic_id: str):
        self._session = session
        self._sapisid = sapisid
        self._gsessionid = gsessionid
        self._channel_sid = channel_sid
        self._canonic_id = canonic_id

    def wait_for_update(self, timeout: float = 15.0) -> dict | None:
        try:
            url = (f"{_CHANNEL_URL}?VER=8&gsessionid={self._gsessionid}&key={_CHANNEL_KEY}"
                   f"&RID=rpc&SID={self._channel_sid}&AID=0&CI=0&TYPE=xmlhttp&zx={_random_zx()}&t=1")
            resp = self._session.get(url, headers=_auth_headers(self._sapisid), timeout=timeout)
            resp.raise_for_status()
            target = self._canonic_id.encode()
            for envelope in _parse_chunked(resp.text):
                blob = _find_matching_blob(envelope, target)
                if blob is not None:
                    return parse_live_info(blob)
            logger.info(
                "No live update seen for %s within %ss - it may not have been actively "
                "located, or doesn't support this (e.g. a BLE tag has no WiFi/battery)",
                self._canonic_id, timeout,
            )
            return None
        except Exception:
            logger.exception("Live device info read failed for %s (non-fatal)", self._canonic_id)
            return None


def open_watch(canonic_id: str) -> LiveInfoWatch | None:
    """Opens a channel watch for canonic_id. Must be called *before*
    triggering the actual locate - see this module's docstring. None on any
    failure (including "no cookies captured yet"), always logged, never
    raised - a missing live-info watch must never affect the locate itself."""
    try:
        session, sapisid = _build_session()
        if session is None:
            logger.info(
                "No web session cookies cached yet for live device info - "
                "re-run Sign in with Google once with ENABLE_LIVE_DEVICE_INFO set to capture them"
            )
            return None
        tokens = _get_page_tokens(session)
        if tokens is None:
            logger.warning("Could not read the Find My Device page's session tokens - skipping live info")
            return None
        token = _random_token()
        gsessionid = _choose_server(session, sapisid, token)
        if not gsessionid:
            logger.warning("chooseServer call failed - skipping live info for %s", canonic_id)
            return None
        channel_sid = _open_channel(session, sapisid, gsessionid, token)
        if not channel_sid:
            logger.warning("Could not open the live info channel - skipping live info for %s", canonic_id)
            return None
        return LiveInfoWatch(session, sapisid, gsessionid, channel_sid, canonic_id)
    except Exception:
        logger.exception("Failed to open a live info watch for %s (non-fatal)", canonic_id)
        return None
