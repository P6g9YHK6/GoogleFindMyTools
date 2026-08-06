from tests.conftest import FAKE_CANONIC_ID


def test_sound_start(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/start")
    assert resp.status_code == 200


def test_sound_stop(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/stop")
    assert resp.status_code == 200


def test_sound_invalid_action_is_rejected(client):
    resp = client.post(f"/devices/{FAKE_CANONIC_ID}/sound/dance")
    assert resp.status_code == 400
