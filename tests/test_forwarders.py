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
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding_config.json")

    assert config_store.get_device_config("dev-1") is None
    config_store.set_device_config("dev-1", {"display_name": "X", "endpoints": []})
    assert config_store.get_device_config("dev-1") == {"display_name": "X", "endpoints": []}
    assert "dev-1" in config_store.all_devices()


def test_config_store_normalizes_legacy_shape(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding_config.json")

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


def test_log_store_round_trip(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward_log.json")

    log_store.append("dev-1", "My Tracker", "traccar", "http://x (device d1)", "ok")
    log_store.append("dev-1", "My Tracker", "phonetrack", "http://y (p1)", "error: boom")
    log_store.append("dev-1", "My Tracker", "traccar", "http://x (device d1)", "skipped")

    entries = log_store.recent_entries()
    assert [e["status"] for e in entries] == ["skipped", "error: boom", "ok"]  # newest first
    assert [e["level"] for e in entries] == ["skipped", "error", "ok"]


def test_log_store_caps_entries(tmp_path, monkeypatch):
    from webui import config
    from webui.forwarders import log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward_log.json")
    monkeypatch.setattr(config, "FORWARD_LOG_MAX_ENTRIES", 5)

    for i in range(10):
        log_store.append("dev-1", "My Tracker", "traccar", "target", f"status-{i}")

    entries = log_store.recent_entries()
    assert len(entries) == 5
    assert entries[0]["status"] == "status-9"  # newest first, oldest 5 dropped
