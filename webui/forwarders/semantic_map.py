"""Substitutes fixed coordinates into SEMANTIC location readings that have a
configured mapping - see webui/settings_store.py's semantic_location_map.
Google never reports lat/lon for a SEMANTIC result (a tracker recognized as
being near a named smart-home device, e.g. "Nest Mini - Living Room"), so
without this every gate in policy.py and the send in custom.py just drops it.
Deliberately its own module (not policy.py or decrypt_locations.py) since it's
a distinct concern - decrypt_locations.py has no access to app settings, and
policy.py is about *whether* to forward a location, not what's in it.
"""

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import create_map_links


def apply_semantic_mapping(locations: list[dict], mapping: dict) -> list[dict]:
    """Returns `locations` with a coordinate-bearing copy substituted for any
    entry whose is_semantic/semantic_name matches a mapping key exactly
    (after stripping whitespace) - is_semantic, semantic_name, status, and
    every other field are left exactly as decoded, so a mapped reading stays
    distinguishable from a real GPS/crowdsourced fix downstream (the
    Forwarding Log's payload, any destination reading {{status}}). A location
    with no match (semantic with an unmapped name, or already non-semantic)
    is passed through unchanged - same object, not a copy - so callers that
    compare by identity aren't affected."""
    if not mapping:
        return locations

    mapped = []
    for location in locations:
        name = (location.get("semantic_name") or "").strip()
        coords = mapping.get(name) if location.get("is_semantic") and name else None
        if coords is None:
            mapped.append(location)
            continue

        latitude, longitude = coords.get("latitude"), coords.get("longitude")
        mapped.append({
            **location,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": None,
            "map_links": create_map_links(latitude, longitude),
        })
    return mapped
