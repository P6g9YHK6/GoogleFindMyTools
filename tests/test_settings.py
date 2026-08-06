from urllib.parse import urlencode

from tests.conftest import FAKE_CANONIC_ID


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
