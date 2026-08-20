"""Unit tests for webui/forwarders/semantic_map.py's apply_semantic_mapping -
independent of *when* it runs (that's webui/scheduler.py, covered by
tests/test_scheduler.py instead)."""

from webui.forwarders import semantic_map


def _semantic(name, **overrides):
    location = {
        "is_semantic": True, "semantic_name": name, "latitude": None, "longitude": None,
        "altitude": None, "time": 1, "status": "SEMANTIC", "status_id": 0,
        "accuracy": 0, "is_own_report": True, "map_links": None,
    }
    location.update(overrides)
    return location


def _gps(**overrides):
    location = {
        "is_semantic": False, "semantic_name": None, "latitude": 1.0, "longitude": 2.0,
        "altitude": 3, "time": 1, "status": "LAST_KNOWN", "status_id": 1,
        "accuracy": 5, "is_own_report": True, "map_links": {"OSM": "http://x"},
    }
    location.update(overrides)
    return location


def test_no_mapping_configured_returns_locations_unchanged():
    locations = [_semantic("Home"), _gps()]
    assert semantic_map.apply_semantic_mapping(locations, {}) == locations
    assert semantic_map.apply_semantic_mapping(locations, {}) is locations


def test_matching_semantic_name_gets_mapped_coordinates():
    location = _semantic("Nest Mini - Living Room")
    mapping = {"Nest Mini - Living Room": {"latitude": 45.0, "longitude": 9.0}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result["latitude"] == 45.0
    assert result["longitude"] == 9.0
    assert result["altitude"] is None
    assert result["map_links"]  # a real dict of provider links now, not None
    # Everything that marks this as a semantic (not GPS) reading survives.
    assert result["is_semantic"] is True
    assert result["semantic_name"] == "Nest Mini - Living Room"
    assert result["status"] == "SEMANTIC"
    assert result["accuracy"] == 0
    assert result["is_own_report"] is True


def test_non_matching_semantic_name_passes_through_unchanged():
    location = _semantic("Unmapped Place")
    mapping = {"Nest Mini - Living Room": {"latitude": 45.0, "longitude": 9.0}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result is location
    assert result["latitude"] is None


def test_non_semantic_location_passes_through_unchanged_even_if_name_matches():
    # A real GPS fix has no semantic_name, so it can never accidentally
    # match a mapping key - but even a location that somehow did carry a
    # matching name should only ever be substituted when is_semantic is True.
    location = _gps(semantic_name="Nest Mini - Living Room")
    mapping = {"Nest Mini - Living Room": {"latitude": 45.0, "longitude": 9.0}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result is location
    assert result["latitude"] == 1.0


def test_semantic_name_is_matched_after_stripping_whitespace():
    location = _semantic("  Home  ")
    mapping = {"Home": {"latitude": 1.0, "longitude": 2.0}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result["latitude"] == 1.0


def test_mixed_batch_only_substitutes_the_matching_semantic_entry():
    mapped = _semantic("Home")
    unmapped = _semantic("Unknown Place")
    gps = _gps()
    mapping = {"Home": {"latitude": 1.0, "longitude": 2.0}}

    result = semantic_map.apply_semantic_mapping([mapped, unmapped, gps], mapping)

    assert result[0]["latitude"] == 1.0
    assert result[1] is unmapped
    assert result[2] is gps


def test_entry_with_no_match_mode_still_matches_exactly():
    # Configs saved before match_mode existed have no such key at all -
    # should keep behaving like "full" always did.
    location = _semantic("Home")
    mapping = {"Home": {"latitude": 1.0, "longitude": 2.0}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result["latitude"] == 1.0


def test_full_match_mode_rejects_a_mere_substring():
    location = _semantic("Nest Mini - Living Room")
    mapping = {"Living Room": {"latitude": 1.0, "longitude": 2.0, "match_mode": "full"}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result is location
    assert result["latitude"] is None


def test_partial_match_mode_matches_on_substring():
    location = _semantic("Nest Mini - Living Room")
    mapping = {"Living Room": {"latitude": 1.0, "longitude": 2.0, "match_mode": "partial"}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result["latitude"] == 1.0
    assert result["longitude"] == 2.0
    assert result["semantic_name"] == "Nest Mini - Living Room"


def test_partial_match_mode_does_not_match_when_not_a_substring():
    location = _semantic("Unrelated Place")
    mapping = {"Living Room": {"latitude": 1.0, "longitude": 2.0, "match_mode": "partial"}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result is location


def test_partial_match_mode_is_case_insensitive():
    location = _semantic("nest mini - LIVING ROOM")
    mapping = {"Living Room": {"latitude": 1.0, "longitude": 2.0, "match_mode": "partial"}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result["latitude"] == 1.0


def test_full_match_mode_still_requires_matching_case():
    location = _semantic("home")
    mapping = {"Home": {"latitude": 1.0, "longitude": 2.0, "match_mode": "full"}}

    [result] = semantic_map.apply_semantic_mapping([location], mapping)

    assert result is location
