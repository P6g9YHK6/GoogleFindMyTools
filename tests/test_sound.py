from tests.conftest import FAKE_CANONIC_ID
from webui.routers import sound


def test_sound_start(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/start")
    assert resp.status_code == 200
    assert 'action-status--ok' in resp.text
    assert '✓' in resp.text


def test_sound_stop(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/stop")
    assert resp.status_code == 200
    assert 'action-status--ok' in resp.text


def test_sound_invalid_action_is_rejected(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/dance")
    assert resp.status_code == 400


def test_sound_failure_renders_a_warning_glyph_instead_of_a_bare_500(client, monkeypatch):
    """Used to just hand back whatever set_sound() raised as an unhandled
    500 (or, before that, dump its raw JSON return value into the button's
    own label - see webui/routers/sound.py) - a failure now renders the
    same status slot Play sound/Stop sound already swap into, just in its
    error state, with the real reason in the tooltip."""
    async def failing_set_sound(canonic_id, should_start):
        raise RuntimeError("FCM token missing")

    monkeypatch.setattr(sound, "set_sound", failing_set_sound)

    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/start")
    assert resp.status_code == 200
    assert 'action-status--error' in resp.text
    assert 'title="FCM token missing"' in resp.text
