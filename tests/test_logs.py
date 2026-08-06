def test_logs_page_empty(client):
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "No forwarding attempts logged yet" in resp.text


def test_logs_page_with_entries(client):
    from webui.forwarders import log_store

    log_store.append("canonic-1", "My Tracker", "traccar", "http://x (device d1)", "ok")
    log_store.append("canonic-1", "My Tracker", "phonetrack", "http://y (p1)", "error: boom")
    log_store.append("canonic-1", "My Tracker", "traccar", "http://x (device d1)", "skipped")

    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "log-ok" in resp.text
    assert "log-error" in resp.text
    assert "log-skipped" in resp.text
    assert "boom" in resp.text
