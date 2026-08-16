import pytest


@pytest.fixture(autouse=True)
def _isolated_log_paths(tmp_path, monkeypatch):
    """Every test in this file gets its own forward.log/system.log, so
    entries from one test never leak into another's assertions."""
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")


def _seed_forwarding_entries():
    from webui.forwarders import log_store

    log_store.append("canonic-1", "My Tracker", "traccar", "http://x (device d1)", "ok",
                      payload='{"latitude": 1.0, "longitude": 2.0}')
    log_store.append("canonic-1", "My Tracker", "phonetrack", "http://y (p1)", "error: boom")
    log_store.append("canonic-1", "My Tracker", "traccar", "http://x (device d1)", "skipped")


def _seed_system_entries():
    from webui import system_log_store

    system_log_store.append(level="WARNING", logger_name="Auth.fcm_receiver", message="push client crashed", when=1)
    system_log_store.append(level="INFO", logger_name="webui.scheduler", message="polling started", when=2)


def test_logs_page_empty(client):
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "No log entries yet." in resp.text


def test_logs_page_with_entries(client):
    _seed_forwarding_entries()
    _seed_system_entries()

    resp = client.get("/logs")
    assert resp.status_code == 200

    # Forwarding rows
    assert "log-ok" in resp.text
    assert "log-error" in resp.text
    assert "log-skipped" in resp.text
    assert "boom" in resp.text
    assert "&#34;latitude&#34;: 1.0" in resp.text or '"latitude": 1.0' in resp.text
    assert "Forwarding" in resp.text

    # System rows
    assert "log-warning" in resp.text
    assert "log-info" in resp.text
    assert "push client crashed" in resp.text
    assert "Auth.fcm_receiver" in resp.text
    assert "System" in resp.text


def test_logs_filter_by_type(client):
    _seed_forwarding_entries()
    _seed_system_entries()

    resp = client.get("/logs", params={"type": "forwarding"})
    assert resp.status_code == 200
    assert "boom" in resp.text
    assert "push client crashed" not in resp.text

    resp = client.get("/logs", params={"type": "system"})
    assert resp.status_code == 200
    assert "push client crashed" in resp.text
    assert "boom" not in resp.text


def test_logs_filter_by_level(client):
    _seed_forwarding_entries()
    _seed_system_entries()

    resp = client.get("/logs", params={"level": "warning"})
    assert resp.status_code == 200
    assert "push client crashed" in resp.text
    assert "boom" not in resp.text
    assert "polling started" not in resp.text


def test_logs_search(client):
    _seed_forwarding_entries()
    _seed_system_entries()

    resp = client.get("/logs", params={"q": "scheduler"})
    assert resp.status_code == 200
    assert "polling started" in resp.text
    assert "boom" not in resp.text
    assert "push client crashed" not in resp.text


def test_logs_page_shows_the_response_body(client):
    from webui.forwarders import log_store

    log_store.append(
        "canonic-1", "My Tracker", "phonetrack", "https://nc.local/logGet", "ok",
        response='200: {"done":1,"pointId":123,"deviceId":19}',
    )

    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "deviceId&#34;:19" in resp.text or '"deviceId":19' in resp.text


def test_logs_search_matches_the_response_body(client):
    from webui.forwarders import log_store

    log_store.append("canonic-1", "My Tracker", "phonetrack", "https://nc.local/logGet", "ok",
                      response="200: session-not-started")

    resp = client.get("/logs", params={"q": "session-not-started"})
    assert resp.status_code == 200
    assert "session-not-started" in resp.text


def test_logs_no_matches_message(client):
    _seed_forwarding_entries()

    resp = client.get("/logs", params={"q": "no-such-entry-anywhere"})
    assert resp.status_code == 200
    assert "No log entries match these filters." in resp.text


def test_logs_table_partial_is_just_the_fragment(client):
    _seed_forwarding_entries()

    resp = client.get("/logs/table")
    assert resp.status_code == 200
    assert "<table" in resp.text
    assert "<html" not in resp.text
    assert "<nav>" not in resp.text


def test_logs_table_is_sortable(client):
    """Opts into static/tables.js's click-to-sort/drag-to-resize columns."""
    resp = client.get("/logs/table")
    assert resp.status_code == 200
    assert '<table class="sortable-table" data-table-id="logs">' in resp.text


def test_logs_system_redirects_to_unified_page(client):
    _seed_system_entries()

    resp = client.get("/logs/system")
    assert resp.status_code == 200  # TestClient follows the redirect by default
    assert "push client crashed" in resp.text
    assert str(resp.url).endswith("/logs?type=system")
