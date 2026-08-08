import httpx

TIMEOUT_S = 10


def forward_to_traccar(base_url: str, device_id: str, location: dict) -> bool:
    if location.get("is_semantic") or location.get("latitude") is None:
        return False

    params = {
        "id": device_id,
        "lat": location["latitude"],
        "lon": location["longitude"],
        "timestamp": location["time"],
    }
    if location.get("altitude") is not None:
        params["altitude"] = location["altitude"]
    if location.get("accuracy") is not None:
        params["accuracy"] = location["accuracy"]
    # Only ever present when this endpoint's "fetch_live_info" toggle is on
    # and the extra query actually got an answer - see webui/scheduler.py's
    # _merge_extra_info and Auth/live_device_info.py.
    if location.get("battery_pct") is not None:
        params["batt"] = location["battery_pct"]

    url = base_url.rstrip("/") + "/"
    response = httpx.get(url, params=params, timeout=TIMEOUT_S)
    response.raise_for_status()
    return True
