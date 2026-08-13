from urllib.parse import urlencode

from tests.conftest import FAKE_CANONIC_ID, FAKE_DEVICE_NAME


def _post_form(client, path, **fields):
    """Each field can be a scalar (sent once) or a list (sent once per item,
    same field name repeated) - the latter is how one endpoint's variable-
    length headers rows are posted. A dict collapses duplicate keys, so the
    raw urlencoded body is built by hand instead."""
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
            # Query params go straight in the URL now - no separate params
            # table posted alongside it.
            "ep-0-url": "http://traccar.local:5055/?id={{device_id}}",
            "ep-0-cron": "*/5 * * * *",

            "ep-1-url": "https://nc.local/x/{{device_name}}",
            "ep-1-cron": "0 */2 * * *",

            "ep-2-url": "",  # left blank -> dropped
            "ep-2-cron": "*/10 * * * *",
        },
    )
    assert resp.status_code == 200
    assert resp.text.count('class="endpoint-block"') == 2

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert len(saved["endpoints"]) == 2
    assert "type" not in saved["endpoints"][0]  # a preset is never saved - see presets.py
    assert saved["endpoints"][0]["url"] == "http://traccar.local:5055/?id={{device_id}}"
    assert "params" not in saved["endpoints"][0]
    assert saved["endpoints"][0]["cron"] == "*/5 * * * *"

    assert "type" not in saved["endpoints"][1]
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


def test_device_alias_field_is_blank_by_default_not_prefilled_with_google_name(client):
    """Before any alias is ever saved, the "Device alias" input must start
    empty - not pre-filled with the Google account name as if that had been
    deliberately typed in (see _device_form.html) - the Google name only
    shows up as the field's placeholder."""
    from webui.forwarders import config_store

    # No "display_name" key at all - same as a device that's never been
    # through the settings form (other tests in this file may have already
    # set one for FAKE_CANONIC_ID, so this can't just rely on a fresh device).
    config_store.set_device_config(FAKE_CANONIC_ID, {"endpoints": []})

    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}")
    assert resp.status_code == 200
    assert 'name="display_name" value=""' in resp.text
    assert f'placeholder="{FAKE_DEVICE_NAME}"' in resp.text


def test_device_alias_field_is_blank_for_a_device_that_has_never_been_saved_at_all(client):
    """Same as above, but for a device that's never even been through
    config_store.set_device_config once (the very first time its settings
    row is opened) - _rows' own fallback device_cfg for an unrecognized
    canonic_id must not seed "display_name" with the Google account name
    either, or a save with the field left untouched would silently pin the
    alias to it forever."""
    from webui.forwarders import config_store

    # DATA_DIR is shared for the whole test session (see conftest.py), so an
    # earlier test may have already saved something for FAKE_CANONIC_ID -
    # reset the store to guarantee this test actually exercises the
    # never-configured-at-all path (devices.get(canonic_id) is None in
    # _rows), not just "saved with no display_name key" (already covered
    # above).
    config_store.save({"devices": {}})
    assert config_store.get_device_config(FAKE_CANONIC_ID) is None

    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}")
    assert resp.status_code == 200
    assert 'name="display_name" value=""' in resp.text
    assert f'placeholder="{FAKE_DEVICE_NAME}"' in resp.text

    assert config_store.get_device_config(FAKE_CANONIC_ID) is None  # merely viewing it must not save anything


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


def test_skip_if_already_seen_defaults_on_when_not_submitted(client):
    """Unlike skip_if_close/skip_if_stale, this toggle defaults to *on* -
    not submitting it at all (a brand-new endpoint, or one saved before
    this toggle existed) must not be saved as off."""
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200
    assert "checked" in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert "skip_if_already_seen" not in saved  # absence means on, same as an explicit True


def test_skip_if_already_seen_can_be_turned_off(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{
            "ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *",
            "ep-0-skip_if_already_seen": "0",
        },
    )
    assert resp.status_code == 200

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["skip_if_already_seen"] is False


def test_send_now_forwards_immediately_bypassing_schedule_and_skip(client, monkeypatch):
    from webui import scheduler
    from webui.forwarders import config_store, latest_values_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "method": "GET", "url": "http://x/",
            "headers": {}, "body_type": "none", "body": "", "variables": {},
            "cron": "0 0 1 1 *",  # once a year - would never be due on its own
            "skip_if_close": True,
        }],
    })
    # would normally skip this fix - see latest_values_store, not config_store
    latest_values_store.set_endpoint_state(FAKE_CANONIC_ID, "http://x/", {"last_sent_lat": 1.0, "last_sent_lon": 2.0})

    async def fake_locate_device(canonic_id, name, timeout=None):
        return [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}]

    monkeypatch.setattr(scheduler, "locate_device", fake_locate_device)
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc, name="", alias=None: "ok")

    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/0/send-now")
    assert resp.status_code == 200
    assert "Last forward: ok" in resp.text
    assert "Send now" in resp.text  # the button survives its own swapped-in response

    assert "last_forward_status" not in config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]

    state = latest_values_store.get_endpoint_state(FAKE_CANONIC_ID, "http://x/")
    assert state["last_forward_status"] == "ok"
    assert state["last_sent_lat"] == 1.0
    assert state["last_sent_lon"] == 2.0


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
    assert "type: custom" not in resp.text  # a preset is never saved - see presets.py
    assert "google_name" not in resp.text  # read-only, fed from Google's own device list
    assert "display_name" not in resp.text  # that's the "Device alias" field's job, not the YAML's
    assert "url: http://x/" in resp.text
    assert "Edit as form" in resp.text


def test_device_form_route_switches_back_from_yaml_view(client):
    resp = client.get(f"/settings/devices/{FAKE_CANONIC_ID}")
    assert resp.status_code == 200
    assert "Edit as YAML" in resp.text
    assert 'name="display_name"' in resp.text


def test_edit_as_yaml_button_reflects_unsaved_form_edits_without_persisting(client):
    """The "Edit as YAML" button posts the form's current values (see
    device_yaml_preview_route) - a not-yet-saved edit must show up in the
    YAML it renders, and must not itself write anything to disk."""
    from webui.forwarders import config_store

    before = config_store.get_device_config(FAKE_CANONIC_ID)

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}/yaml/preview",
        display_name="Not Yet Saved Name",
        ep_order=["0"],
        **{"ep-0-url": "http://not-yet-saved.example/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200
    assert "<legend>Not Yet Saved Name" in resp.text  # the heading, not part of the YAML body itself
    assert "url: http://not-yet-saved.example/" in resp.text
    assert "display_name" not in resp.text
    assert "Edit as form" in resp.text

    assert config_store.get_device_config(FAKE_CANONIC_ID) == before


def test_edit_as_form_button_reflects_unsaved_yaml_edits_without_persisting(client):
    """The mirror image of the test above - the YAML view's "Edit as form"
    button posts the textarea's current (possibly not-yet-saved) endpoints
    text (see device_form_preview_route). The alias itself was never part
    of the YAML in the first place (see _to_yaml_doc) - it stays whatever's
    already saved for this device regardless of what's in the textarea."""
    from webui.forwarders import config_store

    _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-url": "http://saved.example/", "ep-0-cron": "*/5 * * * *"},
    )
    before = config_store.get_device_config(FAKE_CANONIC_ID)

    yaml_text = "endpoints:\n  - url: http://not-yet-saved.example/\n    cron: '*/5 * * * *'\n"
    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/form/preview", data={"yaml_text": yaml_text})
    assert resp.status_code == 200
    assert 'value="My Tracker"' in resp.text  # the alias, untouched by the YAML
    assert ">http://not-yet-saved.example/</textarea>" in resp.text  # the not-yet-saved endpoint edit
    assert "Edit as YAML" in resp.text

    assert config_store.get_device_config(FAKE_CANONIC_ID) == before


def test_edit_as_form_button_shows_invalid_yaml_error_without_switching(client):
    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/form/preview", data={"yaml_text": "not: valid: yaml: ["})
    assert resp.status_code == 200
    assert "Invalid YAML" in resp.text
    assert "Edit as form" in resp.text  # still in the YAML view, not switched away


def test_save_device_yaml_persists_and_reflects_in_the_form(client):
    """The alias itself is untouched by a YAML save - see _to_yaml_doc -
    so it should still read back as whatever was already saved for it."""
    _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-url": "http://placeholder/", "ep-0-cron": "*/5 * * * *"},
    )

    yaml_text = (
        "endpoints:\n"
        "  - type: traccar\n"  # ignored on save, never persisted - see _from_yaml_doc
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
    assert ">http://yaml.example</textarea>" in resp.text  # switched back to the form view
    assert "Edit as YAML" in resp.text
    assert "save-toast" in resp.text

    from webui.forwarders import config_store

    saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert saved["display_name"] == "My Tracker"
    assert saved["endpoints"] == [{
        "method": "GET", "url": "http://yaml.example",
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


def test_save_device_yaml_rejects_an_invalid_cron_without_persisting(client):
    from webui.forwarders import config_store

    good_yaml = (
        "endpoints:\n"
        "  - method: GET\n"
        "    url: http://yaml.example\n"
        "    params: {}\n"
        "    headers: {}\n"
        "    body_type: none\n"
        "    body: ''\n"
        "    variables: {}\n"
        "    cron: '*/10 * * * *'\n"
    )
    good = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": good_yaml})
    assert good.status_code == 200
    before = config_store.get_device_config(FAKE_CANONIC_ID)

    bad_yaml = good_yaml.replace("*/10 * * * *", "not-a-cron")
    bad = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": bad_yaml})
    assert bad.status_code == 200
    assert "not a valid cron expression" in bad.text
    assert "Edit as form" in bad.text  # still in the YAML view, not switched away

    # the earlier good save must not have been overwritten by the rejected one
    assert config_store.get_device_config(FAKE_CANONIC_ID) == before


def test_cron_presets_render_with_the_matching_one_preselected(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "0 * * * *"},
    )
    assert resp.status_code == 200
    assert '<option value="0 * * * *" selected>Every hour</option>' in resp.text
    # the advanced/custom builder stays collapsed when a preset matches
    assert 'cron-advanced" open' not in resp.text


def test_cron_presets_fall_back_to_custom_and_expand_for_a_non_preset_value(client):
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "17 3 * * 2"},
    )
    assert resp.status_code == 200
    assert '<option value="" selected>Custom…</option>' in resp.text
    assert '<details class="cron-advanced" open>' in resp.text


def test_cron_preview_route_returns_next_runs_for_a_valid_expression(client):
    resp = client.post("/settings/cron-preview", data={"cron": "*/5 * * * *"})
    assert resp.status_code == 200
    assert "Next runs:" in resp.text
    assert "·" in resp.text  # three separate timestamps joined


def test_cron_preview_route_reports_an_invalid_expression(client):
    resp = client.post("/settings/cron-preview", data={"cron": "not-a-cron"})
    assert resp.status_code == 200
    assert "Not a valid cron expression" in resp.text


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
    assert ">http://x/</textarea>" in bad.text  # typed value preserved in the error re-render

    from webui.forwarders import config_store

    still_saved = config_store.get_device_config(FAKE_CANONIC_ID)
    assert still_saved["endpoints"][0]["cron"] == "*/5 * * * *"  # bad save must not have overwritten the good one


def test_last_forward_status_carries_forward_when_url_is_unchanged(client):
    """Runtime state is keyed by URL, not position (see
    latest_values_store) - a save that keeps the same URL just naturally
    leaves its recorded state alone, no explicit carry-forward needed."""
    from webui.forwarders import config_store, latest_values_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "method": "GET", "url": "http://x/",
            "headers": {}, "body_type": "none", "body": "", "variables": {},
            "cron": "*/5 * * * *",
        }],
    })
    latest_values_store.set_endpoint_state(FAKE_CANONIC_ID, "http://x/", {
        "last_forward_status": "ok", "last_forward_time": 111,
        "last_sent_lat": 1.0, "last_sent_lon": 2.0, "last_sent_fix_time": 100,
    })

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        # same URL, just a different cron - the recorded state should stay
        **{"ep-0-url": "http://x/", "ep-0-cron": "*/10 * * * *"},
    )
    assert resp.status_code == 200

    state = latest_values_store.get_endpoint_state(FAKE_CANONIC_ID, "http://x/")
    assert state["last_forward_status"] == "ok"
    assert state["last_sent_lat"] == 1.0


def test_last_forward_status_resets_when_url_changes(client):
    from webui.forwarders import config_store, latest_values_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "method": "GET", "url": "http://x/",
            "headers": {}, "body_type": "none", "body": "", "variables": {},
            "cron": "*/5 * * * *",
        }],
    })
    latest_values_store.set_endpoint_state(FAKE_CANONIC_ID, "http://x/", {
        "last_forward_status": "ok", "last_forward_time": 111,
    })

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-url": "http://different/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200

    assert latest_values_store.get_endpoint_state(FAKE_CANONIC_ID, "http://different/") == {}
    # the old URL's entry is pruned away on save too, not left dangling
    assert latest_values_store.get_endpoint_state(FAKE_CANONIC_ID, "http://x/") == {}


def test_preset_control_only_appears_on_a_brand_new_endpoint(client):
    """A preset is a one-time template for starting a new endpoint, not a
    saved property of one - see webui/forwarders/presets.py."""
    _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )

    blank = client.get(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/blank")
    assert 'name="ep-__NEW__-endpoint_type"' in blank.text

    existing = client.get(f"/settings/devices/{FAKE_CANONIC_ID}")
    assert 'name="ep-0-endpoint_type"' not in existing.text


def test_posted_preset_type_is_never_saved(client):
    """Whatever gets posted for the (only ever shown on a new block) preset
    dropdown - even from a stale or hand-crafted request against an
    existing endpoint - is ignored; endpoints don't carry a "type" at all."""
    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-endpoint_type": "traccar", "ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200

    from webui.forwarders import config_store

    assert "type" not in config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]


def test_variables_carry_forward_when_url_is_unchanged(client):
    """No form field posts "variables" anymore (the "Custom variables" table
    is gone), but an endpoint saved before that change may still have one -
    a save of its other fields must not silently erase it."""
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "type": "custom", "method": "GET", "url": "http://x/?id={{device_id}}",
            "headers": {}, "body_type": "none", "body": "",
            "variables": {"device_id": "104"}, "cron": "*/5 * * * *",
        }],
    })

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        # same URL, just a different cron - variables should carry forward
        **{"ep-0-url": "http://x/?id={{device_id}}", "ep-0-cron": "*/10 * * * *"},
    )
    assert resp.status_code == 200

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert saved["variables"] == {"device_id": "104"}


def test_variables_do_not_carry_forward_when_url_changes(client):
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "type": "custom", "method": "GET", "url": "http://x/?id={{device_id}}",
            "headers": {}, "body_type": "none", "body": "",
            "variables": {"device_id": "104"}, "cron": "*/5 * * * *",
        }],
    })

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-url": "http://different/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200

    saved = config_store.get_device_config(FAKE_CANONIC_ID)["endpoints"][0]
    assert "variables" not in saved


def test_save_failure_shows_an_error_instead_of_crashing(client, monkeypatch):
    """A genuine persistence failure (not a validation error) must still
    come back as a visible, server-rendered error - not an uncaught 500
    that leaves the browser with no confirmation either way."""
    from webui.forwarders import config_store

    def boom(canonic_id, device_config):
        raise OSError("disk full")

    monkeypatch.setattr(config_store, "set_device_config", boom)

    resp = _post_form(
        client,
        f"/settings/devices/{FAKE_CANONIC_ID}",
        display_name="My Tracker",
        ep_order=["0"],
        **{"ep-0-url": "http://x/", "ep-0-cron": "*/5 * * * *"},
    )
    assert resp.status_code == 200
    assert "Failed to save" in resp.text
    assert "save-toast" not in resp.text


def test_save_device_yaml_failure_shows_an_error_instead_of_crashing(client, monkeypatch):
    from webui.forwarders import config_store

    def boom(canonic_id, device_config):
        raise OSError("disk full")

    monkeypatch.setattr(config_store, "set_device_config", boom)

    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/yaml", data={"yaml_text": "My Tracker:\n  endpoints: []\n"})
    assert resp.status_code == 200
    assert "Failed to save" in resp.text
    assert "save-toast" not in resp.text


def test_send_now_failure_shows_an_error_instead_of_crashing(client, monkeypatch):
    from webui import scheduler
    from webui.forwarders import config_store

    config_store.set_device_config(FAKE_CANONIC_ID, {
        "display_name": "My Tracker",
        "endpoints": [{
            "type": "custom", "method": "GET", "url": "http://x/",
            "headers": {}, "body_type": "none", "body": "", "cron": "*/5 * * * *",
        }],
    })

    async def boom(canonic_id, index):
        raise OSError("disk full")

    monkeypatch.setattr(scheduler, "forward_now", boom)

    resp = client.post(f"/settings/devices/{FAKE_CANONIC_ID}/endpoints/0/send-now")
    assert resp.status_code == 200
    assert "Send failed" in resp.text
