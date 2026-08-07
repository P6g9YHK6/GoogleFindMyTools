from webui import config, settings_store


def test_load_returns_env_defaults_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 42)

    settings = settings_store.load()
    assert settings["query_throttle_max"] == 42
    assert not config.APP_SETTINGS_PATH.exists()


def test_save_then_load_round_trips_and_overrides_the_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 42)

    settings_store.save({"query_throttle_max": 7})
    settings = settings_store.load()
    assert settings["query_throttle_max"] == 7  # overridden
    assert settings["query_min_spread_s"] == config.QUERY_MIN_SPREAD_S  # untouched key still defaults


def test_apprise_env_shapes_settings_for_notify_module(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", tmp_path / "config.yaml")

    settings_store.save({"apprise_urls": "json://x", "apprise_notify_level": "ERROR"})
    assert settings_store.apprise_env() == {"APPRISE_URLS": "json://x", "APPRISE_NOTIFY_LEVEL": "ERROR"}


def test_load_ignores_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    settings_path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "APP_SETTINGS_PATH", settings_path)
    settings_path.write_text("not: valid: yaml: [")

    settings = settings_store.load()
    assert settings["query_throttle_max"] == config.QUERY_THROTTLE_MAX
