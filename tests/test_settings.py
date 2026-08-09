from urllib.parse import urlencode

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME


def _post_form(client, path, **fields):
    """Each field can be a scalar (sent once) or a list (sent once per item,
    same field name repeated) - the latter is how one endpoint's variable-
    length params/headers/variables rows are posted. A dict collapses
    duplicate keys, so the raw urlencoded body is built by hand instead."""
    pairs = []
    for key, value in fields.items():
        if isinstance(value, (list, tuple)):
            pairs.extend((key, v) for v in value)
        else:
            pairs.append((key, value))
    return client.post(path, content=urlencode(pairs), headers={"content-type": "application/x-www-form-urlencoded"})


def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_blank_endpoint_route(client):
    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/blank")
    assert resp.status_code == 200
    assert 'data-ep-idx="__NEW__"' in resp.text
    assert "Not yet saved" in resp.text
    assert 'name="ep-__NEW__-url"' in resp.text


def test_save_mixed_endpoints_and_drop_blank_block(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0", "1", "2"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://traccar.local:5055/",
            "ep-0-cron": "*/5 * * * *",
            "ep-0-param_key": ["id"], "ep-0-param_value": ["{{device_id}}"],
            "ep-0-var_key": ["device_id"], "ep-0-var_value": ["dev1"],

            "ep-1-endpoint_type": "phonetrack", "ep-1-url": "https://nc.local/x/{{device_name}}",
            "ep-1-cron": "0 */2 * * *",

            "ep-2-endpoint_type": "custom", "ep-2-url": "",  # left blank -> dropped
            "ep-2-cron": "*/10 * * * *",
        },
    )
    assert resp.status_code == 200
    assert resp.text.count('class="endpoint-block"') == 2

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert len(saved["endpoints"]) == 2
    assert saved["endpoints"][0]["type"] == "traccar"
    assert saved["endpoints"][0]["url"] == "http://traccar.local:5055/"
    assert saved["endpoints"][0]["params"] == {"id": "{{device_id}}"}
    assert saved["endpoints"][0]["variables"] == {"device_id": "dev1"}
    assert saved["endpoints"][0]["cron"] == "*/5 * * * *"

    assert saved["endpoints"][1]["type"] == "phonetrack"
    assert saved["endpoints"][1]["url"] == "https://nc.local/x/{{device_name}}"
    assert "device_name" not in saved["endpoints"][1]
    assert saved["endpoints"][1]["cron"] == "0 */2 * * *"


def test_save_response_is_only_the_one_device_row(client):
    """A save must swap outerHTML into a single <form>, not hand back the
    whole multi-device page (which would duplicate every row on screen)."""
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200
    assert resp.text.count("<form") == 1
    assert "Forwarding Settings" not in resp.text  # page heading, not part of the row fragment
    assert "endpoint_fields.js" not in resp.text  # page-level script tag, not part of the row fragment


def test_save_shows_a_confirmation_toast(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200
    assert "save-toast" in resp.text


def test_device_alias_overrides_confusing_google_name(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="Garage Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
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
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *",
            "ep-0-alias": "Home Traccar",
        },
    )
    assert resp.status_code == 200
    assert "Home Traccar" in resp.text

    from webui.forwarders import config_store

    assert config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]["alias"] == "Home Traccar"


def test_endpoint_device_name_is_not_a_saveable_field(client):
    """There's no per-endpoint "Device name" override anymore -
    {{device_name}}/{{device_alias}} always resolve to the device's own
    real alias (see webui/forwarders/custom.py) - a posted "device_name"
    field (e.g. from a stale cached page) must be ignored, not saved."""
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "phonetrack", "ep-0-url": "https://nc.local/x/{{device_name}}",
            "ep-0-cron": "*/5 * * * *", "ep-0-device_name": "phone1",
        },
    )
    assert resp.status_code == 200
    from webui.forwarders import config_store

    assert "device_name" not in config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]


def test_endpoint_method_headers_and_body_are_saved(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "custom", "ep-0-method": "post", "ep-0-url": "http://x/",
            "ep-0-cron": "*/5 * * * *",
            "ep-0-header_key": ["Authorization"], "ep-0-header_value": ["Bearer tok"],
            "ep-0-body_type": "json", "ep-0-body": '{"lat": {{latitude}}}',
        },
    )
    assert resp.status_code == 200

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["method"] == "POST"  # normalized to upper-case
    assert saved["headers"] == {"Authorization": "Bearer tok"}
    assert saved["body_type"] == "json"
    assert saved["body"] == '{"lat": {{latitude}}}'


def test_skip_if_close_toggle_and_threshold_are_saved(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *",
            "ep-0-skip_if_close": "1", "ep-0-min_movement_m": "75",
        },
    )
    assert resp.status_code == 200
    assert "checked" in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["skip_if_close"] is True
    assert saved["min_movement_m"] == 75.0


def test_skip_if_close_defaults_off_when_not_submitted(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *",
            "ep-0-skip_if_close": "0",
        },
    )
    assert resp.status_code == 200

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert "skip_if_close" not in saved


def test_skip_if_stale_toggle_and_gap_are_saved(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *",
            "ep-0-skip_if_stale": "1", "ep-0-min_update_gap_m": "15",
        },
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
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *",
            "ep-0-skip_if_stale": "0",
        },
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
            "type": "traccar", "method": "GET", "url": "http://x/",
            "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {},
            "cron": "0 0 1 1 *",  # once a year - would never be due on its own
            "skip_if_close": True, "last_sent_lat": 1.0, "last_sent_lon": 2.0,  # would normally skip this fix
        }],
    })

    async def fake_locate_device(canonic_id, name, timeout=None):
        return [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}]

    monkeypatch.setattr(scheduler, "locate_device", fake_locate_device)
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc, name="": "ok")

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
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )

    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}/yaml")
    assert resp.status_code == 200
    assert "type: traccar" in resp.text
    assert "url: http://x/" in resp.text
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
        "    method: GET\n"
        "    url: http://yaml.example\n"
        "    params: {}\n"
        "    headers: {}\n"
        "    body_type: none\n"
        "    body: ''\n"
        "    variables: {device_id: yaml-dev}\n"
        "    cron: '*/10 * * * *'\n"
    )
    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": yaml_text})
    assert resp.status_code == 200
    assert 'value="http://yaml.example"' in resp.text  # switched back to the form view
    assert "Edit as YAML" in resp.text
    assert "save-toast" in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert saved["endpoints"] == [{
        "type": "traccar", "method": "GET", "url": "http://yaml.example",
        "params": {}, "headers": {}, "body_type": "none", "body": "",
        "variables": {"device_id": "yaml-dev"}, "cron": "*/10 * * * *",
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
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )
    assert good.status_code == 200

    bad = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "not-a-cron"},
    )
    assert bad.status_code == 200
    assert "not a valid cron expression" in bad.text
    assert 'value="http://x/"' in bad.text  # typed value preserved in the error re-render

    from webui.forwarders import config_store

    still_saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert still_saved["endpoints"][0]["cron"] == "*/5 * * * *"  # bad save must not have overwritten the good one


def test_last_forward_status_carries_forward_when_url_is_unchanged(client):
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "type": "traccar", "method": "GET", "url": "http://x/",
            "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {},
            "cron": "*/5 * * * *", "last_forward_status": "ok", "last_forward_time": 111,
            "last_sent_lat": 1.0, "last_sent_lon": 2.0, "last_sent_fix_time": 100,
        }],
    })

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        # same URL, just a different cron - should carry the last-* fields forward
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/10 * * * *"},
    )
    assert resp.status_code == 200

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["last_forward_status"] == "ok"
    assert saved["last_sent_lat"] == 1.0


def test_last_forward_status_resets_when_url_changes(client):
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "type": "traccar", "method": "GET", "url": "http://x/",
            "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {},
            "cron": "*/5 * * * *", "last_forward_status": "ok", "last_forward_time": 111,
        }],
    })

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://different/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert "last_forward_status" not in saved
