# GoogleFindMyTools

[![Lint and test](https://github.com/P6g9YHK6/GoogleFindMyTools/actions/workflows/test.yml/badge.svg)](https://github.com/P6g9YHK6/GoogleFindMyTools/actions/workflows/test.yml)

A self-hosted app that logs into your Google account, keeps polling your Find My Device trackers and Android phones, and forwards each new location to your own Traccar or Nextcloud PhoneTrack server - so you keep your location history on your own infrastructure instead of Google's. One Docker container, a web UI, nothing else to run.

It's built on top of [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools), the original reverse-engineering work that figured out how to talk to Google's Find My Device / Find Hub network at the protocol level (querying trackers, decrypting end-to-end encrypted locations, registering custom ESP32/Zephyr trackers). That original tool is still in here and still works as a set of Python scripts - see [Advanced: running it as a CLI tool](#advanced-running-it-as-a-cli-tool) below. Everything described in the rest of this README is a self-hosted app built around it: a web UI, a scheduler, multi-destination forwarding, and the operational stuff (logging, throttling, auth, encryption at rest) a service you actually leave running needs.

> [!CAUTION]
> This holds long-lived Google account tokens and live device location data. It's meant for local/LAN use - see [Security](#security) below before exposing it any further than that.

## Features

- **Devices page** - every tracker and phone on your account, in one list. Manual "Locate" and "Play sound" buttons, plus whatever the last scheduled poll found. Shows last-seen time for phones and tags alike.
- **Scheduled forwarding, not a one-off export** - each device polls on its own cron schedule and forwards to as many destinations as you want, each with its own schedule and its own alias. Every destination is really the same generic HTTP request builder (method, URL, headers, query params, body, all with `{{latitude}}`-style placeholders) - Traccar and Nextcloud PhoneTrack are just presets that pre-fill it, so you can add a custom endpoint (a different self-hosted service, a webhook, whatever takes HTTP) without waiting on this project to add it by name.
- **Skip pointless updates** - two independent, opt-in gates per destination: skip sending if the device hasn't moved far enough, and skip re-sending the same stale cached fix Google keeps returning. Both are local math (haversine distance), no external API calls, no extra cost.
- **Forwarding Log** - every attempt, every device, every destination, with the exact payload sent and whether it succeeded - so a silent failure on your Traccar server's end doesn't stay silent here.
- **System Log + error notifications** - every warning/error anywhere in the app (a failed locate, an expired token, a forwarding failure) is captured in a searchable in-app log and can be pushed out live through [Apprise](https://github.com/caronc/apprise) to whatever you already use (ntfy, Discord, Telegram, Pushover, email, 100+ others) - configured from the Config page, no restart needed.
- **Register your own trackers** - pair a custom ESP32- or Zephyr-based BLE tracker straight from the web UI.
- **Account-wide rate limiting** - every call to Google's backend (device list, locate, sound, register) goes through one shared throttle, tunable live from the Config page, so a burst of manual clicks and every device's poll loop can never combine into something that gets your account flagged.
- **Everything survives a restart** - device/forwarding config, the last known location per device, and every log all live in one plain-YAML data directory you mount as a volume. No database to run. The Forwarding Log and System Log are each capped at a fixed number of entries (`FORWARD_LOG_MAX_ENTRIES` / `SYSTEM_LOG_MAX_ENTRIES`) - oldest entries roll off automatically rather than growing either file forever.
- **`/metrics`** - a small set of Prometheus-format gauges (uptime, sign-in status, query-throttle queue depth, forwarding/system log entry counts by outcome) if you already scrape other self-hosted services and want this one in the same dashboard. Behind the same Basic Auth as everything else when configured.

## Quick start

```
docker compose up -d
```

This pulls the pre-built image from `ghcr.io/p6g9yhk6/googlefindmytools` - no local build, no Chrome install on the host. Then open `http://localhost:4321` and go to **Config** → **Sign in with Google**.

Chrome and the Xvfb/x11vnc/noVNC stack needed for that one-time Google login aren't baked into the image - they install on demand into an in-memory directory the first time you sign in (adds ~30-90 seconds to that first sign-in only; later sign-ins skip straight past it). The Config page shows live progress while this happens, and you complete the actual Google login in an embedded browser view right there on the page - no separate machine, no VNC client needed.

Building from source instead: `docker compose -f docker-compose.dev.yml up --build`.

## Configuration

Copy `.env.example` to `.env` and fill in what you need, or pass these directly to `docker run`/`docker compose`. Everything is optional - the defaults are a reasonable, auth-free single-user setup.

| Variable | Default | What it does |
|---|---|---|
| `HTTP_USER` / `HTTP_PASSWORD` | unset | Set both to require this username/password pair (HTTP Basic Auth) for the whole web UI, including the embedded login view. |
| `SECRETS_ENCRYPTION_KEY` | unset | Any string. When set, every credential in `auth.yaml` (OAuth tokens, FCM credentials, vault keys, ...) is encrypted at rest (AES-256-GCM). Unset keeps the old plain-text behavior and logs a one-time startup warning saying so. Losing/changing this makes existing encrypted values unreadable; you'd need to sign in again to regenerate them. |
| `TZ` | UTC | Timezone for timestamps shown in the UI and logs. |
| `GFMT_DATA_DIR` | `/data` (in the container) | Where all persisted state lives: device/forwarding config, credentials, location history, logs - one flat directory, just mount a volume onto it. |
| `DEFAULT_POLL_INTERVAL_S` | 300 | Fallback poll interval for a newly added device before you set its own cron schedule. |
| `LOCATE_CONCURRENCY` | 5 | Max number of devices being actively located at once. |
| `LOCATE_TIMEOUT_S` | 60 | How long to wait for a single locate before giving up. |
| `QUERY_THROTTLE_MAX` / `QUERY_THROTTLE_WINDOW_S` / `QUERY_MIN_SPREAD_S` | 20 / 60 / 1 | Account-wide rate limit against Google's backend. Also editable live from the Config page - no restart needed. |
| `HTTPS_ENABLED` | unset | Set to `1` to serve HTTPS instead of HTTP on the same port, using a self-signed certificate generated automatically on first start and reused after that (not regenerated every restart). See [Security](#security). |
| `GFMT_TLS_CERT_PATH` / `GFMT_TLS_KEY_PATH` | unset | Bring your own cert/key instead of the self-signed one - both must point at existing files, or startup fails rather than silently falling back to self-signed. |
| `GFMT_TLS_SAN` | unset | Comma-separated extra hostnames/IPs to add to the generated self-signed cert (it always covers `localhost`/`127.0.0.1`/`::1`) - set this to your LAN hostname or static IP if you reach the box by either. |
| `GFMT_TLS_VALIDITY_DAYS` | 825 | How long a generated self-signed cert is valid for. Defaults to Apple's ATS cap (Safari/iOS/macOS reject longer-lived certs even after you manually trust them) - raise it if you don't care about Safari. |

The Config page also has fields for the query throttle and Apprise notification settings, applied immediately without a restart.

## Using it

- **Devices** (`/`) - list, locate, play sound, last-seen.
- **Register Tracker** (`/register`) - pair a custom ESP32/Zephyr BLE tracker.
- **Forwarding Settings** (`/settings`) - per device: display name/alias, and any number of forwarding endpoints. Each endpoint is a query builder (method, URL, headers, params, body) that a preset (Traccar, Nextcloud PhoneTrack, or Custom) pre-fills and you can still tweak freely, plus its own cron schedule, alias, device-name override, and skip-if-close / skip-if-stale thresholds. Unsaved edits are flagged, and there's a raw YAML editor for anything the form doesn't cover.
- **Forwarding Log** (`/logs`) - every forward attempt, its target, status, and the exact payload sent.
- **System Log** (`/logs/system`) - every warning/error anywhere in the app.
- **Config** (`/auth`) - sign in/out, credential status, query throttle, and Apprise notification settings.
- **Metrics** (`/metrics`) - Prometheus-format text, for scraping rather than browsing.

## Security

> [!CAUTION]
> By default this is plain HTTP with no auth - meant for a trusted LAN (or behind your own reverse proxy/VPN if you need remote access), not exposed directly to the public internet. `HTTPS_ENABLED=1` gets you transport encryption (see below), but self-signed TLS still isn't the same as a real reverse proxy or VPN for anything beyond casual LAN use.

- Set `HTTP_USER`/`HTTP_PASSWORD` to gate the whole UI, including `/docs` (FastAPI's interactive API explorer) - it's one more route behind the same middleware, not a separate hole.
- Set `HTTPS_ENABLED=1` to serve HTTPS with an automatically generated, persisted self-signed certificate - no separate reverse proxy needed. Your browser will show a one-time "not trusted" warning the first time (expected for any self-signed cert, not a sign something's wrong) - accept/pin it, or point `GFMT_TLS_CERT_PATH`/`GFMT_TLS_KEY_PATH` at a real cert instead if you have one. This defeats passive network snooping but gives no identity guarantee the way a CA-signed cert does. It's a toggle, not a dual mode - with it on, plain `http://` to the same port gets a connection reset, not a redirect.
- Set `SECRETS_ENCRYPTION_KEY` to encrypt credentials at rest instead of plain YAML. Back this up somewhere alongside (or independent of) your `GFMT_DATA_DIR` volume: it's not stored anywhere itself, and losing or changing it makes every already-encrypted value in `auth.yaml` permanently unreadable - your only recovery is signing in again from scratch, not restoring the key.
- Everything - config, credentials, logs - lives in the one data directory you control; nothing phones home except to Google's own APIs and (if you configure it) your Apprise notification targets.

## Publishing the image

Pushing to `main` (or pushing a `v*.*.*` tag) runs `.github/workflows/docker-publish.yml`, which builds and pushes the image to GHCR automatically - no manual steps beyond a normal `git push`. The first time it runs, the GHCR package is created **private** by default; switch it to public under your GitHub account's Packages tab if you want `docker compose up` to work without `docker login ghcr.io` first.

## Development

`.github/workflows/test.yml` lints and runs the test suite on every push and pull request. To run it locally:
```
pip install -r requirements.txt -r requirements-web.txt -r requirements-dev.txt
ruff check .
pytest
```

## Advanced: running it as a CLI tool

The original scripts this project is built on still work standalone, without Docker or the web UI - useful for scripting or if you just want to query a device once.

> [!CAUTION]
> Before starting, ensure Chrome and Python are up to date - if Chrome isn't current, this will not work.

- Clone this repository: `git clone` or download the ZIP file
- `cd GoogleFindMyTools`
- Optional: create/activate a venv (`python -m venv venv`, then `venv\Scripts\activate` on Windows or `source venv/bin/activate` on Linux/macOS)
- `pip install -r requirements.txt`
- Install the latest [Google Chrome](https://www.google.com/chrome/)
- `python main.py`

On first run this walks you through the same Google sign-in as the web UI, storing the result in `Auth/auth.yaml` - copy that file to run on a headless machine without Chrome. (Upgrading from an older version that still has `Auth/secrets.json` migrates it automatically the first time it's read; the old file is left in place, untouched.) `SECRETS_ENCRYPTION_KEY` (see [Configuration](#configuration)) applies here too.
