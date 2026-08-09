"""Plain-text Prometheus exposition format at /metrics, hand-rolled rather
than pulling in the prometheus_client dependency for a handful of gauges.

Everything here is derived on each scrape from state the app already keeps
(the bounded forward/system logs, the query gate, the forwarding config) -
nothing new is persisted, and nothing here does any actual work beyond
counting what's already in memory or on disk.
"""

import time

from fastapi import APIRouter, Response

from webui import config, system_log_store
from webui.auth_state import is_logged_in
from webui.deps import query_gate
from webui.forwarders import config_store, log_store

router = APIRouter()

_START_TIME = time.monotonic()

_FORWARD_STATUSES = ("ok", "error", "skipped")
_SYSTEM_LEVELS = ("info", "warning", "error", "critical")


def _forward_status_bucket(status: str) -> str:
    if status == "ok":
        return "ok"
    if status.startswith("error"):
        return "error"
    return "skipped"


def _render() -> str:
    lines = [
        "# HELP gfmt_uptime_seconds Seconds since this process started.",
        "# TYPE gfmt_uptime_seconds counter",
        f"gfmt_uptime_seconds {time.monotonic() - _START_TIME:.0f}",
        "",
        "# HELP gfmt_logged_in Whether a Google account is currently signed in (1) or not (0).",
        "# TYPE gfmt_logged_in gauge",
        f"gfmt_logged_in {1 if is_logged_in() else 0}",
        "",
        "# HELP gfmt_query_gate_waiting Requests currently queued behind the account-wide throttle.",
        "# TYPE gfmt_query_gate_waiting gauge",
        f"gfmt_query_gate_waiting {query_gate.waiting}",
        "",
    ]

    devices = config_store.all_devices()
    endpoint_count = sum(len(d.get("endpoints", [])) for d in devices.values())
    lines += [
        "# HELP gfmt_devices_configured Devices with at least one forwarding endpoint configured.",
        "# TYPE gfmt_devices_configured gauge",
        f"gfmt_devices_configured {len(devices)}",
        "",
        "# HELP gfmt_forwarding_endpoints_configured Forwarding endpoints configured across all devices.",
        "# TYPE gfmt_forwarding_endpoints_configured gauge",
        f"gfmt_forwarding_endpoints_configured {endpoint_count}",
        "",
    ]

    # Counts every entry the bounded forward/system logs currently retain
    # (see webui/forwarders/log_store.py / webui/system_log_store.py for the
    # cap) - not a running total since process start, and not unbounded
    # history either, just "what's visible on the Logs page right now".
    forward_counts = dict.fromkeys(_FORWARD_STATUSES, 0)
    for entry in log_store.recent_entries(limit=config.FORWARD_LOG_MAX_ENTRIES):
        forward_counts[_forward_status_bucket(entry["status"])] += 1

    lines += [
        "# HELP gfmt_forward_log_entries Forwarding Log entries currently retained, by outcome.",
        "# TYPE gfmt_forward_log_entries gauge",
    ]
    for status, count in forward_counts.items():
        lines.append(f'gfmt_forward_log_entries{{status="{status}"}} {count}')
    lines.append("")

    system_counts = dict.fromkeys(_SYSTEM_LEVELS, 0)
    for entry in system_log_store.recent_entries(limit=config.SYSTEM_LOG_MAX_ENTRIES):
        level = entry["level"].lower()
        system_counts[level] = system_counts.get(level, 0) + 1

    lines += [
        "# HELP gfmt_system_log_entries System Log entries currently retained, by level.",
        "# TYPE gfmt_system_log_entries gauge",
    ]
    for level, count in system_counts.items():
        lines.append(f'gfmt_system_log_entries{{level="{level}"}} {count}')
    lines.append("")

    return "\n".join(lines)


@router.get("/metrics")
async def metrics():
    return Response(_render(), media_type="text/plain; version=0.0.4; charset=utf-8")
