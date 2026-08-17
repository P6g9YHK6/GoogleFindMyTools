"""webui/device_store.py: the shared devices.yaml backing config_store.py,
device_location_store.py and latest_values_store.py, and the one-time
migration folding their three pre-fusion files into it."""

import yaml


def _isolate(tmp_path, monkeypatch):
    from webui import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", tmp_path / "forwarding_config.json")
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")
    monkeypatch.setattr(config, "LATEST_VALUES_PATH", tmp_path / "latest_values.yaml")
    return config


def test_load_on_a_genuinely_fresh_install_creates_nothing(tmp_path, monkeypatch):
    config = _isolate(tmp_path, monkeypatch)
    from webui import device_store

    assert device_store.load() == {"schema_version": 1, "devices": {}}
    assert not config.DEVICES_PATH.exists()
    assert device_store.last_load_ok() is True


def test_load_is_false_for_corrupt_yaml(tmp_path, monkeypatch):
    config = _isolate(tmp_path, monkeypatch)
    from webui import device_store

    config.DEVICES_PATH.write_text("not: valid: yaml: [")
    assert device_store.load() == {"schema_version": 1, "devices": {}}
    assert device_store.last_load_ok() is False


def test_migrates_and_merges_the_three_legacy_files(tmp_path, monkeypatch):
    config = _isolate(tmp_path, monkeypatch)
    from webui import device_store

    config.FORWARDING_CONFIG_PATH.write_text(yaml.safe_dump({
        "devices": {"dev-1": {"display_name": "Keys", "endpoints": []}},
    }))
    config.DEVICE_LOCATIONS_PATH.write_text(yaml.safe_dump({
        "dev-1": {"locations": [{"latitude": 1.0, "longitude": 2.0}], "fetched_at": 100},
    }))
    config.LATEST_VALUES_PATH.write_text(yaml.safe_dump({
        "dev-1": {
            "http://x/": {"last_forward_status": "ok"},
            "__staleness__": {"enabled": True},
        },
    }))

    data = device_store.load()
    entry = data["devices"]["dev-1"]
    assert entry["config"] == {"display_name": "Keys", "endpoints": []}
    assert entry["location"]["fetched_at"] == 100
    assert entry["endpoint_state"] == {"http://x/": {"last_forward_status": "ok"}}
    assert entry["staleness"] == {"enabled": True}
    assert config.DEVICES_PATH.exists()  # migrated once, written back

    # A second load reads devices.yaml directly - it doesn't need the legacy
    # files anymore, and doesn't re-merge/duplicate anything.
    config.FORWARDING_CONFIG_PATH.unlink()
    config.DEVICE_LOCATIONS_PATH.unlink()
    config.LATEST_VALUES_PATH.unlink()
    assert device_store.load() == data


def test_mutate_device_only_writes_when_something_actually_changed(tmp_path, monkeypatch):
    config = _isolate(tmp_path, monkeypatch)
    from webui import device_store

    device_store.mutate_device("dev-1", lambda entry: None)
    assert not config.DEVICES_PATH.exists()  # a no-op mutation never creates the file

    device_store.mutate_device("dev-1", lambda entry: entry.update(config={"display_name": "X"}))
    assert config.DEVICES_PATH.exists()

    before = config.DEVICES_PATH.read_text()
    device_store.mutate_device("dev-1", lambda entry: entry.update(config={"display_name": "X"}))
    assert config.DEVICES_PATH.read_text() == before  # identical value, no rewrite triggered by content change


def test_mutate_device_drops_the_entry_once_it_becomes_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from webui import device_store

    device_store.mutate_device("dev-1", lambda entry: entry.update(config={"display_name": "X"}))
    assert "dev-1" in device_store.load()["devices"]

    device_store.mutate_device("dev-1", lambda entry: entry.pop("config", None))
    assert "dev-1" not in device_store.load()["devices"]
