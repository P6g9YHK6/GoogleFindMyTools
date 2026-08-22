# Build context is the repo root: docker build -f docker/web/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

# requirements.lock is the fully pinned, hash-checked resolution of
# requirements.txt + requirements-web.txt (see CONTRIBUTING.md for how to
# regenerate it) - installing from it instead of the loose *.txt files means
# a rebuild of this exact commit always gets the exact same dependency
# versions, not whatever happens to be newest on the day it's built.
COPY requirements.lock /app/
RUN pip install --no-cache-dir -r requirements.lock

# Only what's needed to run apt-get itself at runtime (ca-certificates for the
# HTTPS downloads, procps for pkill during teardown), to actually install
# xvfb/x11vnc/novnc/websockify on demand, and git to clone ESP-IDF on demand
# (see webui/esp_idf_provisioning.py). Chrome and the ESP-IDF toolchain itself
# are both fetched at runtime, not via apt, and neither the browser/X11/VNC
# stack nor ESP-IDF is baked into this image - see webui/browser_provisioning.py
# and webui/esp_idf_provisioning.py.
#
# libusb-1.0-0 is ESP-IDF's own runtime dependency, not this app's: the
# openocd-esp32 tool that install.sh pulls in dlopen's libusb at startup, and
# idf_tools.py export sanity-checks every installed tool by running it -
# without this, that check fails ("error while loading shared libraries:
# libusb-1.0.so.0") and export aborts before printing anything to source env
# vars from, even though openocd (JTAG debugging) itself is never actually
# used by a build/merge-bin here.
#
# cmake/ninja-build/ccache/dfu-util/libffi-dev/libssl-dev/wget/flex/bison/
# gperf are ESP-IDF's own documented Linux prerequisites - install.sh only
# fetches the cross-compiler toolchains and debug tools (xtensa-esp32-elf,
# riscv32-esp-elf, openocd, gdb, ...), it never bundles cmake/ninja
# themselves, those are expected to already be on the system. Without them,
# `idf.py set-target` fails outright ("cmake" must be available on the PATH).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates procps tzdata git libusb-1.0-0 \
        cmake ninja-build ccache dfu-util libffi-dev libssl-dev wget flex bison gperf \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# GFMT_SECRETS_DIR is deliberately not set here - Auth/token_cache.py falls
# back to GFMT_DATA_DIR when it's unset, so everything (auth.yaml alongside
# config.yaml/forwarding.yaml/forward.log/...) lands flat in one directory,
# no subfolders, matching the single `-v .../data:/data` mount below.
#
# GFMT_BUILD_SHA/GFMT_BUILD_DATE/GFMT_BUILD_BRANCH identify what's actually
# running (shown in the web UI's footer, see webui/templating.py) without the
# running container having to read back its own image's OCI labels. Only set
# by .github/workflows/docker-publish.yml via --build-arg; a plain local
# `docker build` (or docker-compose.dev.yml) leaves all three at their
# defaults, which the footer treats as "no real commit to link to" / "no
# branch to show".
ARG GFMT_BUILD_SHA=dev
ARG GFMT_BUILD_DATE=
ARG GFMT_BUILD_BRANCH=
# A bare ENV substitution below has been observed serving a stale cached
# layer from the registry buildcache even when the ARG value passed in
# differs from the previous build (seen 2026-08-22: the footer kept showing
# a commit from a day and several pushes earlier, despite /app itself - the
# COPY layer above, which did invalidate correctly - having the current
# code). Same class of stale-cache-hit bug as .github/workflows/
# docker-publish.yml's own comment on the registry cache describes, just
# hitting this ENV layer instead this time. RUN's cache key reliably
# incorporates any ARG it actually references, unlike a plain ENV assignment
# in some BuildKit versions, so this forces a real cache-key check against
# GFMT_BUILD_SHA's resolved value and makes a stale hit here impossible
# regardless of cause.
RUN echo "Building ${GFMT_BUILD_SHA} (${GFMT_BUILD_BRANCH}, ${GFMT_BUILD_DATE})"
ENV DISPLAY=:99 \
    GFMT_BROWSER_RUNTIME_DIR=/run/gfmt-browser \
    GFMT_DATA_DIR=/data \
    GFMT_NONINTERACTIVE=1 \
    GFMT_BUILD_SHA=${GFMT_BUILD_SHA} \
    GFMT_BUILD_DATE=${GFMT_BUILD_DATE} \
    GFMT_BUILD_BRANCH=${GFMT_BUILD_BRANCH}

EXPOSE 4321

# See webui/main.py's /health route and docker/web/healthcheck.py - a plain
# Python script rather than curl, which isn't part of this image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "docker/web/healthcheck.py"]

# webui/serve.py wraps the same plain uvicorn invocation the CMD used to be
# directly, adding a self-signed HTTPS option (HTTPS_ENABLED, see
# webui/config.py and webui/tls.py) - a no-op wrapper unless that's set.
CMD ["python3", "-m", "webui.serve"]
