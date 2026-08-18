# Architecture

This is a map of how the pieces fit together, for anyone new to the code who
wants more than one-line docstrings scattered across two dozen files. It
doesn't replace those docstrings/comments - read the file itself for the
"why" behind any specific piece; this is just the "where do I look" layer.

## Two layers

**The original CLI tool** (`Auth/`, `NovaApi/`, `SpotApi/`, `ProtoDecoders/`,
`FMDNCrypto/`, `KeyBackup/`, `DULT/`) is the reverse-engineered protocol
layer: logging into Google, talking to the Find My Device / Find Hub
backend, decrypting end-to-end encrypted location reports, registering
custom BLE trackers. It works standalone as a set of scripts (`main.py` and
the `if __name__ == "__main__"` entrypoints throughout `Auth/`) and doesn't
know the web app exists.

**The web app** (`webui/`) is everything built around that: a FastAPI app
that logs in through the same code above, polls devices on a schedule, and
forwards their locations to your own server. Nothing under `webui/` talks
to Google directly - it always goes through the CLI-tool layer.

## `webui/` layout

- `main.py` - FastAPI app object, middleware, router registration, the
  `/health` liveness route, and the two WebSocket endpoints
  (`/ws/locations` for live location pushes, `/ws/provision` for the
  browser-provisioning progress feed).
- `config.py` - every env-var-configurable knob, in one place with comments
  on what each one is for. Start here when you're trying to find out how
  something is configured.
- `deps.py` - `run_blocking()`/`QueryGate`: the one choke point every
  blocking call to Google's backend goes through, so the account-wide rate
  limit (`QUERY_THROTTLE_*`) actually applies everywhere at once.
- `scheduler.py` - the cron-driven poll loop per device: one
  `asyncio.Task` per device (see `_poll_device`), sleeping until the next
  endpoint's cron fires, locating, then forwarding to each due endpoint
  (skip-if-close / skip-if-stale gates included).
- `auth_state.py` / `browser_provisioning.py` / `browser_stack.py` - the web
  login flow, split into the sign-in state machine (`browser_provisioning.py`
  - what phase it's in, when to tear down, pushing progress live over
  `/ws/provision`) and the Chrome-in-Xvfb-in-noVNC stack that state machine
  drives (`browser_stack.py` - installing, launching, and killing the actual
  processes, provisioned on demand and torn down after each sign-in attempt
  but left installed/downloaded for the rest of the container's life). See
  each module's own docstring for specifics.
- `auth_middleware.py` - optional HTTP Basic Auth gating the whole ASGI
  app (HTTP and WebSocket alike), a no-op unless both `HTTP_USER` and
  `HTTP_PASSWORD` are set.
- `tls.py` / `serve.py` - optional self-signed HTTPS. `tls.py`'s
  `ensure_cert()` generates and persists a cert (or validates a
  bring-your-own one), `serve.py` is the Docker image's actual entrypoint
  (see `docker/web/Dockerfile`'s `CMD`) that wires the cert into uvicorn
  when `HTTPS_ENABLED` is set - a no-op wrapper around a plain uvicorn
  invocation otherwise.
- `settings_store.py` - persisted overrides (`config.yaml`) for things that
  used to be env-var-only (query throttle, Apprise settings), editable live
  from the Config page.
- `device_location_store.py` - the last location actually fetched per
  device, regardless of source (manual click or cron poll) - what the
  Devices page shows.
- `system_log_store.py` + `log_capture.py` - every INFO+ log record
  app-wide, captured via a root logging handler and stored bounded, for the
  System Log page.
- `notify.py` - optional Apprise push notifications, also attached to the
  root logger, so any WARNING+ anywhere in the app (not just `webui.*`) can
  be pushed out live.
- `staleness.py` - per-device staleness alerting: is the newest fix on file
  for a device older than the threshold it's configured with, on its own
  independent sweep (a device with no forwarding endpoints is never polled
  by `scheduler.py` at all, so this can't piggyback on that loop). Config
  and alert-dedup state live in `forwarders/latest_values_store.py`, not
  here - see that module's own comment for why.
- `geo.py` - the one pure-math helper (haversine distance), used by the
  scheduler's skip-if-close gate.
- `ws.py` / `templating.py` - thin shared infrastructure: the WebSocket
  connection managers behind `/ws/*`, and the Jinja2 environment behind
  every `TemplateResponse`.

### `webui/forwarders/`

Everything about *where* a location goes, separate from *when* (that's
`scheduler.py`'s job):

- `config_store.py` - persisted per-device forwarding config: which
  endpoints, their schedules, thresholds.
- `policy.py` - the skip-if-close/skip-if-stale gates, the dispatch-and-log
  call every endpoint goes through, and consecutive-failure escalation.
  Everything about *where* a location goes and whether this particular fix
  is worth sending, with no idea of cron schedules or *when* it's called -
  that's `webui/scheduler.py`, built on top of this.
- `custom.py` - the one generic HTTP request builder every endpoint sends
  through (method/URL/headers/params/body, all with `{{variable}}`
  templating).
- `presets.py` - Traccar/Nextcloud PhoneTrack/Custom are just presets that
  pre-fill the generic builder above, not separate code paths.
- `log_store.py` - the Forwarding Log: every attempt, its target, status,
  and payload.
- `latest_values_store.py` - per-endpoint-URL forwarding runtime state, plus
  each device's staleness config/alert-dedup state - see
  `webui/staleness.py`.

`config_store.py`, `webui/device_location_store.py` (the Devices page's last
known fix per device) and `latest_values_store.py` all persist through the
shared `webui/device_store.py` - one file (`devices.yaml`), keyed by canonic
device ID, one sub-key per module (`config`/`location`/`endpoint_state`/
`staleness`), one lock. They used to be three independent YAML files; see
that module's docstring for why they were fused and how the pre-fusion files
get migrated in.

### `webui/routers/`

One module per URL area, thin by design - they call into the modules above
rather than holding logic themselves: `devices.py` (`/`), `locate.py`
(manual locate), `sound.py` (play sound), `register.py` (pair a tracker),
`settings.py` (forwarding config UI - the actual row-fetching/YAML-
conversion/form-parsing logic lives in `webui/forwarders/settings_service.py`,
keeping the router itself thin like every other one here),
`staleness.py` (the Staleness page -
per-device staleness alert config, separate from `settings.py`'s forwarding
config), `logs.py` (Forwarding Log + System Log pages), `auth.py` (sign
in/out, the Config page), `vnc_proxy.py` (proxies the embedded browser view
through the app's own origin instead of exposing noVNC directly),
`metrics.py` (`/metrics` - Prometheus text, derived on each scrape from
state the app already keeps, nothing new persisted).

## Data on disk

Everything persisted lives flat in one directory (`GFMT_DATA_DIR`, `/data`
in the Docker image): `auth.yaml` (credentials, optionally encrypted - see
`Auth/token_cache.py`), `devices.yaml`, `config.yaml`, `forward.log`,
`system.log`. No database - see the README's "Everything survives a
restart" feature bullet for why.

## Tests

`tests/conftest.py` explains the one non-obvious rule the whole suite
depends on: patches target where a name is *looked up* (the router module
that did `from webui.deps import X`), not where it's defined. Read that
docstring before writing a new router test.
