from webui import config, serve, tls


def test_uvicorn_kwargs_are_plain_http_by_default(monkeypatch):
    monkeypatch.setattr(config, "HTTPS_ENABLED", False)

    def fail_if_called():
        raise AssertionError("ensure_cert() should never be called when HTTPS_ENABLED is False")

    monkeypatch.setattr(tls, "ensure_cert", fail_if_called)

    kwargs = serve._uvicorn_kwargs()
    assert kwargs == {"host": "0.0.0.0", "port": 4321}


def test_uvicorn_kwargs_adds_ssl_files_when_https_enabled(monkeypatch):
    monkeypatch.setattr(config, "HTTPS_ENABLED", True)

    calls = []

    def fake_ensure_cert():
        calls.append(1)
        return "/data/tls_cert.pem", "/data/tls_key.pem"

    monkeypatch.setattr(tls, "ensure_cert", fake_ensure_cert)

    kwargs = serve._uvicorn_kwargs()

    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 4321
    assert kwargs["ssl_certfile"] == "/data/tls_cert.pem"
    assert kwargs["ssl_keyfile"] == "/data/tls_key.pem"
    assert len(calls) == 1  # called exactly once, not per-kwarg
