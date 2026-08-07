import pytest

from NovaApi import nova_request as nova_request_module
from NovaApi.nova_request import nova_request


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text
        self.content = b"\xde\xad\xbe\xef"


@pytest.fixture(autouse=True)
def stub_auth(monkeypatch):
    monkeypatch.setattr(nova_request_module, "get_username", lambda: "user@example.com")
    monkeypatch.setattr(nova_request_module, "get_adm_token", lambda username: "fake-token")


def test_nova_request_returns_hex_content_on_success(monkeypatch):
    monkeypatch.setattr(
        nova_request_module.requests, "post", lambda *a, **kw: FakeResponse(200),
    )
    assert nova_request("someScope", "00") == "deadbeef"


def test_nova_request_raises_with_a_clear_message_on_failure(monkeypatch):
    monkeypatch.setattr(
        nova_request_module.requests, "post",
        lambda *a, **kw: FakeResponse(403, "<html><body>Forbidden</body></html>"),
    )
    with pytest.raises(RuntimeError, match="403"):
        nova_request("someScope", "00")
