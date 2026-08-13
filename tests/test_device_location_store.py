from webui import config, device_location_store


def test_get_last_location_returns_none_when_nothing_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    assert device_location_store.get_last_location("dev-1") is None


def test_set_then_get_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    locations = [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "map_links": {"OSM": "http://x"}}]
    device_location_store.set_last_location("dev-1", locations, fetched_at=1700000000)

    saved = device_location_store.get_last_location("dev-1")
    assert saved == {"locations": locations, "fetched_at": 1700000000}


def test_get_last_location_backfills_map_links_for_a_location_saved_before_that_field_existed(tmp_path, monkeypatch):
    """A location fetched before decrypt_locations.py's create_map_links
    replaced the old single-provider "google_maps_link" has neither field -
    the Devices page's "Map" column must not just stay blank for it forever."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location(
        "dev-1",
        [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "google_maps_link": "http://old.example"}],
        fetched_at=1,
    )

    loc = device_location_store.get_last_location("dev-1")["locations"][0]
    assert "google_maps_link" not in loc
    assert loc["map_links"]["OSM"].startswith("https://www.openstreetmap.org/")
    assert "Google" in loc["map_links"]


def test_get_last_location_leaves_a_semantic_location_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location("dev-1", [{"is_semantic": True, "semantic_name": "Home"}], fetched_at=1)

    loc = device_location_store.get_last_location("dev-1")["locations"][0]
    assert loc == {"is_semantic": True, "semantic_name": "Home"}


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


def test_a_corrupt_file_is_treated_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    path = tmp_path / "device_locations.yaml"
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", path)
    path.write_text("not: valid: yaml: [")

    assert device_location_store.get_last_location("dev-1") is None
