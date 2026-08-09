from urllib.parse import urlencode

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME


def _post_form(client, path, **fields):
    """Repeated field names need explicit urlencoding (a dict collapses
    duplicate keys) - build the raw urlencoded body ourselves."""
    pairs = [(key, v) for key, values in fields.items() for v in values]
    return client.post(path, content=urlencode(pairs), headers={"content-type": "application/x-www-form-urlencoded"})


def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_blank_endpoint_route(client):
    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/blank")
    assert resp.status_code == 200
    assert 'name="traccar_url"' in resp.text
    assert 'name="phonetrack_base_url"' in resp.text


def test_save_mixed_endpoints_and_drop_blank_block(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar", "phonetrack", "traccar"],
        cron=["*/5 * * * *", "0 */2 * * *", "*/10 * * * *"],
        traccar_url=["http://traccar.local:5055", "", ""],  # third block left blank -> dropped
        traccar_device_id=["dev1", "", ""],
        phonetrack_base_url=["", "https://nc.local/x", ""],
        phonetrack_device_name=["", "phone1", ""],
    )
    assert resp.status_code == 200
    assert resp.text.count('class="endpoint-block"') == 2

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert len(saved["endpoints"]) == 2
    assert saved["endpoints"][0] == {
        "type": "traccar",
        "traccar": {"url": "http://traccar.local:5055", "device_id": "dev1"},
        "cron": "*/5 * * * *",
    }
    assert saved["endpoints"][1] == {
        "type": "phonetrack",
        "phonetrack": {"base_url": "https://nc.local/x", "device_name": "phone1"},
        "cron": "0 */2 * * *",
    }


def test_save_response_is_only_the_one_device_row(client):
    """A save must swap outerHTML into a single <form>, not hand back the
    whole multi-device page (which would duplicate every row on screen)."""
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200
    assert resp.text.count("<form") == 1
    assert "Forwarding Settings" not in resp.text  # page heading, not part of the row fragment
    assert "endpoint_fields.js" not in resp.text  # page-level script tag, not part of the row fragment


def test_device_alias_overrides_confusing_google_name(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["Garage Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200
    assert "Garage Tracker" in resp.text
    assert FAKE_DEVICE_NAME in resp.text  # hint pointing back at the underlying Google device name

    from webui.forwarders import config_store

    assert config_store.get_device_config(FAKE_CANONIC_ID)["display_name"] == "Garage Tracker"

    page = client.get("/settings")
    assert "Garage Tracker" in page.text


def test_endpoint_alias_is_saved_and_shown_in_legend(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        alias=["Home Traccar"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200
    assert "Home Traccar" in resp.text

    from webui.forwarders import config_store

    assert config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]["alias"] == "Home Traccar"


def test_skip_if_close_toggle_and_threshold_are_saved(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        skip_if_close=["1"],
        min_movement_m=["75"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200
    assert 'checked' in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["skip_if_close"] is True
    assert saved["min_movement_m"] == 75.0


def test_skip_if_close_defaults_off_when_not_submitted(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        skip_if_close=["0"],
        min_movement_m=["50"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert "skip_if_close" not in saved


def test_skip_if_stale_toggle_and_gap_are_saved(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        skip_if_stale=["1"],
        min_update_gap_m=["15"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200
    assert "checked" in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["skip_if_stale"] is True
    assert saved["min_update_gap_m"] == 15.0


def test_skip_if_stale_defaults_off_when_not_submitted(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        skip_if_stale=["0"],
        min_update_gap_m=["30"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert resp.status_code == 200

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert "skip_if_stale" not in saved


def test_send_now_forwards_immediately_bypassing_schedule_and_skip(client, monkeypatch):
    from webui import scheduler
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "type": "traccar",
            "traccar": {"url": "http://x", "device_id": "d1"},
            "cron": "0 0 1 1 *",  # once a year - would never be due on its own
            "skip_if_close": True, "last_sent_lat": 1.0, "last_sent_lon": 2.0,  # would normally skip this fix
        }],
    })

    async def fake_locate_device(canonic_id, name, timeout=None):
        return [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}]

    monkeypatch.setattr(scheduler, "locate_device", fake_locate_device)
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc: "ok")

    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/0/send-now")
    assert resp.status_code == 200
    assert "Last forward: ok" in resp.text
    assert "Send now" in resp.text  # the button survives its own swapped-in response

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["last_forward_status"] == "ok"
    assert saved["last_sent_lat"] == 1.0
    assert saved["last_sent_lon"] == 2.0


def test_send_now_404s_for_unknown_endpoint_index(client):
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {"display_name": "My Tracker", "endpoints": []})
    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/0/send-now")
    assert resp.status_code == 404


def test_device_yaml_view_shows_current_config(client):
    _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )

    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}/yaml")
    assert resp.status_code == 200
    assert "type: traccar" in resp.text
    assert "url: http://x" in resp.text
    assert "Edit as form" in resp.text


def test_device_form_route_switches_back_from_yaml_view(client):
    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}")
    assert resp.status_code == 200
    assert "Edit as YAML" in resp.text
    assert 'name="display_name"' in resp.text


def test_save_device_yaml_persists_and_reflects_in_the_form(client):
    yaml_text = (
        "endpoints:\n"
        "  - type: traccar\n"
        "    traccar:\n"
        "      url: http://yaml.example\n"
        "      device_id: yaml-dev\n"
        "    cron: '*/10 * * * *'\n"
    )
    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": yaml_text})
    assert resp.status_code == 200
    assert 'value="http://yaml.example"' in resp.text  # switched back to the form view
    assert "Edit as YAML" in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert saved["endpoints"] == [{
        "type": "traccar",
        "traccar": {"url": "http://yaml.example", "device_id": "yaml-dev"},
        "cron": "*/10 * * * *",
    }]


def test_save_device_yaml_rejects_invalid_yaml_without_persisting(client):
    from webui.forwarders import config_store

    before = config_store.get_device_config(FAKE_CANONIC_ID)

    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": "not: valid: yaml: ["})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert "Edit as form" in resp.text  # still in the YAML view, not switched away

    assert config_store.get_device_config(FAKE_CANONIC_ID) == before


def test_save_device_yaml_rejects_a_non_mapping_document(client):
    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": "- just\n- a\n- list\n"})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text


def test_invalid_cron_is_rejected_without_persisting(client):
    good = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["*/5 * * * *"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert good.status_code == 200

    bad = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name=["My Tracker"],
        endpoint_type=["traccar"],
        cron=["not-a-cron"],
        traccar_url=["http://x"],
        traccar_device_id=["d1"],
        phonetrack_base_url=[""],
        phonetrack_device_name=[""],
    )
    assert bad.status_code == 200
    assert "not a valid cron expression" in bad.text
    assert 'value="http://x"' in bad.text  # typed value preserved in the error re-render

    from webui.forwarders import config_store

    still_saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert still_saved["endpoints"][0]["cron"] == "*/5 * * * *"  # bad save must not have overwritten the good one
