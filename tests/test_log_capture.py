import logging

from webui import config, log_capture, system_log_store


def test_configure_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    first = log_capture.configure_log_capture()
    second = log_capture.configure_log_capture()
    try:
        handlers = [h for h in logging.getLogger().handlers if isinstance(h, log_capture._SystemLogHandler)]
        assert handlers == [second]
        assert first not in handlers
    finally:
        logging.getLogger().removeHandler(second)


def test_captures_a_warning_from_outside_the_webui_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    handler = log_capture.configure_log_capture()
    try:
        logging.getLogger("Auth.fcm_receiver").warning("push client crashed")
        entries = system_log_store.recent_entries()
        assert any(e["message"] == "push client crashed" and e["level"] == "WARNING" for e in entries)
    finally:
        logging.getLogger().removeHandler(handler)


def test_ignores_noisy_loggers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    handler = log_capture.configure_log_capture()
    try:
        logging.getLogger("uvicorn.access").info("GET /auth/queue 200 OK")
        entries = system_log_store.recent_entries()
        assert entries == []
    finally:
        logging.getLogger().removeHandler(handler)
