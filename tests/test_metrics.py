import pytest


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    """Every test in this file gets its own forward.log/system.log/
    forwarding.yaml, so entries from other test modules (or each other)
    never leak into these assertions - see tests/test_logs.py for the same
    pattern."""
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")


def test_metrics_exposes_prometheus_text_format(client, monkeypatch):
    from webui.routers import metrics

    monkeypatch.setattr(metrics, "is_logged_in", lambda: True)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "gfmt_uptime_seconds" in resp.text
    assert "gfmt_logged_in 1" in resp.text


def test_metrics_counts_forward_log_entries_by_outcome(client):
    from webui.forwarders import log_store

    log_store.append("id1", "Test Device", "custom", "GET http://x/", "ok", "{}")
    log_store.append("id1", "Test Device", "custom", "GET http://x/", "error: boom", "{}")
    log_store.append("id1", "Test Device", "custom", "GET http://x/", "skipped: moved less than 50m", "{}")

    resp = client.get("/metrics")
    assert 'gfmt_forward_log_entries{status="ok"} 1' in resp.text
    assert 'gfmt_forward_log_entries{status="error"} 1' in resp.text
    assert 'gfmt_forward_log_entries{status="skipped"} 1' in resp.text


def test_metrics_counts_system_log_entries_by_level(client):
    from webui import system_log_store

    system_log_store.append("WARNING", "webui.test", "something went wrong", 1)

    resp = client.get("/metrics")
    assert 'gfmt_system_log_entries{level="warning"} 1' in resp.text


def test_metrics_counts_configured_devices_and_endpoints(client):
    from webui.forwarders import config_store

    config_store.set_device_config("dev-1", {
        "display_name": "Dev 1",
        "endpoints": [
            {"type": "custom", "method": "GET", "url": "http://a/"},
            {"type": "custom", "method": "GET", "url": "http://b/"},
        ],
    })

    resp = client.get("/metrics")
    assert "gfmt_devices_configured 1" in resp.text
    assert "gfmt_forwarding_endpoints_configured 2" in resp.text
