"""docker/web/healthcheck.py isn't part of the webui/ package (it's a
standalone script Docker execs directly, excluded from the coverage floor -
see pyproject.toml's [tool.coverage.run]) but it gained real branching logic
once HTTPS_ENABLED existed, so it's worth a light test rather than relying
on production to be the first place a bug in it shows up."""

import importlib.util
import pathlib
import ssl

from webui import config

_HEALTHCHECK_PATH = pathlib.Path(__file__).resolve().parents[1] / "docker" / "web" / "healthcheck.py"


def _load_healthcheck():
    spec = importlib.util.spec_from_file_location("_healthcheck_under_test", _HEALTHCHECK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheme_and_context_is_plain_http_by_default(monkeypatch):
    monkeypatch.setattr(config, "HTTPS_ENABLED", False)
    healthcheck = _load_healthcheck()

    scheme, context = healthcheck._scheme_and_context()
    assert scheme == "http"
    assert context is None


def test_scheme_and_context_disables_verification_for_https(monkeypatch):
    monkeypatch.setattr(config, "HTTPS_ENABLED", True)
    healthcheck = _load_healthcheck()

    scheme, context = healthcheck._scheme_and_context()
    assert scheme == "https"
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE
