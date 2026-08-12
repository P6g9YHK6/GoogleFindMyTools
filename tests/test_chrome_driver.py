"""Unit tests for chrome_driver.py's version-mismatch hint - detecting the
"session not created: This version of ChromeDriver only supports Chrome
version N" failure undetected_chromedriver's auto-fetched driver can hit
against a host's actual installed Chrome, and surfacing an actionable hint
instead of leaving the raw Selenium message to speak for itself."""

import logging

import pytest

import chrome_driver


@pytest.mark.parametrize("message", [
    "session not created: This version of ChromeDriver only supports Chrome version 150",
    "Message: session not created: probe failed with unhandled error",
])
def test_version_mismatch_hint_detects_known_signatures(message):
    hint = chrome_driver._version_mismatch_hint(Exception(message))
    assert "GFMT_CHROME_BINARY" in hint
    assert "Docker" in hint


def test_version_mismatch_hint_ignores_unrelated_failures():
    assert chrome_driver._version_mismatch_hint(Exception("Chrome not found")) == ""


def test_create_driver_raises_with_the_hint_on_a_version_mismatch(monkeypatch, caplog):
    def raise_version_mismatch(*a, **kw):
        raise Exception(
            "session not created: This version of ChromeDriver only supports "
            "Chrome version 150; Current browser version is 149.0.7827.156"
        )

    monkeypatch.setattr(chrome_driver, "find_chrome", lambda: None)
    monkeypatch.setattr(chrome_driver.uc, "Chrome", raise_version_mismatch)
    monkeypatch.setattr(chrome_driver.os, "system", lambda *a, **kw: None)
    monkeypatch.setattr(chrome_driver.time, "sleep", lambda *a, **kw: None)

    with caplog.at_level(logging.WARNING, logger="chrome_driver"):
        with pytest.raises(Exception, match="GFMT_CHROME_BINARY"):
            chrome_driver.create_driver()

    # both the default and the headless-fallback attempt logged the hint
    assert sum("GFMT_CHROME_BINARY" in r.message for r in caplog.records) >= 2


def test_create_driver_does_not_add_the_hint_for_unrelated_failures(monkeypatch, caplog):
    def raise_plain(*a, **kw):
        raise Exception("Message: unknown error: cannot find Chrome binary")

    monkeypatch.setattr(chrome_driver, "find_chrome", lambda: None)
    monkeypatch.setattr(chrome_driver.uc, "Chrome", raise_plain)
    monkeypatch.setattr(chrome_driver.os, "system", lambda *a, **kw: None)
    monkeypatch.setattr(chrome_driver.time, "sleep", lambda *a, **kw: None)

    with caplog.at_level(logging.WARNING, logger="chrome_driver"):
        with pytest.raises(Exception):
            chrome_driver.create_driver()

    assert "version mismatch" not in caplog.text
