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
    assert saved == {
        "locations": [{**locations[0], "first_seen": 1700000000}],
        "fetched_at": 1700000000,
    }


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
    assert loc == {"is_semantic": True, "semantic_name": "Home", "first_seen": 1}


def test_devices_do_not_clobber_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location("dev-1", [{"latitude": 1.0}], fetched_at=1)
    device_location_store.set_last_location("dev-2", [{"latitude": 2.0}], fetched_at=2)

    assert device_location_store.get_last_location("dev-1")["locations"] == [{"latitude": 1.0, "first_seen": 1}]
    assert device_location_store.get_last_location("dev-2")["locations"] == [{"latitude": 2.0, "first_seen": 2}]


def test_a_later_call_overwrites_the_prior_one_for_the_same_device(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    device_location_store.set_last_location("dev-1", [{"latitude": 1.0}], fetched_at=1)
    device_location_store.set_last_location("dev-1", [{"latitude": 2.0}], fetched_at=2)

    assert device_location_store.get_last_location("dev-1") == {
        "locations": [{"latitude": 2.0, "first_seen": 2}], "fetched_at": 2,
    }


def test_a_corrupt_file_is_treated_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    path = tmp_path / "device_locations.yaml"
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", path)
    path.write_text("not: valid: yaml: [")

    assert device_location_store.get_last_location("dev-1") is None


def test_set_last_location_backfills_first_seen_for_a_reading_stored_before_that_field_existed(tmp_path, monkeypatch):
    """A device_locations.yaml written before first_seen existed has none on
    its stored locations - set_last_location must not just propagate that
    missing/null value forever once the same reading reappears; it should
    fall back to the prior snapshot's own fetched_at instead."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    path = tmp_path / "device_locations.yaml"
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", path)

    import yaml

    reading = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "status": "REPORTED", "time": 100}
    path.write_text(yaml.safe_dump({"dev-1": {"locations": [reading], "fetched_at": 500}}))

    stamped = device_location_store.set_last_location("dev-1", [reading], fetched_at=1000)

    assert stamped[0]["first_seen"] == 500
    assert stamped[0]["_new_this_fetch"] is False  # still correctly recognized as already seen


def test_set_last_location_stamps_a_new_reading_with_this_fetchs_time(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    stamped = device_location_store.set_last_location(
        "dev-1", [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 100}], fetched_at=1000,
    )

    assert stamped[0]["first_seen"] == 1000


def test_set_last_location_keeps_the_original_first_seen_for_a_reading_google_resends(tmp_path, monkeypatch):
    """Google sometimes bundles a stale, already-reported reading alongside
    fresh ones - that reading's first_seen must stay pinned to whenever we
    actually first observed it, not keep sliding forward on every fetch."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    reading = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "status": "REPORTED", "time": 100}
    device_location_store.set_last_location("dev-1", [reading], fetched_at=1000)

    stamped = device_location_store.set_last_location("dev-1", [reading], fetched_at=2000)

    assert stamped[0]["first_seen"] == 1000


def test_set_last_location_only_stamps_a_within_batch_duplicate_once(tmp_path, monkeypatch):
    """The exact same reading appearing twice in one incoming batch (Google
    duplicating an entry within a single response) must not be treated as
    "new" the second time just because there's no prior fetch to compare
    against yet."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    reading = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "status": "REPORTED", "time": 100}
    stamped = device_location_store.set_last_location("dev-1", [reading, dict(reading)], fetched_at=1000)

    assert stamped[0]["first_seen"] == 1000
    assert stamped[1]["first_seen"] == 1000


def test_set_last_location_treats_a_different_reading_as_new_even_with_others_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")

    old_reading = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "status": "REPORTED", "time": 100}
    device_location_store.set_last_location("dev-1", [old_reading], fetched_at=1000)

    new_reading = {"is_semantic": False, "latitude": 3.0, "longitude": 4.0, "status": "REPORTED", "time": 200}
    stamped = device_location_store.set_last_location("dev-1", [old_reading, new_reading], fetched_at=2000)

    assert stamped[0]["first_seen"] == 1000  # unchanged - already seen at fetched_at=1000
    assert stamped[1]["first_seen"] == 2000  # genuinely new this fetch


def test_get_last_location_backfills_first_seen_for_a_location_saved_before_that_field_existed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    path = tmp_path / "device_locations.yaml"
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", path)

    import yaml

    path.write_text(yaml.safe_dump({
        "dev-1": {
            "locations": [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0}],
            "fetched_at": 1234,
        },
    }))

    loc = device_location_store.get_last_location("dev-1")["locations"][0]
    assert loc["first_seen"] == 1234
