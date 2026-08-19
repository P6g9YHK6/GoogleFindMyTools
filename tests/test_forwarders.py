"""Pure-logic unit tests for the forwarders package - no HTTP involved."""

from webui.forwarders import PRESETS, blank_endpoint


def test_presets_cover_traccar_and_phonetrack_and_custom():
    assert set(PRESETS) == {
        "custom", "traccar", "phonetrack",
        "phonetrack_osmand", "phonetrack_gpslogger", "phonetrack_locusmap",
        "phonetrack_ulogger", "phonetrack_owntracks", "phonetrack_overland",
    }
    for preset in PRESETS.values():
        assert preset["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE")
        assert isinstance(preset["headers"], dict)
        assert "params" not in preset  # query params live in the URL itself now
        assert "variables" not in preset  # no more "Custom variables" table to pre-fill


def test_traccar_preset_templates_the_fix_as_query_params_baked_into_the_url():
    preset = PRESETS["traccar"]
    assert "lat={{latitude}}" in preset["url"]
    assert "lon={{longitude}}" in preset["url"]
    # No custom-variables table left to fill a device_id in from - a literal
    # placeholder is baked into the URL for the user to hand-edit instead.
    assert "id=REPLACE_WITH_YOUR_DEVICE_ID" in preset["url"]


def test_phonetrack_preset_bakes_device_alias_and_query_params_into_the_url():
    # {{device_alias}}, not {{device_name}} - PhoneTrack's session id wants
    # the local nickname you control, not the Google account's fixed name
    # (which may be cryptic and isn't yours to edit here).
    preset = PRESETS["phonetrack"]
    assert "{{device_alias}}" in preset["url"]
    assert "lat={{latitude}}" in preset["url"]


def test_phonetrack_preset_sets_useragent_so_it_does_not_default_to_unknown():
    """logGet() (PhoneTrack's LogController.php) defaults its own per-point
    useragent field to the literal "unknown GET logger" when the query
    string leaves it out - baked in here instead. Only "phonetrack" itself
    (not its OsmAnd/GpsLogger/etc siblings) even reads this param - see
    this preset's own hint."""
    assert "useragent=gfmtForwarding{{type}}" in PRESETS["phonetrack"]["url"]


def test_phonetrack_locusmap_and_ulogger_presets_use_time_not_timestamp():
    # Unlike PhoneTrack's other GET endpoints, these two use ?time= - worth
    # pinning since it looks like a typo next to the others.
    assert "time={{google_timestamp}}" in PRESETS["phonetrack_locusmap"]["url"]
    assert "timestamp=" not in PRESETS["phonetrack_locusmap"]["url"]
    assert "time={{google_timestamp}}" in PRESETS["phonetrack_ulogger"]["url"]
    assert "action=addpos" in PRESETS["phonetrack_ulogger"]["url"]


def test_phonetrack_owntracks_and_overland_presets_render_to_valid_json():
    import json

    from webui.forwarders.custom import _render, build_context

    location = {"latitude": 47.1, "longitude": 8.5, "altitude": 400.0, "accuracy": 10.0, "time": 1700000000}
    ctx = build_context({}, location, "MyPhone")

    for key in ("phonetrack_owntracks", "phonetrack_overland"):
        preset = PRESETS[key]
        assert preset["body_type"] == "json"
        rendered = json.loads(_render(preset["body"], ctx))
        assert rendered  # parses and isn't empty


def test_blank_endpoint_starts_from_the_custom_preset():
    blank = blank_endpoint("*/5 * * * *")
    assert blank["cron"] == "*/5 * * * *"
    assert blank["type"] == "custom"
    assert blank["method"] == "GET"
    assert blank["url"] == ""
    assert "params" not in blank
    assert "variables" not in blank


def test_forward_to_custom_renders_templated_url_and_its_query_string(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET",
        "url": "http://traccar.local:5055/?id=104&lat={{latitude}}&lon={{longitude}}",
        "headers": {},
        "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    assert custom.forward_to_custom(endpoint_cfg, location, "My Phone") is True
    assert captured["method"] == "GET"
    assert captured["url"] == "http://traccar.local:5055/?id=104&lat=1.0&lon=2.0"
    # No `params=` kwarg at all - httpx parses the query string embedded in
    # the URL itself. (Passing params= used to silently replace/wipe the
    # URL's own query string entirely, even with an empty dict.)
    assert "params" not in captured["kwargs"]


def test_forward_to_custom_fills_response_out_when_given(monkeypatch):
    from webui.forwarders import custom

    class FakeResponse:
        status_code = 200
        text = '{"done":1}'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(custom.httpx, "request", lambda method, url, **kwargs: FakeResponse())

    endpoint_cfg = {"method": "GET", "url": "http://x/", "headers": {}, "body_type": "none", "body": ""}
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    response_out = {}
    assert custom.forward_to_custom(endpoint_cfg, location, "My Phone", response_out=response_out) is True
    assert response_out == {"status_code": 200, "body": '{"done":1}'}


def test_forward_to_custom_captures_the_response_body_before_raising_for_an_http_error(monkeypatch):
    """A non-2xx response's body is exactly what's most useful for
    debugging - captured before raise_for_status() turns it into the
    caller's "error: ..." status, not lost along with the exception."""
    import httpx

    from webui.forwarders import custom

    class FakeResponse:
        status_code = 500
        text = "Internal Server Error"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("500", request=None, response=self)

    monkeypatch.setattr(custom.httpx, "request", lambda method, url, **kwargs: FakeResponse())

    endpoint_cfg = {"method": "GET", "url": "http://x/", "headers": {}, "body_type": "none", "body": ""}
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    response_out = {}
    try:
        custom.forward_to_custom(endpoint_cfg, location, "My Phone", response_out=response_out)
    except httpx.HTTPStatusError:
        pass
    assert response_out == {"status_code": 500, "body": "Internal Server Error"}


def test_forward_to_custom_truncates_a_very_long_response_body(monkeypatch):
    from webui.forwarders import custom

    class FakeResponse:
        status_code = 200
        text = "x" * (custom.MAX_LOGGED_RESPONSE_CHARS + 500)

        def raise_for_status(self):
            pass

    monkeypatch.setattr(custom.httpx, "request", lambda method, url, **kwargs: FakeResponse())

    endpoint_cfg = {"method": "GET", "url": "http://x/", "headers": {}, "body_type": "none", "body": ""}
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    response_out = {}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone", response_out=response_out)
    assert response_out["body"].endswith("... (truncated)")
    assert len(response_out["body"]) == custom.MAX_LOGGED_RESPONSE_CHARS + len("... (truncated)")


def test_forward_to_custom_leaves_unresolved_variables_visible(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "http://x/?token={{typo_var}}",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "http://x/?token={{typo_var}}"  # left as-is, not silently dropped


def test_forward_to_custom_still_resolves_a_legacy_variables_dict(monkeypatch):
    """No UI writes "variables" anymore (see webui/forwarders/presets.py),
    but an endpoint saved before that change may still have one (e.g. a
    Traccar endpoint's device_id) - it must keep resolving."""
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "http://traccar.local/?id={{device_id}}",
        "headers": {}, "body_type": "none", "body": "", "variables": {"device_id": "104"},
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "http://traccar.local/?id=104"


def test_forward_to_custom_device_name_is_not_overridable(monkeypatch):
    """A stray "device_name" key on an endpoint (e.g. left over from an old
    config) must not change what {{device_name}}/{{device_alias}} resolve
    to - neither is overridable per endpoint - see webui/forwarders/
    custom.py's build_context(). They're allowed to resolve to two
    different values now (the Google account's real name vs. the local
    nickname - see webui/scheduler.py), just not ones an endpoint can set."""
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "https://nc.local/x/{{device_name}}/{{device_alias}}",
        "headers": {}, "body_type": "none", "body": "", "device_name": "phone1",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "Pixel 8", "My Phone")
    assert captured["url"] == "https://nc.local/x/Pixel 8/My Phone"


def test_forward_to_custom_device_alias_falls_back_to_device_name(monkeypatch):
    """Callers that only ever have one name to give (older code, most of the
    tests below) still get that same value for both tokens - only callers
    that explicitly pass a second, different device_alias see a split."""
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "https://nc.local/x/{{device_name}}/{{device_alias}}",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "https://nc.local/x/My Phone/My Phone"


def test_build_context_includes_tracker_id():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    ctx = build_context({}, location, "My Phone", tracker_id="abc-123")
    assert ctx["tracker_id"] == "abc-123"


def test_build_context_tracker_id_defaults_to_blank_when_not_passed():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    ctx = build_context({}, location, "My Phone")
    assert ctx["tracker_id"] == ""


def test_forward_to_custom_substitutes_tracker_id(monkeypatch):
    """{{tracker_id}} used to be offered as a Variables chip (see
    presets.py's BUILTIN_VARIABLES_FROM_APP) without build_context() ever
    actually setting it - a request built with it in the URL silently went
    out to the literal string "{{tracker_id}}" forever, with no error or
    log anywhere."""
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "https://svc.example/{{tracker_id}}/update",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone", tracker_id="canonic-abc-123")
    assert captured["url"] == "https://svc.example/canonic-abc-123/update"


def test_build_context_flattens_named_device_meta_fields():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    device_meta = {"manufacturer": "Chipolo", "model": "ONE Point", "type": "Beacon", "image_url": "https://x/p.png"}
    ctx = build_context({}, location, "My Phone", device_meta=device_meta)
    assert ctx["manufacturer"] == "Chipolo"
    assert ctx["model"] == "ONE Point"
    assert ctx["type"] == "Beacon"
    assert ctx["image_url"] == "https://x/p.png"


def test_build_context_prefixes_unnamed_device_meta_fields_with_label():
    """Anything in device_meta beyond the four named fields becomes
    {{label_<key>}} generically - so a field added to get_device_details
    later needs no matching change in build_context to become available."""
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    device_meta = {"carrier": "Vodafone", "imei": "123456", "a_future_field": "x"}
    ctx = build_context({}, location, "My Phone", device_meta=device_meta)
    assert ctx["label_carrier"] == "Vodafone"
    assert ctx["label_imei"] == "123456"
    assert ctx["label_a_future_field"] == "x"


def test_build_context_device_meta_fields_default_to_blank_when_not_passed():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    ctx = build_context({}, location, "My Phone")
    assert ctx["manufacturer"] == ""
    assert ctx["model"] == ""
    assert ctx["type"] == ""
    assert ctx["image_url"] == ""
    assert "label_carrier" not in ctx  # nothing to derive a label_* key from


def test_forward_to_custom_substitutes_device_meta_fields(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "https://svc.example/?mfr={{manufacturer}}&model={{model}}&imei={{label_imei}}",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    device_meta = {"manufacturer": "Chipolo", "model": "ONE Point", "imei": "354935091234567"}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone", device_meta=device_meta)
    assert captured["url"] == "https://svc.example/?mfr=Chipolo&model=ONE Point&imei=354935091234567"


def test_build_context_exposes_status_and_own_report():
    from webui.forwarders.custom import build_context

    location = {
        "is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1,
        "status": "AGGREGATED", "status_id": 3, "is_own_report": True,
    }
    ctx = build_context({}, location, "My Phone")
    assert ctx["status"] == "AGGREGATED"
    assert ctx["status_id"] == 3
    assert ctx["own_report"] is True
    assert ctx["is_semantic"] is False
    assert ctx["semantic_name"] == ""


def test_build_context_status_and_own_report_default_when_missing():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    ctx = build_context({}, location, "My Phone")
    assert ctx["status"] == ""
    assert ctx["status_id"] == ""
    assert ctx["own_report"] is False
    assert ctx["is_semantic"] is False
    assert ctx["semantic_name"] == ""


def test_build_context_exposes_is_semantic_and_semantic_name():
    from webui.forwarders.custom import build_context

    location = {
        "is_semantic": True, "semantic_name": "Nest Mini - Living Room",
        "latitude": 45.0, "longitude": 9.0, "time": 1,
        "status": "SEMANTIC", "status_id": 0, "is_own_report": True,
    }
    ctx = build_context({}, location, "My Phone")
    assert ctx["is_semantic"] is True
    assert ctx["semantic_name"] == "Nest Mini - Living Room"


def test_forward_to_custom_substitutes_status_and_own_report(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET",
        "url": "https://svc.example/?status={{status}}&status_id={{status_id}}&own={{own_report}}",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {
        "is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1,
        "status": "CROWDSOURCED", "status_id": 2, "is_own_report": False,
    }
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "https://svc.example/?status=CROWDSOURCED&status_id=2&own=False"


def test_build_context_exposes_type_id_alongside_type():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    device_meta = {"type": "Keys", "type_id": 3}
    ctx = build_context({}, location, "My Phone", device_meta=device_meta)
    assert ctx["type"] == "Keys"
    assert ctx["type_id"] == 3


def test_build_context_type_id_defaults_to_empty_string_when_missing():
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    ctx = build_context({}, location, "My Phone")
    assert ctx["type_id"] == ""


def test_build_context_type_id_zero_is_not_treated_as_missing():
    """DEVICE_TYPE_UNKNOWN is enum value 0 - a legitimate value, not an
    absent one (see custom.py's _NAMED_DEVICE_META_KEYS loop)."""
    from webui.forwarders.custom import build_context

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    device_meta = {"type": "Unknown", "type_id": 0}
    ctx = build_context({}, location, "My Phone", device_meta=device_meta)
    assert ctx["type_id"] == 0


def test_forward_to_custom_substitutes_type_id(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET",
        "url": "https://svc.example/?type={{type}}&type_id={{type_id}}",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    device_meta = {"type": "Keys", "type_id": 3}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone", device_meta=device_meta)
    assert captured["url"] == "https://svc.example/?type=Keys&type_id=3"


def test_forward_to_custom_device_name_uses_device_display_name(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "https://nc.local/x/{{device_name}}",
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "https://nc.local/x/My Phone"


def test_build_context_splits_google_and_current_timestamp(monkeypatch):
    """google_timestamp is Google's own fix time; current_timestamp is
    computed fresh at render time - they must not collapse to the same
    value just because the fix happens to be old."""
    from webui.forwarders import custom

    monkeypatch.setattr(custom.time, "time", lambda: 1800000000.0)
    location = {"latitude": 1.0, "longitude": 2.0, "time": 1700000000}
    ctx = custom.build_context({}, location, "My Phone")
    assert ctx["google_timestamp"] == 1700000000
    assert ctx["current_timestamp"] == 1800000000
    assert ctx["google_timestamp"] != ctx["current_timestamp"]


def test_build_context_keeps_fix_timestamp_resolving_to_the_google_value():
    """fix_timestamp is google_timestamp's old name - an endpoint saved
    before the rename must keep resolving it (to the same value as
    google_timestamp), not go quietly broken."""
    from webui.forwarders import custom

    location = {"latitude": 1.0, "longitude": 2.0, "time": 1700000000}
    ctx = custom.build_context({}, location, "My Phone")
    assert ctx["fix_timestamp"] == ctx["google_timestamp"] == 1700000000


def test_render_warns_on_a_variable_that_resolves_empty(caplog):
    """A token that resolves - just to "" - sends silently short of what was
    intended (e.g. {{device_alias}} on a device with no alias set). Unlike a
    typo'd token (left unresolved and visibly {{broken}} in the request),
    nothing here looks wrong without a log line."""
    from webui.forwarders.custom import _render

    with caplog.at_level("WARNING", logger="webui.forwarders.custom"):
        result = _render("id={{device_alias}}&name={{device_name}}", {"device_alias": "", "device_name": "Pixel"})
    assert result == "id=&name=Pixel"
    assert len(caplog.records) == 1
    assert "device_alias" in caplog.records[0].message


def test_render_does_not_warn_on_unresolved_or_nonempty_tokens(caplog):
    from webui.forwarders.custom import _render

    with caplog.at_level("WARNING", logger="webui.forwarders.custom"):
        result = _render("a={{typo}}&b={{ok}}", {"ok": "value"})
    assert result == "a={{typo}}&b=value"
    assert caplog.records == []


def test_forward_to_custom_skips_semantic_and_missing_coordinates():
    from webui.forwarders import custom

    endpoint_cfg = {"method": "GET", "url": "http://x/", "headers": {}, "body_type": "none", "body": ""}
    assert custom.forward_to_custom(endpoint_cfg, {"is_semantic": True}, "n") is False
    assert custom.forward_to_custom(endpoint_cfg, {"is_semantic": False, "latitude": None}, "n") is False


def test_forward_to_custom_sends_a_semantic_reading_with_mapped_coordinates(monkeypatch):
    """A SEMANTIC reading with coordinates filled in by
    webui/forwarders/semantic_map.py (see webui/scheduler.py, where that
    happens before this is ever called) sends exactly like a real fix -
    is_semantic and status="SEMANTIC" ride along unchanged."""
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET",
        "url": (
            "https://svc.example/?lat={{latitude}}&lon={{longitude}}&status={{status}}"
            "&is_semantic={{is_semantic}}&semantic_name={{semantic_name}}"
        ),
        "headers": {}, "body_type": "none", "body": "",
    }
    location = {
        "is_semantic": True, "semantic_name": "Nest Mini - Living Room",
        "latitude": 45.0, "longitude": 9.0, "time": 1,
        "status": "SEMANTIC", "status_id": 0, "accuracy": 0, "is_own_report": True,
    }
    assert custom.forward_to_custom(endpoint_cfg, location, "My Tracker") is True
    assert captured["url"] == (
        "https://svc.example/?lat=45.0&lon=9.0&status=SEMANTIC"
        "&is_semantic=True&semantic_name=Nest Mini - Living Room"
    )


def test_forward_to_custom_skips_when_url_is_blank():
    from webui.forwarders import custom

    endpoint_cfg = {"method": "GET", "url": "", "headers": {}, "body_type": "none", "body": ""}
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    assert custom.forward_to_custom(endpoint_cfg, location, "n") is False


def test_forward_to_custom_sends_a_json_body(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["content"] = kwargs.get("content")
        captured["headers"] = kwargs.get("headers")
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "POST", "url": "http://x/", "headers": {},
        "body_type": "json", "body": '{"lat": {{latitude}}}',
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "n")
    assert captured["method"] == "POST"
    assert captured["content"] == '{"lat": 1.0}'
    assert captured["headers"]["Content-Type"] == "application/json"


def test_config_store_round_trip(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    assert config_store.get_device_config("dev-1") is None
    config_store.set_device_config("dev-1", {"display_name": "X", "endpoints": []})
    assert config_store.get_device_config("dev-1") == {"display_name": "X", "endpoints": []}
    assert "dev-1" in config_store.all_devices()


def test_config_store_last_load_ok_false_for_corrupt_yaml(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    assert config_store.load() == config_store._empty()
    assert config_store.last_load_ok() is True  # no file yet - a fresh install, not a failure

    config.DEVICES_PATH.write_text("not: valid: yaml: [")
    assert config_store.load() == config_store._empty()
    assert config_store.last_load_ok() is False

    config.DEVICES_PATH.write_text("devices: {}\n")
    config_store.load()
    assert config_store.last_load_ok() is True  # flips back once the file's readable again


def test_config_store_last_load_ok_false_for_a_non_mapping_document(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    config.DEVICES_PATH.write_text("- just\n- a\n- list\n")

    assert config_store.load() == config_store._empty()
    assert config_store.last_load_ok() is False


def test_config_store_last_load_ok_true_for_a_genuinely_empty_file(tmp_path, monkeypatch):
    """An empty forwarding.yaml (0 bytes) is a legitimate "no devices yet"
    state, not a failure - only content that fails to parse as a mapping
    counts as last_load_ok() going false."""
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    config.DEVICES_PATH.write_text("")

    assert config_store.load() == {"devices": {}}
    assert config_store.last_load_ok() is True


def test_config_store_migrates_legacy_single_destination_shape(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    legacy = {
        "display_name": "X",
        "destination": "traccar",
        "traccar": {"url": "http://a", "device_id": "1"},
        "poll_interval_seconds": 120,
        "last_forward_status": "ok",
        "last_forward_time": 123,
    }
    normalized = config_store.normalize_device_config(legacy)
    assert len(normalized["endpoints"]) == 1
    ep = normalized["endpoints"][0]
    assert ep["type"] == "traccar"
    assert ep["url"].startswith("http://a/?")
    assert "lat={{latitude}}" in ep["url"]
    assert "params" not in ep
    assert ep["variables"] == {"device_id": "1"}
    assert ep["cron"] == "*/2 * * * *"
    # Runtime state doesn't live on a saved endpoint anymore either - see
    # webui/forwarders/latest_values_store.py - dropped on migration same as
    # the old nested "traccar" sub-dict below.
    assert "last_forward_status" not in ep
    assert "last_forward_time" not in ep
    assert "traccar" not in ep  # the old nested sub-dict is gone, not just unused

    none_dest = config_store.normalize_device_config({"display_name": "x", "destination": "none"})
    assert none_dest["endpoints"] == []

    already_new = {"display_name": "x", "endpoints": []}
    assert config_store.normalize_device_config(already_new) is already_new


def test_config_store_migrates_legacy_endpoints_list_shape(tmp_path, monkeypatch):
    """Endpoints already living under "endpoints" (multi-endpoint era) but
    still in the old nested traccar/phonetrack-sub-dict shape also need
    upgrading - not just the older single-destination records."""
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    legacy = {
        "display_name": "X",
        "endpoints": [
            {"type": "traccar", "traccar": {"url": "http://a/", "device_id": "1"}, "cron": "*/5 * * * *"},
            {
                "type": "phonetrack", "phonetrack": {"base_url": "http://b", "device_name": "p1"},
                "cron": "*/5 * * * *", "alias": "PT",
            },
        ],
    }
    normalized = config_store.normalize_device_config(legacy)
    traccar_ep, phonetrack_ep = normalized["endpoints"]

    assert traccar_ep["url"].startswith("http://a/?")
    assert "lat={{latitude}}" in traccar_ep["url"]
    assert traccar_ep["variables"] == {"device_id": "1"}

    assert phonetrack_ep["url"].startswith("http://b/p1?")
    assert "lat={{latitude}}" in phonetrack_ep["url"]
    assert "device_name" not in phonetrack_ep
    assert phonetrack_ep["alias"] == "PT"


def test_config_store_folds_leftover_query_params_into_the_url(tmp_path, monkeypatch):
    """An endpoint saved after the generic query-builder existed but before
    query params moved into the URL itself (a "params" dict alongside a
    plain "url") must keep sending the exact same request - see
    config_store._fold_params_into_url."""
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")

    legacy = {
        "display_name": "X",
        "endpoints": [{
            "type": "custom", "method": "GET", "url": "http://x/",
            "params": {"id": "{{device_id}}", "lat": "{{latitude}}"},
            "headers": {}, "body_type": "none", "body": "", "cron": "*/5 * * * *",
        }],
    }
    normalized = config_store.normalize_device_config(legacy)
    ep = normalized["endpoints"][0]
    assert ep["url"] == "http://x/?id={{device_id}}&lat={{latitude}}"
    assert "params" not in ep

    # Idempotent: running it again (as every load() does) is a no-op.
    assert config_store.normalize_device_config(normalized) is normalized

    # A URL that already has its own querystring gets the leftover params
    # appended with "&", not a second "?".
    legacy_with_qs = {
        "display_name": "X",
        "endpoints": [{
            "type": "custom", "method": "GET", "url": "http://x/?existing=1",
            "params": {"lat": "{{latitude}}"},
            "headers": {}, "body_type": "none", "body": "", "cron": "*/5 * * * *",
        }],
    }
    ep2 = config_store.normalize_device_config(legacy_with_qs)["endpoints"][0]
    assert ep2["url"] == "http://x/?existing=1&lat={{latitude}}"


def test_config_store_migrates_from_legacy_json(tmp_path, monkeypatch):
    import json

    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    legacy_path = tmp_path / "forwarding_config.json"
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", legacy_path)

    legacy_path.write_text(json.dumps({"devices": {"dev-1": {"display_name": "X", "endpoints": []}}}))

    # First read migrates: loads the JSON, and from then on the YAML file is
    # the source of truth. The old JSON file is left alone, not deleted.
    assert config_store.get_device_config("dev-1") == {"display_name": "X", "endpoints": []}
    assert config.DEVICES_PATH.exists()
    assert legacy_path.exists()

    config_store.set_device_config("dev-2", {"display_name": "Y", "endpoints": []})
    legacy_path.write_text(json.dumps({"devices": {}}))  # even if this goes stale afterwards
    assert {"dev-1", "dev-2"} <= config_store.all_devices().keys()


def test_log_store_round_trip(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")

    log_store.append("dev-1", "My Tracker", "traccar", "http://x (device d1)", "ok")
    log_store.append("dev-1", "My Tracker", "phonetrack", "http://y (p1)", "error: boom")
    log_store.append("dev-1", "My Tracker", "traccar", "http://x (device d1)", "skipped")

    entries = log_store.recent_entries()
    assert [e["status"] for e in entries] == ["skipped", "error: boom", "ok"]  # newest first
    assert [e["level"] for e in entries] == ["skipped", "error", "ok"]


def test_log_store_migrates_from_legacy_json(tmp_path, monkeypatch):
    import json

    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    legacy_path = tmp_path / "forward_log.json"
    monkeypatch.setattr(config, "FORWARD_LOG_LEGACY_JSON_PATH", legacy_path)

    legacy_path.write_text(json.dumps({"entries": [
        {"time": 1, "canonic_id": "dev-1", "device_name": "X", "endpoint_type": "traccar",
         "target": "http://x", "status": "ok"},
    ]}))

    entries = log_store.recent_entries()
    assert [e["status"] for e in entries] == ["ok"]
    assert config.FORWARD_LOG_PATH.exists()
    assert legacy_path.exists()  # left alone, not deleted

    log_store.append("dev-1", "X", "traccar", "http://x", "error: boom")
    entries = log_store.recent_entries()
    assert [e["status"] for e in entries] == ["error: boom", "ok"]


def test_log_store_round_trips_the_full_payload(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")

    payload = '{"latitude": 1.0, "longitude": 2.0, "is_semantic": false}'
    log_store.append("dev-1", "My Tracker", "traccar", "http://x", "ok", payload=payload)

    entries = log_store.recent_entries()
    assert entries[0]["payload"] == payload


def test_log_store_round_trips_the_response_body(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")

    log_store.append("dev-1", "My Tracker", "traccar", "http://x", "ok", response='200: {"done":1}')

    entries = log_store.recent_entries()
    assert entries[0]["response"] == '200: {"done":1}'


def test_log_store_reads_pre_payload_lines_as_blank(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    log_path = tmp_path / "forward.log"
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", log_path)

    # A line written before the payload column existed - 6 fields, not 7.
    log_path.write_text("1\tdev-1\tMy Tracker\ttraccar\thttp://x\tok\n")

    entries = log_store.recent_entries()
    assert entries[0]["status"] == "ok"
    assert entries[0]["payload"] == ""
    assert entries[0]["response"] == ""


def test_log_store_reads_pre_response_lines_as_blank(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    log_path = tmp_path / "forward.log"
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", log_path)

    # A line written before the response column existed - 7 fields, not 8.
    log_path.write_text("1\tdev-1\tMy Tracker\ttraccar\thttp://x\tok\tsome-payload\n")

    entries = log_store.recent_entries()
    assert entries[0]["status"] == "ok"
    assert entries[0]["payload"] == "some-payload"
    assert entries[0]["response"] == ""


def test_log_store_sanitizes_embedded_tabs_and_newlines(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")

    log_store.append(
        "dev-1", "My\tTracker", "traccar", "http://x", "error: line one\nline two",
        response="500: multi\nline\tbody",
    )

    entries = log_store.recent_entries()
    assert "\t" not in entries[0]["device_name"]
    assert "\n" not in entries[0]["status"]
    assert "\t" not in entries[0]["response"]
    assert "\n" not in entries[0]["response"]
    # One log line per entry - a literal newline in the status would have split it in two.
    assert config.FORWARD_LOG_PATH.read_text().count("\n") == 1


def test_log_store_caps_entries(tmp_path, monkeypatch):
    from webui import config, line_log_io
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "FORWARD_LOG_MAX_ENTRIES", 5)
    # append_line() only compacts once every _COMPACT_SLACK entries past the
    # cap (see line_log_io.py) - force it to 0 so this test still checks the
    # cap logic itself, without depending on that amortization tuning.
    monkeypatch.setattr(line_log_io, "_COMPACT_SLACK", 0)

    for i in range(10):
        log_store.append("dev-1", "My Tracker", "traccar", "target", f"status-{i}")

    entries = log_store.recent_entries()
    assert len(entries) == 5
    assert entries[0]["status"] == "status-9"  # newest first, oldest 5 dropped


def test_device_label_variables_only_offers_fields_this_device_actually_has():
    from webui.forwarders import device_label_variables

    device_meta = {
        "manufacturer": "Chipolo", "model": "ONE Point", "type": "Keys", "image_url": "https://x/p.png",
        "carrier": "", "codename": "", "imei": "", "registered_at": "", "shared_with": "",
    }
    assert device_label_variables(device_meta) == []  # a non-phone tracker: no label_* chip is a false promise


def test_device_label_variables_offers_only_the_truthy_phone_only_fields():
    from webui.forwarders import device_label_variables

    device_meta = {
        "manufacturer": "Google", "model": "Pixel", "type": "Phone", "image_url": "",
        "carrier": "T-Mobile", "codename": "", "imei": "354935091234567", "registered_at": "",
        "shared_with": "family@example.com",
    }
    names = [name for name, _ in device_label_variables(device_meta)]
    assert names == ["label_carrier", "label_imei", "label_shared_with"]  # blank codename/registered_at excluded


def test_device_label_variables_handles_missing_device_meta():
    from webui.forwarders import device_label_variables

    assert device_label_variables(None) == []
    assert device_label_variables({}) == []


def test_device_label_variables_falls_back_to_a_generic_description():
    from webui.forwarders import device_label_variables

    names_and_descriptions = device_label_variables({"a_future_field": "x"})
    assert names_and_descriptions == [("label_a_future_field", "This device's a future field, from Google's own response")]
