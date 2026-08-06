def test_register_form(client):
    resp = client.get("/register")
    assert resp.status_code == 200


def test_register_submit(client):
    resp = client.post("/register")
    assert resp.status_code == 200
    assert "deadbeef" in resp.text
