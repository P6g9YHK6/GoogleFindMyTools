from webui import config, device_location_store


def test_get_last_location_returns_none_when_nothing_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    assert device_location_store.get_last_location("dev-1") is None


def test_set_then_get_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    locations = [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0}]
    device_location_store.set_last_location("dev-1", locations, fetched_at=1700000000)

    saved = device_location_store.get_last_location("dev-1")
    assert saved == {"locations": locations, "fetched_at": 1700000000}


def test_devices_do_not_clobber_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location("dev-1", [{"latitude": 1.0}], fetched_at=1)
    device_location_store.set_last_location("dev-2", [{"latitude": 2.0}], fetched_at=2)

    assert device_location_store.get_last_location("dev-1")["locations"] == [{"latitude": 1.0}]
    assert device_location_store.get_last_location("dev-2")["locations"] == [{"latitude": 2.0}]


def test_a_later_call_overwrites_the_prior_one_for_the_same_device(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location("dev-1", [{"latitude": 1.0}], fetched_at=1)
    device_location_store.set_last_location("dev-1", [{"latitude": 2.0}], fetched_at=2)

    assert device_location_store.get_last_location("dev-1") == {"locations": [{"latitude": 2.0}], "fetched_at": 2}


def test_get_last_extra_info_returns_none_when_nothing_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    assert device_location_store.get_last_extra_info("dev-1") is None


def test_extra_info_round_trips_and_carries_fetched_at(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_extra_info("dev-1", {"battery_pct": 95, "wifi_ssid": "Mordor"}, fetched_at=1700000000)

    saved = device_location_store.get_last_extra_info("dev-1")
    assert saved == {"battery_pct": 95, "wifi_ssid": "Mordor", "fetched_at": 1700000000}


def test_location_and_extra_info_coexist_without_clobbering_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location("dev-1", [{"latitude": 1.0}], fetched_at=1)
    device_location_store.set_last_extra_info("dev-1", {"battery_pct": 95}, fetched_at=2)

    assert device_location_store.get_last_location("dev-1")["locations"] == [{"latitude": 1.0}]
    assert device_location_store.get_last_extra_info("dev-1")["battery_pct"] == 95

    # Updating one must not erase the other.
    device_location_store.set_last_location("dev-1", [{"latitude": 2.0}], fetched_at=3)
    assert device_location_store.get_last_extra_info("dev-1")["battery_pct"] == 95


def test_a_corrupt_file_is_treated_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    path = tmp_path / "device_locations.yaml"
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", path)
    path.write_text("not: valid: yaml: [")

    assert device_location_store.get_last_location("dev-1") is None
