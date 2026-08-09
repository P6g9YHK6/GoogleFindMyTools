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
# HTTPS downloads, procps for pkill during teardown) and to actually install
# xvfb/x11vnc/novnc/websockify on demand. Chrome itself is fetched as a
# portable "Chrome for Testing" zip at runtime, not via apt, and none of the
# browser/X11/VNC stack is baked into this image - see webui/browser_provisioning.py.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates procps tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# GFMT_SECRETS_DIR is deliberately not set here - Auth/token_cache.py falls
# back to GFMT_DATA_DIR when it's unset, so everything (auth.yaml alongside
# config.yaml/forwarding.yaml/forward.log/...) lands flat in one directory,
# no subfolders, matching the single `-v .../data:/data` mount below.
ENV DISPLAY=:99 \
    GFMT_BROWSER_RUNTIME_DIR=/run/gfmt-browser \
    GFMT_DATA_DIR=/data \
    GFMT_NONINTERACTIVE=1

EXPOSE 4321

# See webui/main.py's /health route and docker/web/healthcheck.py - a plain
# Python script rather than curl, which isn't part of this image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "docker/web/healthcheck.py"]

CMD ["uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "4321"]
