"""Tests for GET /health (webui/main.py) - the readiness check Docker's
HEALTHCHECK polls (see docker/web/healthcheck.py). Each underlying check's
own logic (crashed-task detection, corrupt-file detection, ...) is covered
where it actually lives (tests/test_scheduler.py, tests/test_forwarders.py,
tests/test_token_cache.py) - these tests only cover /health's own job of
aggregating those into a single status."""

import os

from webui import auth_state, config, scheduler
from webui.forwarders import config_store


def test_health_is_ok_by_default(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_reports_a_crashed_scheduler_task(client, monkeypatch):
    monkeypatch.setattr(scheduler, "dead_tasks", lambda: ["some-device"])

    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert "1 device polling task(s) crashed" in body["problems"]


def test_health_reports_a_failed_config_load(client, monkeypatch):
    monkeypatch.setattr(config_store, "last_load_ok", lambda: False)

    resp = client.get("/health")
    assert resp.status_code == 503
    assert "forwarding.yaml failed to load" in resp.json()["problems"]


def test_health_reports_a_failed_auth_store_load(client, monkeypatch):
    monkeypatch.setattr(auth_state, "auth_store_ok", lambda: False)

    resp = client.get("/health")
    assert resp.status_code == 503
    assert "auth.yaml failed to load" in resp.json()["problems"]


def test_health_reports_an_unwritable_data_dir(client, monkeypatch):
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    resp = client.get("/health")
    assert resp.status_code == 503
    assert f"{config.DATA_DIR} is not writable" in resp.json()["problems"]


def test_health_reports_every_problem_at_once(client, monkeypatch):
    monkeypatch.setattr(scheduler, "dead_tasks", lambda: ["a", "b"])
    monkeypatch.setattr(config_store, "last_load_ok", lambda: False)
    monkeypatch.setattr(auth_state, "auth_store_ok", lambda: False)
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["problems"] == [
        "2 device polling task(s) crashed",
        "forwarding.yaml failed to load",
        "auth.yaml failed to load",
        f"{config.DATA_DIR} is not writable",
    ]


def test_health_is_exempt_from_basic_auth(client, monkeypatch):
    monkeypatch.setattr(config, "HTTP_USER", "u")
    monkeypatch.setattr(config, "HTTP_PASSWORD", "p")

    resp = client.get("/health")
    assert resp.status_code in (200, 503)  # never a 401
