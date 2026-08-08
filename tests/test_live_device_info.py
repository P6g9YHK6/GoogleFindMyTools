"""Unit tests for Auth/live_device_info.py - no real network calls. The
sample blobs below are exactly what this session's HAR-based investigation
decoded from a live account's real-time push channel (see the module
docstring), used here as fixed, deterministic fixtures (stored as raw hex,
generated straight from the original captured base64 - see git history if
these ever need regenerating from scratch)."""

import base64
import hashlib

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
