def test_logs_page_empty(client):
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "No forwarding attempts logged yet" in resp.text


def test_logs_page_with_entries(client):
    from webui.forwarders import log_store

    log_store.append("canonic-1", "My Tracker", "traccar", "http://x (device d1)", "ok",
                      payload='{"latitude": 1.0, "longitude": 2.0}')
    log_store.append("canonic-1", "My Tracker", "phonetrack", "http://y (p1)", "error: boom")
    log_store.append("canonic-1", "My Tracker", "traccar", "http://x (device d1)", "skipped")

    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "log-ok" in resp.text
    assert "log-error" in resp.text
    assert "log-skipped" in resp.text
    assert "boom" in resp.text
    assert "&#34;latitude&#34;: 1.0" in resp.text or '"latitude": 1.0' in resp.text


def test_system_log_page_empty(client, tmp_path, monkeypatch):
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert "No log entries yet" in resp.text


def test_system_log_page_with_entries(client, tmp_path, monkeypatch):
    from webui import config, system_log_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    system_log_store.append(level="WARNING", logger_name="Auth.fcm_receiver", message="push client crashed", when=1)
    system_log_store.append(level="INFO", logger_name="webui.scheduler", message="polling started", when=2)

    resp = client.get("/logs/system")
    assert resp.status_code == 200
    assert "log-warning" in resp.text
    assert "log-info" in resp.text
    assert "push client crashed" in resp.text
    assert "Auth.fcm_receiver" in resp.text
