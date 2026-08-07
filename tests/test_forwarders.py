"""Pure-logic unit tests for the forwarders package - no HTTP involved."""

from webui.forwarders import FORWARDER_TYPES, blank_endpoint


def test_registry_field_names_match_form_naming():
    assert FORWARDER_TYPES["traccar"].form_field_name("url") == "traccar_url"
    assert FORWARDER_TYPES["traccar"].form_field_name("device_id") == "traccar_device_id"
    assert FORWARDER_TYPES["phonetrack"].form_field_name("base_url") == "phonetrack_base_url"
    assert FORWARDER_TYPES["phonetrack"].form_field_name("device_name") == "phonetrack_device_name"


def test_registry_target_labels():
    assert FORWARDER_TYPES["traccar"].target_label({"url": "http://x", "device_id": "d1"}) == "http://x (device d1)"
    assert FORWARDER_TYPES["phonetrack"].target_label({"base_url": "http://y", "device_name": "p1"}) == "http://y (p1)"


def test_blank_endpoint_has_one_empty_config_per_registered_type():
    blank = blank_endpoint("*/5 * * * *")
    assert blank["cron"] == "*/5 * * * *"
    assert blank["type"] in FORWARDER_TYPES
    for key in FORWARDER_TYPES:
        assert blank[key] == {}


def test_config_store_round_trip(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")

    assert config_store.get_device_config("dev-1") is None
    config_store.set_device_config("dev-1", {"display_name": "X", "endpoints": []})
    assert config_store.get_device_config("dev-1") == {"display_name": "X", "endpoints": []}
    assert "dev-1" in config_store.all_devices()


def test_config_store_normalizes_legacy_shape(tmp_path, monkeypatch):
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
    assert normalized["endpoints"] == [{
        "type": "traccar", "traccar": {"url": "http://a", "device_id": "1"}, "cron": "*/2 * * * *",
        "last_forward_status": "ok", "last_forward_time": 123,
    }]

    none_dest = config_store.normalize_device_config({"display_name": "x", "destination": "none"})
    assert none_dest["endpoints"] == []

    already_new = {"display_name": "x", "endpoints": []}
    assert config_store.normalize_device_config(already_new) is already_new


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
