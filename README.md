# GoogleFindMyTools

This repository includes some useful tools that reimplement parts of Google's Find My Device Network (now called Find Hub Network). Note that the code of this repo is still very experimental.

### What's possible?
Currently, it is possible to query Find My Device / Find Hub trackers and Android devices, read out their E2EE keys, and decrypt encrypted locations sent from the Find My Device / Find Hub network. You can also send register your own ESP32- or Zephyr-based trackers, as described below.

### How to use

> [!CAUTION]
> Before starting, ensure you have Chrome and Python updated.
> 
> **If Chrome is not up to date, the script will NOT work, guaranteed!**

- Clone this repository: `git clone` or download the ZIP file
- Change into the directory: `cd GoogleFindMyTools`
- Optional: Create venv: `python -m venv venv`
- Optional: Activate venv: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Linux & macOS)
- Install all required packages: `pip install -r requirements.txt`
- Install the latest version of Google Chrome: https://www.google.com/chrome/
- Start the program by running [main.py](main.py): `python main.py` or `python3 main.py`

### Authentication

On the first run, an authentication sequence is executed, which requires a computer with access to Google Chrome.

The authentication results are stored in `Auth/secrets.json`. If you intend to run this tool on a headless machine, you can just copy this file to avoid having to use Chrome.

### Web UI

This repo also includes an optional local web UI (`webui/`) for everyday use: a device list, a live map for locating trackers, sound start/stop, custom tracker registration, and per-device forwarding of decrypted locations to a Traccar or Nextcloud PhoneTrack server on a configurable schedule, instead of keeping local history.

**Quick start (pre-built image):** `docker compose up -d` pulls the image published by this repo's GitHub Actions workflow (`.github/workflows/docker-publish.yml`) from `ghcr.io/p6g9yhk6/googlefindmytools` - no local build, no Chrome install needed on the host.

**Build from source instead:** `docker compose -f docker-compose.dev.yml up --build`.

Either way, this is a single container, published at `http://localhost:4321`. Chrome and the Xvfb/x11vnc/noVNC stack used for the Google login are **not** baked into the image - they're installed on demand, into an in-memory (tmpfs) directory, the first time a login is triggered, then left in place for the rest of that container's life so later logins skip straight past setup. This keeps the image itself small, but means:
- The container needs outbound network access (to Debian's package mirrors and `storage.googleapis.com`) the first time a login is triggered, not just when the image was built.
- The first sign-in after a container start takes roughly 30-90 seconds before the embedded Chrome view appears, while it installs Xvfb/x11vnc/noVNC and downloads a portable Chrome build. The `/auth` page shows live progress for each step over a WebSocket while this happens. Later sign-ins in the same container are much faster - only the browser/VNC processes themselves restart, not the install.
- A clean container shutdown removes all of it again, leaving no trace behind; give it a bit of time to do so (`docker compose down`/`stop` already wait long enough via `stop_grace_period` in the compose files - if you stop the container manually, use e.g. `docker stop -t 30` rather than a bare `docker stop`).

To sign in, open `http://localhost:4321/auth` and click "Sign in with Google" - watch the setup progress, then complete the login in the embedded Chrome view that appears on the same page once it's ready. The resulting tokens are written to `Auth/secrets.json` in a Docker volume, exactly like copying `secrets.json` between machines as described below, just automated.

Set a `WEBUI_PASSWORD` environment variable to require a password (any username, HTTP Basic Auth) for the whole web UI, including the embedded login view. Copy `.env.example` to `.env` and fill it in, or run `WEBUI_PASSWORD=yourpassword docker compose up -d`. It's unset by default.

> [!CAUTION]
> Even with `WEBUI_PASSWORD` set, this web UI only adds a single shared password and no HTTPS, and it holds long-lived Google account tokens plus live device location data. It is meant for local/LAN use only. Do not port-forward it or otherwise expose it to the public internet.

#### Publishing the image

Pushing to `main` (or pushing a `v*.*.*` tag) on GitHub runs `.github/workflows/docker-publish.yml`, which builds the image and pushes it to GHCR under this repo automatically - no manual steps beyond a normal `git push`. The first time it runs, the GHCR package is created **private** by default; open the package's settings under your GitHub account's Packages tab and switch visibility to public if you want `docker compose up` to work without `docker login ghcr.io` first.

### Known Issues
- "Your encryption data is locked on your device" is shown if you have never set up Find My Device on an Android device. Solution: Login with your Google Account on an Android device, go to Settings > Google > All Services > Find My Device > Find your offline devices > enable "With network in all areas" or "With network in high-traffic areas only". If "Find your offline devices" is not shown in Settings, you will need to download the Find My Device app from Google's Play Store, and pair a real Find My Device tracker with your device to force-enable the Find My Device network.
- No support for trackers using the P-256 curve and 32-Byte advertisements. Regular trackers don't seem to use this curve at all - I can only confirm that it is used with Sony's WH1000XM5 headphones.
- No support for the authentication process on ARM Linux
- If you receive "ssl.SSLCertVerificationError" when running the script, try to follow [this answer](https://stackoverflow.com/a/53310545).
- Please also consider the issues listed in the [README in the ESP32Firmware folder](ESP32Firmware/README.md) if you want to register custom trackers.

### Firmware for custom ESP32-based trackers
If you want to use an ESP32 as a custom Find My Device tracker, you can find the firmware in the folder ESP32Firmware. To register a new tracker, run main.py and press 'r' if you are asked to. Afterward, follow the instructions on-screen.

For more information, check the [README in the ESP32Firmware folder](ESP32Firmware/README.md).

### Firmware for custom Zephyr-based trackers
If you want to use a Zephyr-supported BLE device (e.g. nRF51/52) as a custom Find My Device tracker, you can find the firmware in the folder ZephyrFirmware. To register a new tracker, run main.py and press 'r' if you are asked to. Afterward, follow the instructions on-screen.

For more information, check the [README in the ZephyrFirmware folder](ZephyrFirmware/README.md).

### iOS App
You can also use my [iOS App](https://testflight.apple.com/join/rGqa2mTe) to access your Find My Device trackers on the go.
