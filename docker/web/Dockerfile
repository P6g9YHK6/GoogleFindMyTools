# Build context is the repo root: docker build -f docker/web/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-web.txt /app/
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

# Only what's needed to run apt-get itself at runtime (ca-certificates for the
# HTTPS downloads, procps for pkill during teardown) and to actually install
# xvfb/x11vnc/novnc/websockify on demand. Chrome itself is fetched as a
# portable "Chrome for Testing" zip at runtime, not via apt, and none of the
# browser/X11/VNC stack is baked into this image - see webui/browser_provisioning.py.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

ENV DISPLAY=:99 \
    GFMT_BROWSER_RUNTIME_DIR=/run/gfmt-browser \
    GFMT_SECRETS_DIR=/data/auth \
    GFMT_DATA_DIR=/data/webui \
    GFMT_NONINTERACTIVE=1

EXPOSE 4321

CMD ["uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "4321"]
