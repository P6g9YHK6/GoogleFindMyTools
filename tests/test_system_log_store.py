from webui import config, system_log_store


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    system_log_store.append(level="INFO", logger_name="webui.scheduler", message="polling started", when=1)
    system_log_store.append(level="WARNING", logger_name="Auth.fcm_receiver", message="push client crashed", when=2)

    entries = system_log_store.recent_entries()
    assert [e["message"] for e in entries] == ["push client crashed", "polling started"]  # newest first
    assert entries[0]["level"] == "WARNING"
    assert entries[0]["logger"] == "Auth.fcm_receiver"


def test_caps_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")
    monkeypatch.setattr(config, "SYSTEM_LOG_MAX_ENTRIES", 5)

    for i in range(10):
        system_log_store.append(level="INFO", logger_name="test", message=f"line {i}", when=i)

    entries = system_log_store.recent_entries()
    assert len(entries) == 5
    assert entries[0]["message"] == "line 9"  # newest first, oldest 5 dropped


def test_sanitizes_embedded_tabs_and_newlines(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SYSTEM_LOG_PATH", tmp_path / "system.log")

    system_log_store.append(level="INFO", logger_name="test", message="line one\nline two\ttabbed", when=1)

    entries = system_log_store.recent_entries()
    assert "\t" not in entries[0]["message"]
    assert "\n" not in entries[0]["message"]
    assert config.SYSTEM_LOG_PATH.read_text().count("\n") == 1
