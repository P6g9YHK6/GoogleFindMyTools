"""Pure-logic unit tests for the forwarders package - no HTTP involved."""

from webui.forwarders import PRESETS, blank_endpoint


def test_presets_cover_traccar_and_phonetrack_and_custom():
    assert set(PRESETS) == {"custom", "traccar", "phonetrack"}
    for preset in PRESETS.values():
        assert preset["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE")
        assert isinstance(preset["params"], dict)
        assert isinstance(preset["headers"], dict)
        assert isinstance(preset["variables"], dict)


def test_traccar_preset_templates_the_fix_as_query_params():
    preset = PRESETS["traccar"]
    assert preset["params"]["lat"] == "{{latitude}}"
    assert preset["params"]["lon"] == "{{longitude}}"
    assert preset["params"]["id"] == "{{device_id}}"
    assert "device_id" in preset["variables"]


def test_phonetrack_preset_bakes_device_name_into_the_url():
    preset = PRESETS["phonetrack"]
    assert "{{device_name}}" in preset["url"]
    assert preset["params"]["lat"] == "{{latitude}}"


def test_blank_endpoint_starts_from_the_custom_preset():
    blank = blank_endpoint("*/5 * * * *")
    assert blank["cron"] == "*/5 * * * *"
    assert blank["type"] == "custom"
    assert blank["method"] == "GET"
    assert blank["url"] == ""
    assert blank["params"] == {}


def test_forward_to_custom_renders_templated_url_and_params(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["headers"] = kwargs.get("headers")
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET",
        "url": "http://traccar.local:5055/",
        "params": {"id": "{{device_id}}", "lat": "{{latitude}}", "lon": "{{longitude}}"},
        "headers": {},
        "body_type": "none", "body": "",
        "variables": {"device_id": "104"},
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    assert custom.forward_to_custom(endpoint_cfg, location, "My Phone") is True
    assert captured["method"] == "GET"
    assert captured["url"] == "http://traccar.local:5055/"
    assert captured["params"] == {"id": "104", "lat": "1.0", "lon": "2.0"}


def test_forward_to_custom_leaves_unresolved_variables_visible(monkeypatch):
    from webui.forwarders import custom

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        captured["params"] = kwargs.get("params")
        return FakeResponse()

    monkeypatch.setattr(custom.httpx, "request", fake_request)

    endpoint_cfg = {
        "method": "GET", "url": "http://x/", "params": {"token": "{{typo_var}}"},
        "headers": {}, "body_type": "none", "body": "", "variables": {},
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["params"]["token"] == "{{typo_var}}"  # left as-is, not silently dropped


def test_forward_to_custom_device_name_is_not_overridable(monkeypatch):
    """A stray "device_name" key on an endpoint (e.g. left over from an old
    config) must not change what {{device_name}}/{{device_alias}} resolve
    to - both are always the device's own real alias, never overridable
    per endpoint - see webui/forwarders/custom.py's build_context()."""
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
        "method": "GET", "url": "https://nc.local/x/{{device_name}}/{{device_alias}}", "params": {},
        "headers": {}, "body_type": "none", "body": "", "variables": {}, "device_name": "phone1",
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "https://nc.local/x/My Phone/My Phone"


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
        "method": "GET", "url": "https://nc.local/x/{{device_name}}", "params": {},
        "headers": {}, "body_type": "none", "body": "", "variables": {},
    }
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    custom.forward_to_custom(endpoint_cfg, location, "My Phone")
    assert captured["url"] == "https://nc.local/x/My Phone"


def test_forward_to_custom_skips_semantic_and_missing_coordinates():
    from webui.forwarders import custom

    endpoint_cfg = {"method": "GET", "url": "http://x/", "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {}}
    assert custom.forward_to_custom(endpoint_cfg, {"is_semantic": True}, "n") is False
    assert custom.forward_to_custom(endpoint_cfg, {"is_semantic": False, "latitude": None}, "n") is False


def test_forward_to_custom_skips_when_url_is_blank():
    from webui.forwarders import custom

    endpoint_cfg = {"method": "GET", "url": "", "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {}}
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
        "method": "POST", "url": "http://x/", "params": {}, "headers": {},
        "body_type": "json", "body": '{"lat": {{latitude}}}', "variables": {},
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
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")

    assert config_store.get_device_config("dev-1") is None
    config_store.set_device_config("dev-1", {"display_name": "X", "endpoints": []})
    assert config_store.get_device_config("dev-1") == {"display_name": "X", "endpoints": []}
    assert "dev-1" in config_store.all_devices()


def test_config_store_migrates_legacy_single_destination_shape(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")

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
    assert ep["url"] == "http://a/"
    assert ep["params"]["lat"] == "{{latitude}}"
    assert ep["variables"] == {"device_id": "1"}
    assert ep["cron"] == "*/2 * * * *"
    assert ep["last_forward_status"] == "ok"
    assert ep["last_forward_time"] == 123
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
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")

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

    assert traccar_ep["url"] == "http://a/"
    assert traccar_ep["variables"] == {"device_id": "1"}

    assert phonetrack_ep["url"] == "http://b/p1"
    assert "device_name" not in phonetrack_ep
    assert phonetrack_ep["alias"] == "PT"


def test_config_store_migrates_from_legacy_json(tmp_path, monkeypatch):
    import json

    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
    legacy_path = tmp_path / "forwarding_config.json"
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", legacy_path)

    legacy_path.write_text(json.dumps({"devices": {"dev-1": {"display_name": "X", "endpoints": []}}}))

    # First read migrates: loads the JSON, and from then on the YAML file is
    # the source of truth. The old JSON file is left alone, not deleted.
    assert config_store.get_device_config("dev-1") == {"display_name": "X", "endpoints": []}
    assert config.FORWARDING_CONFIG_PATH.exists()
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


def test_log_store_sanitizes_embedded_tabs_and_newlines(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")

    log_store.append("dev-1", "My\tTracker", "traccar", "http://x", "error: line one\nline two")

    entries = log_store.recent_entries()
    assert "\t" not in entries[0]["device_name"]
    assert "\n" not in entries[0]["status"]
    # One log line per entry - a literal newline in the status would have split it in two.
    assert config.FORWARD_LOG_PATH.read_text().count("\n") == 1


def test_log_store_caps_entries(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "FORWARD_LOG_MAX_ENTRIES", 5)

    for i in range(10):
        log_store.append("dev-1", "My Tracker", "traccar", "target", f"status-{i}")

    entries = log_store.recent_entries()
    assert len(entries) == 5
    assert entries[0]["status"] == "status-9"  # newest first, oldest 5 dropped
