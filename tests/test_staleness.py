import logging

from webui import config, device_location_store, staleness
from webui.forwarders import config_store, latest_values_store

CANONIC_ID = "dev-1"


def _use_tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEVICES_PATH", tmp_path / "devices.yaml")
    monkeypatch.setattr(config, "FORWARDING_CONFIG_LEGACY_JSON_PATH", tmp_path / "forwarding_config.json")


def _set_fix(now: int, age_s: int):
    device_location_store.set_last_location(
        CANONIC_ID, [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": now - age_s}], fetched_at=now,
    )


# --- compute_status -----------------------------------------------------

def test_compute_status_fresh_within_threshold(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _set_fix(now, age_s=60)

    status = staleness.compute_status(CANONIC_ID, {"enabled": True, "threshold_s": 3600}, now=now)
    assert status == {
        "enabled": True, "muted": False, "threshold_s": 3600,
        "last_fix_time": now - 60, "age_s": 60, "has_data": True, "is_stale": False,
    }


def test_compute_status_stale_past_threshold(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _set_fix(now, age_s=7200)

    status = staleness.compute_status(CANONIC_ID, {"enabled": True, "threshold_s": 3600}, now=now)
    assert status["is_stale"] is True


def test_compute_status_no_data_yet_is_never_stale(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)

    status = staleness.compute_status("never-located", {"enabled": True, "threshold_s": 3600})
    assert status["has_data"] is False
    assert status["is_stale"] is False


def test_compute_status_disabled_is_never_stale_even_if_old(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _set_fix(now, age_s=999999)

    status = staleness.compute_status(CANONIC_ID, {"enabled": False, "threshold_s": 3600}, now=now)
    assert status["is_stale"] is False


def test_compute_status_no_threshold_set_is_never_stale(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _set_fix(now, age_s=999999)

    status = staleness.compute_status(CANONIC_ID, {"enabled": True, "threshold_s": None}, now=now)
    assert status["is_stale"] is False


# --- sweep_once -----------------------------------------------------------

def _configure_device(canonic_id=CANONIC_ID, **overrides):
    config_store.set_device_config(canonic_id, {"display_name": "", "google_name": "My Tag", "endpoints": []})
    cfg = {**staleness.default_staleness(), "enabled": True, "threshold_s": 3600, **overrides}
    latest_values_store.set_device_staleness(canonic_id, cfg)
    return cfg


def test_sweep_fires_once_when_crossing_threshold(tmp_path, monkeypatch, caplog):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _configure_device()
    _set_fix(now, age_s=7200)

    with caplog.at_level(logging.WARNING, logger="webui.staleness"):
        staleness.sweep_once(now=now)
    assert any("My Tag" in r.message for r in caplog.records)

    cfg = latest_values_store.get_device_staleness(CANONIC_ID)
    assert cfg["alert_active"] is True
    assert cfg["last_alert_sent_at"] == now


def test_sweep_does_not_repeat_when_repeat_is_off(tmp_path, monkeypatch, caplog):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _configure_device(repeat_s=None)
    _set_fix(now, age_s=7200)
    staleness.sweep_once(now=now)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="webui.staleness"):
        staleness.sweep_once(now=now + 3600)  # still stale, an hour later
    assert caplog.records == []


def test_sweep_repeats_after_the_configured_interval(tmp_path, monkeypatch, caplog):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _configure_device(repeat_s=1800)
    _set_fix(now, age_s=7200)
    staleness.sweep_once(now=now)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="webui.staleness"):
        staleness.sweep_once(now=now + 1800)  # exactly one repeat interval later
    assert any("My Tag" in r.message for r in caplog.records)


def test_sweep_sends_recovery_notice_once_fix_is_fresh_again(tmp_path, monkeypatch, caplog):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _configure_device()
    _set_fix(now, age_s=7200)
    staleness.sweep_once(now=now)

    _set_fix(now + 10, age_s=0)  # a fresh fix comes in
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="webui.staleness"):
        staleness.sweep_once(now=now + 10)
    assert any("reporting again" in r.message for r in caplog.records)

    cfg = latest_values_store.get_device_staleness(CANONIC_ID)
    assert cfg["alert_active"] is False


def test_sweep_skips_muted_devices_entirely(tmp_path, monkeypatch, caplog):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _configure_device(muted=True)
    _set_fix(now, age_s=7200)

    with caplog.at_level(logging.WARNING, logger="webui.staleness"):
        staleness.sweep_once(now=now)
    assert caplog.records == []


def test_sweep_skips_devices_not_opted_in(tmp_path, monkeypatch, caplog):
    _use_tmp_stores(tmp_path, monkeypatch)
    now = 1_700_000_000
    _configure_device(enabled=False)
    _set_fix(now, age_s=7200)

    with caplog.at_level(logging.WARNING, logger="webui.staleness"):
        staleness.sweep_once(now=now)
    assert caplog.records == []


# --- latest_values_store plumbing -----------------------------------------

def test_device_staleness_round_trips(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    assert latest_values_store.get_device_staleness(CANONIC_ID) == {}

    latest_values_store.set_device_staleness(CANONIC_ID, {"enabled": True, "threshold_s": 3600})
    assert latest_values_store.get_device_staleness(CANONIC_ID) == {"enabled": True, "threshold_s": 3600}


def test_device_staleness_does_not_collide_with_endpoint_urls(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    latest_values_store.set_endpoint_state(CANONIC_ID, "https://example.com/log", {"last_forward_status": "ok"})
    latest_values_store.set_device_staleness(CANONIC_ID, {"enabled": True})

    assert latest_values_store.get_endpoint_state(CANONIC_ID, "https://example.com/log") == {"last_forward_status": "ok"}
    assert latest_values_store.get_device_staleness(CANONIC_ID) == {"enabled": True}


def test_prune_to_urls_preserves_staleness_state(tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    latest_values_store.set_endpoint_state(CANONIC_ID, "https://old.example", {"last_forward_status": "ok"})
    latest_values_store.set_device_staleness(CANONIC_ID, {"enabled": True, "threshold_s": 3600})

    # Simulate a Settings-page save that removed the old endpoint entirely.
    latest_values_store.prune_to_urls(CANONIC_ID, set())

    assert latest_values_store.get_endpoint_state(CANONIC_ID, "https://old.example") == {}
    assert latest_values_store.get_device_staleness(CANONIC_ID) == {"enabled": True, "threshold_s": 3600}


# --- router -----------------------------------------------------------

def test_staleness_page_loads(client):
    resp = client.get("/staleness")
    assert resp.status_code == 200
    assert "Staleness" in resp.text


def test_staleness_table_lists_the_account_device(client):
    resp = client.get("/staleness/table")
    assert resp.status_code == 200
    assert "My Tracker" in resp.text
    assert "Tracking off" in resp.text  # not opted in yet


def test_save_device_staleness_via_form(client, tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)

    from tests.conftest import FAKE_CANONIC_ID

    resp = client.post(
        f"/staleness/devices/{FAKE_CANONIC_ID}",
        data={
            "enabled": "1",
            "threshold_preset": "86400",
            "repeat_preset": "off",
            "message_template": "Custom: {{device_name}}",
            "muted": "0",
        },
    )
    assert resp.status_code == 200

    saved = latest_values_store.get_device_staleness(FAKE_CANONIC_ID)
    assert saved["enabled"] is True
    assert saved["threshold_s"] == 86400
    assert saved["repeat_s"] is None
    assert saved["message_template"] == "Custom: {{device_name}}"


def test_save_device_staleness_accepts_a_custom_hours_value(client, tmp_path, monkeypatch):
    _use_tmp_stores(tmp_path, monkeypatch)
    from tests.conftest import FAKE_CANONIC_ID

    resp = client.post(
        f"/staleness/devices/{FAKE_CANONIC_ID}",
        data={"enabled": "1", "threshold_preset": "", "threshold_custom_hours": "5", "repeat_preset": "off"},
    )
    assert resp.status_code == 200
    assert latest_values_store.get_device_staleness(FAKE_CANONIC_ID)["threshold_s"] == 5 * 3600
