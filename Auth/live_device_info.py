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

import asyncio
import base64
import hashlib
import json
import logging
import os
import queue
import random
import re
import ssl
import string
import threading
import time
import urllib.parse

import requests
from aioquic.asyncio import connect as quic_connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration

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
# Only ever overridden by tests, to run the HTTP/3 channel read against a
# local self-signed server instead of the real one - see _listen_http3.
_QUIC_VERIFY_MODE = ssl.CERT_REQUIRED

_SAPISID_COOKIE_NAMES = ("SAPISID", "__Secure-3PAPISID")

# Every other Google-facing request in this project sends a User-Agent
# matching the real client it's impersonating (see NovaApi/nova_request.py,
# SpotApi/spot_request.py) - this module didn't, so Google saw requests'
# default "python-requests/x.y.z" UA and served something other than the
# real page (no window.WIZ_global_data to scrape), which _get_page_tokens
# below then couldn't find its fields in. These cookies were captured from
# an actual Chrome-for-Testing session (see Auth/web_session.py), so a
# current desktop Chrome UA is the most consistent thing to present them
# with on every subsequent request through this session.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


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
    session.headers["User-Agent"] = _BROWSER_USER_AGENT
    return session, sapisid


def _auth_headers(sapisid: str) -> dict:
    return {
        "Authorization": f"SAPISIDHASH {_sapisid_hash(sapisid, _ORIGIN)}",
        "Origin": _ORIGIN,
        "X-Goog-AuthUser": "0",
    }


_WIZ_FIELD_RE = {
    # FdrFJe comes back as a quoted string, not a bare number - confirmed
    # both in a live capture and in the original HAR this module was reverse
    # engineered from (values like "-1529750813986083965" don't fit a JS
    # safe integer, so Google stringifies it). The unquoted alternative is
    # kept too in case that ever changes back - either way, only the digits
    # end up in the capture group.
    "FdrFJe": re.compile(r'"FdrFJe":"?(-?\d+)"?'),
    "cfb2h": re.compile(r'"cfb2h":"([^"]*)"'),
    "SNlM0e": re.compile(r'"SNlM0e":"([^"]*)"'),
}


def _fetch_fmd_page(session: requests.Session) -> str:
    resp = session.get(_FMD_PAGE_URL, timeout=15)
    resp.raise_for_status()
    return resp.text


def _get_page_tokens(page_text: str) -> dict | None:
    """window.WIZ_global_data is inlined as plain JS object literal in the
    page's own HTML - same values KeyBackup/vault_web_api.py reads via
    window.WIZ_global_data inside an actual browser; pulled out with a
    regex here since there's no browser in this path at all."""
    values = {}
    for key, pattern in _WIZ_FIELD_RE.items():
        m = pattern.search(page_text)
        if not m:
            return None
        values[key] = m.group(1)
    return values


def _get_device_numeric_id(page_text: str, canonic_id: str) -> str | None:
    """The page's own initial device list (embedded as an AF_initDataCallback
    blob, same mechanism as window.WIZ_global_data - just a different
    payload) pairs each phone with an internal numeric id right next to its
    canonic_id: `..."<numeric_id>",[["<canonic_id>"...`. This is the id
    SWJ22b (see _request_live_status) needs in the *first* position of its
    payload - confirmed by locating this exact substring in a real page
    capture. BLE tags don't have one there at all (matches the "phones
    only" scope this feature already documents), so None here is a normal,
    expected outcome for a tag - not a parse failure."""
    m = re.search(r'"(\d+)",\[\["' + re.escape(canonic_id) + '"', page_text)
    return m.group(1) if m else None


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


def _decode_maybe_base64_json(text: str):
    """chooseServer's response body has been observed both ways for the
    exact same call against the same account (the HAR this module was built
    from had it base64-encoded; a live repro while debugging this got plain
    JSON back directly) - try plain JSON first since that's the cheap,
    unambiguous case, and only fall back to base64 if that fails. Getting
    this backwards silently corrupts the plain-JSON case instead of raising:
    b64decode(validate=False) just drops every non-base64-alphabet character
    (quotes, brackets, commas, ...) and "successfully" decodes whatever's
    left into garbage bytes, which then fail utf-8 decoding inside
    json.loads with a confusing UnicodeDecodeError."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(base64.b64decode(text + "=="))


def _choose_server(session: requests.Session, sapisid: str, token: str) -> str | None:
    watch_entry = [None, None, None, [9, 5], None, [[_TOPIC], [1], [[[token]]]]]
    body = json.dumps([watch_entry, None, None, 0, 0])
    headers = {**_auth_headers(sapisid), "Content-Type": "application/json+protobuf"}
    resp = session.post(f"{_CHOOSE_SERVER_URL}?key={_CHANNEL_KEY}", data=body, headers=headers, timeout=10)
    resp.raise_for_status()
    decoded = _decode_maybe_base64_json(resp.text)
    return decoded[0] if decoded else None


def _open_channel(session: requests.Session, sapisid: str, gsessionid: str, token: str) -> tuple[str, float | None] | tuple[None, None]:
    watch_entry = [None, None, None, [9, 5], None, [[_TOPIC], [1], [[[token]]]]]
    req_data = json.dumps([[[1, watch_entry, None, None, 1], None, 3]])
    url = (f"{_CHANNEL_URL}?VER=8&gsessionid={gsessionid}&key={_CHANNEL_KEY}"
           f"&RID={random.randint(10000, 99999)}&CVER=22&zx={_random_zx()}&t=1")
    headers = {**_auth_headers(sapisid), "Content-Type": "application/x-www-form-urlencoded"}
    resp = session.post(url, data={"count": "1", "ofs": "0", "req0___data__": req_data}, headers=headers, timeout=10)
    resp.raise_for_status()
    for envelope in _parse_chunked(resp.text):
        for item in envelope:
            # [[0, ["c", "<channel sid>", "", 8, 14, 30000]]] - the last
            # element is the server's own long-poll duration for this
            # channel, in milliseconds (confirmed 30000 both live and in the
            # original HAR). LiveInfoWatch.wait_for_update needs this: its
            # request timeout must be at least this long, or the client
            # gives up (ReadTimeoutError) before the server would ever
            # naturally respond to a still-open long poll.
            if isinstance(item, list) and len(item) == 2 and isinstance(item[1], list) and item[1][:1] == ["c"]:
                inner = item[1]
                server_timeout_s = inner[5] / 1000 if len(inner) > 5 and isinstance(inner[5], (int, float)) else None
                return inner[1], server_timeout_s
    return None, None


_LIVE_STATUS_URL = "https://www.google.com/android/find/_/BoqWebFindMyDeviceUi/data/batchexecute"


def _request_live_status(session: requests.Session, sapisid: str, page_tokens: dict, device_numeric_id: str,
                          canonic_id: str, channel_token: str) -> bool:
    """Asks Google's backend to ping this phone for a live status update and
    route the response to whichever channel is watching channel_token - see
    this module's docstring for why open_channel() alone is a no-op without
    this. Reverse-engineered from a real capture of the "SWJ22b" batchexecute
    RPC the website itself makes right after opening its own channel watch;
    two parts of that payload are best-effort reconstructions rather than
    confirmed values, called out below. Returns whether the request was
    accepted - never raises, this is one extra best-effort step in a chain
    that must never block the locate itself on a failure here.

    Unconfirmed pieces, in case a live account ever needs deeper debugging:
    - The ~16-byte blob in the 2nd payload segment: not found anywhere else
      in the reference capture (not on the page, not in an earlier
      response), so it reads as a client-generated per-request nonce -
      generated fresh here the same way, standard (not urlsafe) base64 to
      match its observed "==" padding.
    - The 2nd token in the 3rd segment: identical across two different
      SWJ22b calls *within the same already-loaded page* in the capture,
      but that's consistent with it being a session-scoped id the page's JS
      generated once and reused - since open_watch() always starts a fresh
      "session" (a new page load) per call, generating a fresh one here
      each time is the direct equivalent, not a guess that ignores the
      evidence.
    """
    nonce = base64.b64encode(os.urandom(16)).decode()
    session_token = _random_token()
    inner = json.dumps([
        [[device_numeric_id, [[canonic_id]]], 1],
        [None, None, None, [nonce]],
        [1, channel_token, session_token, None, [channel_token], 1],
    ])
    body = json.dumps([[["SWJ22b", inner, None, "generic"]]])
    params = {
        "rpcids": "SWJ22b",
        "source-path": "/android/find/",
        "f.sid": page_tokens.get("FdrFJe", ""),
        "bl": page_tokens.get("cfb2h", ""),
        "hl": "en-GB",
        "_reqid": str(random.randint(100000, 999999)),
        "rt": "c",
    }
    data = {"f.req": body, "at": page_tokens.get("SNlM0e", "")}
    headers = {**_auth_headers(sapisid), "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    resp = session.post(_LIVE_STATUS_URL, params=params, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    return "SWJ22b" in resp.text


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
    run it via webui.deps.run_blocking.

    Starts listening on the channel immediately, in a background thread,
    rather than waiting for a later wait_for_update() call to do it - a real
    capture showed the website itself starts its long-poll GET only ~300ms
    after opening the channel, *before* it triggers the live-status request
    (SWJ22b) that actually causes Google to push something. This project's
    own flow calls open_watch() then does a whole separate locate() (a
    second or more) before ever calling wait_for_update() - if the update
    only arrives once, right after SWJ22b, waiting that long to start
    listening means missing it entirely, matching the module docstring's
    note that the channel never delivers to a watch that wasn't already
    open when the update happened."""

    def __init__(self, session: requests.Session, sapisid: str, gsessionid: str, channel_sid: str, canonic_id: str,
                 server_timeout_s: float | None = None):
        self._session = session
        self._sapisid = sapisid
        self._gsessionid = gsessionid
        self._channel_sid = channel_sid
        self._canonic_id = canonic_id
        # The channel's own declared long-poll duration (see _open_channel) -
        # falls back to a plain default if that couldn't be read.
        self._deadline_s = (server_timeout_s or 15.0) + 5  # +5s slack for ordinary network/processing delay
        self._result: queue.Queue[dict | None] = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        # aioquic is asyncio-only - run a private event loop just for this
        # background thread rather than restructuring the rest of this
        # (deliberately synchronous, run-via-webui.deps.run_blocking) class.
        result = None
        try:
            result = asyncio.run(self._listen_http3())
            if result is None:
                logger.info(
                    "No live update seen for %s within %ss - it may not have been actively "
                    "located, or doesn't support this (e.g. a BLE tag has no WiFi/battery)",
                    self._canonic_id, self._deadline_s,
                )
        except Exception:
            logger.exception("Live device info read failed for %s (non-fatal)", self._canonic_id)
        self._result.put(result)

    async def _listen_http3(self) -> dict | None:
        # HTTP/3, not HTTP/1.1 or HTTP/2: a real browser capture (with a
        # real push actually arriving, decoded via this same
        # parse_live_info() and confirmed against ground truth - wifi
        # "Mordor", battery 86%) showed the successful request used HTTP/3.
        # Every earlier attempt here over HTTP/1.1 or HTTP/2 - however
        # faithfully it replicated the request/response shapes otherwise -
        # only ever got the channel's initial handshake and periodic
        # keep-alives, never an actual pushed update, across many real
        # attempts; Google's backend appears to only route live pushes to
        # genuinely QUIC-negotiated clients. No stdlib support for this -
        # aioquic is a real added dependency, justified only because both
        # cheaper alternatives were tried first and neither worked.
        parsed = urllib.parse.urlsplit(_CHANNEL_URL)
        host, port = parsed.hostname, parsed.port or 443
        path = (f"{parsed.path}?VER=8&gsessionid={self._gsessionid}&key={_CHANNEL_KEY}&RID=rpc"
                f"&SID={self._channel_sid}&AID=0&CI=0&TYPE=xmlhttp&zx={_random_zx()}&t=1")

        canonic_id = self._canonic_id  # captured for the nested class below - it has its own `self`
        target = canonic_id.encode()
        cookie_header = "; ".join(f"{c.name}={c.value}" for c in self._session.cookies)
        # _auth_headers alone (Authorization/Origin/X-Goog-AuthUser) is what
        # the other calls in this module send, and it's enough for those -
        # but this is the one request that's supposed to receive an actual
        # server-initiated push rather than just a synchronous reply, and a
        # real capture's equivalent request carried a full normal-browser
        # header set (User-Agent, Referer, Sec-Fetch-*, ...) that this was
        # missing entirely. Unconfirmed whether that's actually why no push
        # ever arrived here - but it's a real, concrete gap versus the
        # capture that's cheap to close, unlike the alternatives already
        # ruled out (HTTP/2, plain HTTP/1.1).
        request_headers = [
            (b":method", b"GET"),
            (b":scheme", b"https"),
            (b":authority", host.encode()),
            (b":path", path.encode()),
            (b"cookie", cookie_header.encode()),
            (b"user-agent", _BROWSER_USER_AGENT.encode()),
            (b"accept", b"*/*"),
            (b"accept-language", b"en-US,en;q=0.9"),
            (b"referer", f"{_ORIGIN}/".encode()),
            (b"sec-fetch-dest", b"empty"),
            (b"sec-fetch-mode", b"cors"),
            (b"sec-fetch-site", b"same-site"),
        ] + [(k.lower().encode(), v.encode()) for k, v in _auth_headers(self._sapisid).items()]

        chunks: list[bytes] = []
        result: dict | None = None

        class _H3Client(QuicConnectionProtocol):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.h3 = H3Connection(self._quic)
                self.done = asyncio.Event()

            def quic_event_received(self, event):
                # Unlike the rest of this module, this runs as a callback
                # from inside asyncio's own datagram-received handling, not
                # from code this class's own try/except can see - anything
                # raised here becomes an "exception in callback" logged by
                # asyncio itself instead of propagating to _run(), and
                # self.done never gets set, so the caller just waits out the
                # full deadline instead of failing fast (confirmed: exactly
                # this, from a coincidental substring match on non-protobuf
                # bytes that _find_matching_blob's plain substring search
                # doesn't and can't rule out ahead of parsing it for real).
                nonlocal result
                try:
                    self._handle_h3_events(event)
                except Exception:
                    logger.exception("Live device info read failed for %s (non-fatal)", canonic_id)
                    self.done.set()

            def _handle_h3_events(self, event):
                nonlocal result
                for h3_event in self.h3.handle_event(event):
                    if isinstance(h3_event, DataReceived):
                        chunks.append(h3_event.data)
                        text_so_far = b"".join(chunks).decode("utf-8", "replace")
                        for envelope in _parse_chunked(text_so_far):
                            blob = _find_matching_blob(envelope, target)
                            if blob is not None:
                                result = parse_live_info(blob)
                                self.done.set()
                                return
                        if h3_event.stream_ended:
                            self.done.set()
                    elif isinstance(h3_event, HeadersReceived) and h3_event.stream_ended:
                        self.done.set()

        # verify_mode overridable (see _QUIC_VERIFY_MODE) only so tests can
        # run a local self-signed server - always the real, verifying
        # default outside of that.
        config = QuicConfiguration(is_client=True, alpn_protocols=["h3"])
        config.verify_mode = _QUIC_VERIFY_MODE

        async def _run() -> dict | None:
            async with quic_connect(host, port, configuration=config, create_protocol=_H3Client) as protocol:
                stream_id = protocol._quic.get_next_available_stream_id()
                protocol.h3.send_headers(stream_id, request_headers, end_stream=True)
                protocol.transmit()
                await protocol.done.wait()
            return result

        try:
            return await asyncio.wait_for(_run(), timeout=self._deadline_s)
        except TimeoutError:
            # A match found right as the deadline hit still counts - only
            # give up empty-handed if nothing was ever found.
            return result

    def wait_for_update(self, timeout: float = 15.0) -> dict | None:
        # The background listener (started in __init__, already running by
        # the time this is called, with a head start on whatever gap there
        # was between construction and this call) has its own deadline based
        # on the channel's declared long-poll duration - wait at least that
        # long. +10s beyond that on top: _listen's own network timeout isn't
        # a perfectly tight bound (connect time, TLS, and general timing
        # imprecision all sit outside what requests' timeout= actually
        # measures), so without slack here this could give up and log a
        # confusing "listener hadn't finished" right as _listen was about to
        # report its own, more informative "no update" result (confirmed
        # live: observed exactly that race).
        wait_s = max(timeout, self._deadline_s) + 10
        try:
            return self._result.get(timeout=wait_s)
        except queue.Empty:
            logger.warning("Live info listener for %s hadn't finished after %ss - giving up anyway",
                            self._canonic_id, wait_s)
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
                "re-run Sign in with Google once to capture them"
            )
            return None
        page_text = _fetch_fmd_page(session)
        tokens = _get_page_tokens(page_text)
        if tokens is None:
            logger.warning("Could not read the Find My Device page's session tokens - skipping live info")
            return None
        token = _random_token()
        gsessionid = _choose_server(session, sapisid, token)
        if not gsessionid:
            logger.warning("chooseServer call failed - skipping live info for %s", canonic_id)
            return None
        channel_sid, server_timeout_s = _open_channel(session, sapisid, gsessionid, token)
        if not channel_sid:
            logger.warning("Could not open the live info channel - skipping live info for %s", canonic_id)
            return None

        # Start listening on the channel *before* asking Google to push
        # anything to it - a real capture showed the website's own long-poll
        # GET starts right after opening the channel, before it triggers
        # SWJ22b below, and this project's LiveInfoWatch does the same in
        # its own background thread as soon as it's constructed (see its
        # docstring). Getting this order backwards means the update can
        # arrive and be gone before anything is listening for it.
        watch = LiveInfoWatch(session, sapisid, gsessionid, channel_sid, canonic_id, server_timeout_s)

        # Opening the channel above only sets up somewhere to *receive* a
        # push - it doesn't cause Google to ever send one. SWJ22b is what
        # actually asks the backend to ping this phone and route its answer
        # to this channel; without it the watch just listens to silence
        # (confirmed live: a channel that opened cleanly never received
        # anything across 5 consecutive real locate cycles before this).
        # Only phones have the numeric id it needs - not finding one for a
        # BLE tag is expected, not an error, so this doesn't gate the watch
        # the way the steps above do (still worth returning the watch even
        # if this fails, in case something else about the account/session
        # still makes an update arrive).
        device_numeric_id = _get_device_numeric_id(page_text, canonic_id)
        if device_numeric_id:
            if not _request_live_status(session, sapisid, tokens, device_numeric_id, canonic_id, token):
                logger.warning("Live status request (SWJ22b) failed for %s - waiting anyway", canonic_id)
        else:
            logger.info("No numeric device id found for %s (BLE tag, or not a phone) - "
                        "waiting on the channel without an explicit trigger", canonic_id)

        return watch
    except Exception:
        logger.exception("Failed to open a live info watch for %s (non-fatal)", canonic_id)
        return None
