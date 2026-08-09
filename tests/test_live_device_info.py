"""Unit tests for Auth/live_device_info.py - no real network calls. The
sample blobs below are exactly what this session's HAR-based investigation
decoded from a live account's real-time push channel (see the module
docstring), used here as fixed, deterministic fixtures (stored as raw hex,
generated straight from the original captured base64 - see git history if
these ever need regenerating from scratch)."""

import asyncio
import base64
import datetime
import hashlib
import ipaddress
import json
import socket
import ssl
import time

import requests
from aioquic.asyncio import serve as quic_serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from Auth import live_device_info as ldi

# A phone update captured *before* wifi/battery arrived (locate still in
# flight) - has a device-info section (field 26) but no field 30/32 at all.
PHONE_BLOB_BEFORE_WIFI_BATTERY = bytes.fromhex(
    "0a3c08011210547545515a4550334431686342772e2e1a105756374c36737a4d5847696667672e2e2a120a10547545515a4550334431686342772e2e30011ab3040a380a3408d0e783b3c0c3ba923d12280a260a2436376164623965392d303030302d326538342d393262662d313432323362626530376436100112070a03fa0100100112070a0382020010011ac903d201fe020ad8020a260a2436376164623965392d303030302d326538342d393262662d3134323233626265303764361286010a0b4d6920313054204c69746510144a710a6f68747470733a2f2f666f6e74732e677374617469632e636f6d2f732f692f676f6f676c656d6174657269616c69636f6e732f736d61727470686f6e652f7631342f676d5f677265792d323464702f32782f676d5f736d61727470686f6e655f676d5f677265795f323464702e706e67580370025a060801280130019a014e0a3c20396c07cab5b9588f60da1f09c2b9d04f79f059c82e6023e98f6ecbff5b7cbb6b94dfcbbca2a5796324ee835e104a9e92e773e9bf79b64611478ccc1802420c08dfd5ced30610d983f69602a201065869616f6d69aa010f6c696e656167655f6761756775696eb00101c0010aca0110cf18dfd59f52f18e45d4750cba7c6bf78a020b08add1c9bd061099de99429202094d323030374a3137471a210a1953616d792e616e746f6e69617a7a6940676d61696c2e636f6d100118012001a202440a3852340a2d122981fade50269a0f9d18961adb2db764238436095b5fc8d9bac063923687d1cbb713bcd6d423b329f07d18011d8fc2c341580118032206088a94d8d3062a0b4d6920313054204c697465620c08e394d8d30610a5d7addb012a06c18b84c4e812"
)

# A phone update carrying live WiFi + battery (confirmed against a real
# account: wifi "Mordor", battery 95%).
PHONE_BLOB_WITH_WIFI_BATTERY = bytes.fromhex(
    "0a281210547545515a4550334431686342772e2e2a120a10547545515a4550334431686342772e2e30011ac0010a380a3408d0e783b3c0c3ba923d12280a260a2436376164623965392d303030302d326538342d393262662d31343232336262653037643610011a777001f2010c0a08224d6f72646f72221004820202085f8a0212080010401800200028003000380040004800a2024612340a204ffbdff15bd5d921bbb016cc8cb8b00f1cf555e2cf8a598fd9b5d39a8cf773a31210bd1f267f27f2d39b3ef851bc8232e8781801220c08e394d8d3061080d281b901c00202620b08e594d8d30610e88ab26c2200"
)

# A BLE tag (Chipolo) update - no WiFi radio, no battery reporting, its
# device-info section is nested completely differently (field 4, not 3).
CHIPOLO_BLOB = bytes.fromhex(
    "0a3c080112106464335651306a377644526748772e2e1a105756374c36737a4d5847696667672e2e2a120a106464335651306a377644526748772e2e30011ae8070a2c10021a280a260a2436376164626434392d303030302d323339322d623536332d35383234323963363439663012070a03f20100100112070a03fa0100100112070a03820200100122fc040a8f040a260a2436376164626434392d303030302d323339322d623536332d3538323432396336343966301294010a11436869706f6c6f204f4e4520506f696e7410014a7d0a7968747470733a2f2f6c68332e676f6f676c6575736572636f6e74656e742e636f6d2f74483879557a4a35673034765834437a6c615f566b465033546949442d4c4a596b66584335595a454679316d5a38325742543976494237746154594e515368567132365977704c43485631733642485972535959646c6310015a060801280130017a2463643061363430322d383261312d343238622d393437632d3264393038356633383838319a01ba010a3c33c76c61868ff5c2bade91426cf1a4628d915c69c07535b605df737ae6b77d547b22983d699b5399d4c13f562c2a23a6b41b749d6ca904a97bc8ca6f1802222cb4b6d156634c5319ba31d55a84f6184939b05cb22d3e4a306b8dcecd7db4b6b2befa26258cffb7449cb991bf420c08ebd5ced30610b0b290fa025a3cd8cd8b05eb04370944934eae3383503e449440d9f63e48d0298fa5fa1fad8a216053ba6a5d0174e1fa4447731ef282882bfcd86ed621dec8bf64fa36a20107436869706f6c6faa0106366564646135b00101b801d3d0c9bd06c0010aca010885e3bcc721fe9d57d201082586b79af3c99bb7fa0108b9b7bdc3c6ad631e8a020c08b2d1c9bd0610e48882c503920211436869706f6c6f204f4e4520506f696e7412451a43223f0a3552310a2a1226f20b1d32bffe7fa1523e783475bda84928804a8ea7cd700a41bf7dabe8ee3d1f2af82958cfdf18011d7ff459435803120608a184d8d30628011a210a1953616d792e616e746f6e69617a7a6940676d61696c2e636f6d1001180120012a11436869706f6c6f204f4e4520506f696e7432fa010a7968747470733a2f2f6c68332e676f6f676c6575736572636f6e74656e742e636f6d2f74483879557a4a35673034765834437a6c615f566b465033546949442d4c4a596b66584335595a454679316d5a38325742543976494237746154594e515368567132365977704c43485631733642485972535959646c634007620c08e994d8d30610999ca1e501"
)


def test_parse_live_info_extracts_wifi_and_battery():
    info = ldi.parse_live_info(PHONE_BLOB_WITH_WIFI_BATTERY)
    assert info["wifi_ssid"] == "Mordor"
    assert info["wifi_signal"] == 4
    assert info["battery_pct"] == 95
    assert "raw_extra" in info  # fields 14/33/40 - present, not yet identified


def test_parse_live_info_has_no_wifi_battery_before_they_arrive():
    # This message only has a device-info section (field 26) - no wifi/
    # battery keys yet, but its unhandled raw bytes still surface via
    # raw_extra rather than being silently dropped.
    info = ldi.parse_live_info(PHONE_BLOB_BEFORE_WIFI_BATTERY)
    assert "wifi_ssid" not in info
    assert "battery_pct" not in info
    assert "raw_extra" in info


def test_parse_live_info_returns_none_for_a_ble_tag():
    # Chipolo has no phone-style status section at all (nested under field 4
    # instead of field 3) - no WiFi radio, no battery to report.
    assert ldi.parse_live_info(CHIPOLO_BLOB) is None


def test_sapisid_hash_matches_the_documented_scheme():
    result = ldi._sapisid_hash("some-sapisid-value", "https://www.google.com", timestamp=1786120802)
    expected_digest = hashlib.sha1(b"1786120802 some-sapisid-value https://www.google.com").hexdigest()
    assert result == f"1786120802_{expected_digest}"


def test_build_session_returns_none_without_cached_cookies(monkeypatch):
    monkeypatch.setattr(ldi, "get_cached_value", lambda name: None)
    session, sapisid = ldi._build_session()
    assert session is None
    assert sapisid is None


def test_build_session_extracts_sapisid_from_cached_cookies(monkeypatch):
    cookies = [
        {"name": "AEC", "value": "aec-value", "domain": ".google.com", "path": "/"},
        {"name": "SAPISID", "value": "the-sapisid", "domain": ".google.com", "path": "/"},
    ]
    monkeypatch.setattr(ldi, "get_cached_value", lambda name: cookies if name == "web_session_cookies" else None)
    session, sapisid = ldi._build_session()
    assert sapisid == "the-sapisid"
    assert session.cookies.get("AEC") == "aec-value"
    # Without a browser-like UA, Google serves something other than the real
    # page and _get_page_tokens can't find window.WIZ_global_data in it - see
    # the comment above _BROWSER_USER_AGENT.
    assert session.headers["User-Agent"] == ldi._BROWSER_USER_AGENT
    assert "python-requests" not in session.headers["User-Agent"]


def test_find_matching_blob_locates_the_right_base64_string():
    haystack = ["unrelated", base64.b64encode(b"hello-canonic-id-123").decode(), "also-unrelated"]
    found = ldi._find_matching_blob(haystack, b"canonic-id-123")
    assert found == b"hello-canonic-id-123"
    assert ldi._find_matching_blob(haystack, b"not-present") is None


def test_parse_chunked_reads_repeated_length_prefixed_json_blocks():
    text = "8\n[1,2,3]9\n[4,5,6]a"  # trailing junk after the last valid chunk is ignored
    assert ldi._parse_chunked(text) == [[1, 2, 3], [4, 5, 6]]


def test_open_watch_returns_none_when_no_cookies_cached(monkeypatch):
    monkeypatch.setattr(ldi, "get_cached_value", lambda name: None)
    assert ldi.open_watch("some-canonic-id") is None


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self, text):
        self._text = text

    def get(self, *args, **kwargs):
        return _FakeResponse(self._text)

    def post(self, *args, **kwargs):
        return _FakeResponse(self._text)


def _wiz_page(fdrfje_literal: str) -> str:
    return (
        '<script nonce="x">var AF_initDataKeys = [];window.WIZ_global_data = '
        '{"AfY8Hf":true,"EP1ykd":["/_/*"],"FdrFJe":' + fdrfje_literal + ','
        '"HiPsbb":1,"cfb2h":"prod_build_label","Im6cmf":"/android/find/_",'
        '"SNlM0e":"the-csrf-token"};</script>'
    )


def test_get_page_tokens_handles_fdrfje_as_a_quoted_string():
    # This is the actual format Google sends (confirmed both live and in the
    # original HAR capture this module was built from) - large session ids
    # don't fit a JS safe integer, so Google stringifies the field.
    tokens = ldi._get_page_tokens(_wiz_page('"975547745069287805"'))
    assert tokens == {"FdrFJe": "975547745069287805", "cfb2h": "prod_build_label", "SNlM0e": "the-csrf-token"}


def test_get_page_tokens_still_handles_fdrfje_as_a_bare_number():
    tokens = ldi._get_page_tokens(_wiz_page("975547745069287805"))
    assert tokens["FdrFJe"] == "975547745069287805"


def test_get_page_tokens_handles_a_negative_fdrfje():
    tokens = ldi._get_page_tokens(_wiz_page('"-1529750813986083965"'))
    assert tokens["FdrFJe"] == "-1529750813986083965"


def test_get_page_tokens_returns_none_when_a_field_is_missing():
    assert ldi._get_page_tokens("<html>not the page we expected, no WIZ data here</html>") is None


def test_decode_maybe_base64_json_handles_plain_json():
    # Observed live while debugging this: chooseServer sometimes answers
    # with plain JSON directly, not base64 - see _decode_maybe_base64_json's
    # docstring for why getting the order backwards is dangerous, not just
    # slower.
    text = '["FAJZYfRdmLpXX6JU41CvSloT_JH7m3hrN0koKkc6XPo",3,null,"1786226149904933","1786226149904995"]'
    assert ldi._decode_maybe_base64_json(text)[0] == "FAJZYfRdmLpXX6JU41CvSloT_JH7m3hrN0koKkc6XPo"


def test_decode_maybe_base64_json_handles_base64(monkeypatch):
    # This is the format the original HAR capture had.
    text = "WyJDaGk1cEZHWmZkVDM4V2hUM3Y4MTBzWndBa044ZVN4OVdTdHZNOS1ybFhJIiwzLG51bGwsIjE3ODYxMjA4MDI0NzQ4MDMiLCIxNzg2MTIwODAyNDc0OTM3Il0="
    assert ldi._decode_maybe_base64_json(text)[0] == "Chi5pFGZfdT38WhT3v810sZwAkN8eSx9WStvM9-rlXI"


def test_open_channel_extracts_sid_and_server_timeout():
    # Real shape from a live capture: [[0,["c","<sid>","",8,14,30000]]] - the
    # trailing 30000 is the channel's own long-poll duration in ms.
    session = _FakeSession('51\n[[0,["c","1dM1leahd1pvOO0anqReVg","",8,14,30000]]]')
    channel_sid, server_timeout_s = ldi._open_channel(session, "sapisid", "gsessionid", "token")
    assert channel_sid == "1dM1leahd1pvOO0anqReVg"
    assert server_timeout_s == 30.0


def test_open_channel_returns_none_none_when_unparseable():
    session = _FakeSession("not a valid chunked response at all")
    assert ldi._open_channel(session, "sapisid", "gsessionid", "token") == (None, None)


def test_live_info_watch_uses_the_server_declared_timeout_for_its_listener(monkeypatch):
    # LiveInfoWatch starts listening at construction time, not when
    # wait_for_update() is later called (see its docstring for why) - so its
    # read deadline can only come from the channel's own declared long-poll
    # duration, computed synchronously in __init__ before the background
    # listener thread (which this doesn't need to wait for) ever runs.
    # _CHANNEL_URL points somewhere nothing is listening so that thread fails
    # fast instead of trying real network access.
    monkeypatch.setattr(ldi, "_CHANNEL_URL", "http://127.0.0.1:1/channel")
    watch = ldi.LiveInfoWatch(requests.Session(), "sapisid", "gsessionid", "channel_sid", "canonic-id",
                               server_timeout_s=30.0)
    assert watch._deadline_s == 35.0  # 30 + 5s slack


def test_live_info_watch_falls_back_to_a_default_when_server_timeout_unknown(monkeypatch):
    monkeypatch.setattr(ldi, "_CHANNEL_URL", "http://127.0.0.1:1/channel")
    watch = ldi.LiveInfoWatch(requests.Session(), "sapisid", "gsessionid", "channel_sid", "canonic-id",
                               server_timeout_s=None)
    assert watch._deadline_s == 20.0  # 15s default + 5s slack


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _self_signed_cert(tmp_path):
    """A throwaway cert for 127.0.0.1, good for an hour - only ever used to
    let the tests below run a real local HTTP/3 server; LiveInfoWatch itself
    always verifies real certs (see _QUIC_VERIFY_MODE, only ever overridden
    here)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                        critical=False)
        .sign(key, hashes.SHA256())
    )
    certfile, keyfile = tmp_path / "cert.pem", tmp_path / "key.pem"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return str(certfile), str(keyfile)


async def _run_local_h3_server(certfile, keyfile, port, on_headers_received):
    """Real local HTTP/3/QUIC server (127.0.0.1 only, not a real network
    call) - the two tests below need actual H3-stream timing to verify
    LiveInfoWatch's own asyncio.wait_for deadline against a real asyncio
    server, the same way the equivalent HTTP/1.1 version of these tests
    (see git history) needed a real local HTTP server rather than a mocked
    session.get(): several supposedly-reliable timeout mechanisms turned out
    not to be, and only a real server/client round trip caught it each time.
    on_headers_received(h3_conn, stream_id) does the actual response -
    scheduled as its own task so it can use asyncio.sleep for timing without
    blocking new connections."""
    class ServerProtocol(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.h3 = H3Connection(self._quic)

        def quic_event_received(self, event):
            for h3_event in self.h3.handle_event(event):
                if isinstance(h3_event, HeadersReceived):
                    asyncio.ensure_future(on_headers_received(self, h3_event.stream_id))

    config = QuicConfiguration(is_client=False, alpn_protocols=["h3"])
    config.load_cert_chain(certfile, keyfile)
    return await quic_serve("127.0.0.1", port, configuration=config, create_protocol=ServerProtocol)


def _use_local_h3_channel(monkeypatch, port):
    monkeypatch.setattr(ldi, "_CHANNEL_URL", f"https://127.0.0.1:{port}/channel")
    monkeypatch.setattr(ldi, "_QUIC_VERIFY_MODE", ssl.CERT_NONE)


async def test_wait_for_update_does_not_hang_past_its_deadline_on_endless_heartbeats(monkeypatch, tmp_path):
    # Reproduces a real failure seen while debugging this: a channel that
    # never stops sending keep-alives (and never sends a matching update)
    # ran for 270s against one early, unfixed version of this instead of
    # respecting its ~7s deadline. This server would happily stream
    # heartbeats for 30s straight; the test only passes if wait_for_update
    # gives up long before that.
    async def send_heartbeats_forever(protocol, stream_id):
        protocol.h3.send_headers(stream_id, [(b":status", b"200")])
        protocol.transmit()
        for _ in range(60):  # 60 * 0.5s = 30s worth, way past this test's ~7s deadline
            protocol.h3.send_data(stream_id, b"8\n[[9,[]]]\n", end_stream=False)
            protocol.transmit()
            await asyncio.sleep(0.5)

    certfile, keyfile = _self_signed_cert(tmp_path)
    port = _free_udp_port()
    server = await _run_local_h3_server(certfile, keyfile, port, send_heartbeats_forever)
    _use_local_h3_channel(monkeypatch, port)
    try:
        watch = ldi.LiveInfoWatch(requests.Session(), "sapisid", "gsessionid", "channel_sid", "some-canonic-id",
                                   server_timeout_s=2.0)
        t0 = time.monotonic()
        result = await asyncio.to_thread(watch.wait_for_update, timeout=1.0)  # deadline = max(1, 2) + 5 = 7s
        elapsed = time.monotonic() - t0
    finally:
        server.close()

    assert result is None
    assert elapsed < 15  # nowhere near the 30s of heartbeats the server was willing to send


async def test_wait_for_update_returns_as_soon_as_a_match_arrives_even_if_the_stream_stays_open(monkeypatch, tmp_path):
    # The connection can easily stay open well past the moment the real
    # update arrives (the server above does exactly this in practice) -
    # checking for a match only once the stream ends would throw away data
    # already in hand instead of returning with it immediately.
    canonic_id = "some-canonic-id"
    matching_blob_b64 = base64.b64encode(b"prefix-" + canonic_id.encode() + b"-suffix").decode()

    async def send_heartbeat_then_match_then_stay_open(protocol, stream_id):
        protocol.h3.send_headers(stream_id, [(b":status", b"200")])
        protocol.h3.send_data(stream_id, b"8\n[[9,[]]]\n", end_stream=False)  # one heartbeat first
        protocol.transmit()
        await asyncio.sleep(0.3)
        envelope = f'[[9,["{matching_blob_b64}"]]]'
        protocol.h3.send_data(stream_id, f"{len(envelope)}\n{envelope}\n".encode(), end_stream=False)
        protocol.transmit()
        await asyncio.sleep(10)  # server keeps the connection open long after - must not be waited out
        protocol.h3.send_data(stream_id, b"", end_stream=True)
        protocol.transmit()

    certfile, keyfile = _self_signed_cert(tmp_path)
    port = _free_udp_port()
    server = await _run_local_h3_server(certfile, keyfile, port, send_heartbeat_then_match_then_stay_open)
    _use_local_h3_channel(monkeypatch, port)
    try:
        watch = ldi.LiveInfoWatch(requests.Session(), "sapisid", "gsessionid", "channel_sid", canonic_id,
                                   server_timeout_s=25.0)
        t0 = time.monotonic()
        await asyncio.to_thread(watch.wait_for_update, timeout=1.0)  # deadline = max(1, 25) + 5 = 30s
        elapsed = time.monotonic() - t0
    finally:
        server.close()

    assert elapsed < 5  # returned right after the match arrived (~0.3s in), not near the 30s deadline


# A trimmed excerpt of the actual AF_initDataCallback shape a real page capture
# had - the device list pairs each phone with a numeric id right before its
# canonic_id, unrelated surrounding data included to prove the regex doesn't
# need the full page structure to find it.
_DEVICE_LIST_PAGE_EXCERPT = (
    "AF_initDataCallback({key: 'ds:0', hash: '1', data:[null,[[[["
    '"4405903741562188752",[["67adb9e9-0000-2e84-92bf-14223bbe07d6"]]],'
    '"Mi 10T Lite"],[null,2,[["67adbd49-0000-2392-b563-582429c649f0"]]],'
    '"Chipolo ONE Point"]],null]});'
)


def test_get_device_numeric_id_finds_a_phones_id():
    numeric_id = ldi._get_device_numeric_id(_DEVICE_LIST_PAGE_EXCERPT, "67adb9e9-0000-2e84-92bf-14223bbe07d6")
    assert numeric_id == "4405903741562188752"


def test_get_device_numeric_id_returns_none_for_a_ble_tag():
    # Confirmed against a real capture: tags don't get a numeric id in this
    # position at all - None here is the expected, normal case, not a
    # parse failure (see _get_device_numeric_id's docstring).
    numeric_id = ldi._get_device_numeric_id(_DEVICE_LIST_PAGE_EXCERPT, "67adbd49-0000-2392-b563-582429c649f0")
    assert numeric_id is None


def test_get_device_numeric_id_returns_none_when_canonic_id_absent():
    assert ldi._get_device_numeric_id(_DEVICE_LIST_PAGE_EXCERPT, "some-other-canonic-id") is None


def test_request_live_status_sends_the_expected_payload_shape(monkeypatch):
    captured = {}

    class _FakeLiveStatusResponse:
        text = '[["wrb.fr","SWJ22b","[1]",null,null,null,"generic"]]'

        def raise_for_status(self):
            pass

    class _RecordingSession:
        def post(self, url, params=None, data=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["data"] = data
            return _FakeLiveStatusResponse()

    monkeypatch.setattr(ldi, "_random_token", lambda: "fake-session-token")

    page_tokens = {"FdrFJe": "-1529750813986083965", "cfb2h": "prod_build_label", "SNlM0e": "the-csrf-token"}
    ok = ldi._request_live_status(
        _RecordingSession(), "sapisid", page_tokens,
        device_numeric_id="4405903741562188752", canonic_id="67adb9e9-0000-2e84-92bf-14223bbe07d6",
        channel_token="the-channel-token",
    )

    assert ok is True
    assert captured["url"] == ldi._LIVE_STATUS_URL
    assert captured["params"]["rpcids"] == "SWJ22b"
    assert captured["params"]["f.sid"] == "-1529750813986083965"
    assert captured["params"]["bl"] == "prod_build_label"
    assert captured["data"]["at"] == "the-csrf-token"

    # The RPC args are themselves JSON-encoded as a string inside the outer
    # f.req array (Google's batchexecute framing) - decode that inner layer
    # to check the actual payload shape matches the real capture's.
    outer = json.loads(captured["data"]["f.req"])
    inner = json.loads(outer[0][0][1])
    assert inner[0] == [["4405903741562188752", [["67adb9e9-0000-2e84-92bf-14223bbe07d6"]]], 1]
    assert inner[2][1] == "the-channel-token"  # channel_token, in the position the real capture had it
    assert inner[2][4] == ["the-channel-token"]  # ...and echoed again here, same as the real capture


def test_request_live_status_returns_false_on_an_unexpected_response(monkeypatch):
    class _FakeResponse:
        text = "not the response we expected"

        def raise_for_status(self):
            pass

    class _FakeSessionForPost:
        def post(self, *args, **kwargs):
            return _FakeResponse()

    ok = ldi._request_live_status(
        _FakeSessionForPost(), "sapisid", {}, device_numeric_id="123", canonic_id="some-id",
        channel_token="token",
    )
    assert ok is False
