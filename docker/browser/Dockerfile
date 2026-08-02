# Build context is the repo root: docker build -f docker/browser/Dockerfile .
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    GFMT_NONINTERACTIVE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg ca-certificates fonts-liberation \
        xvfb x11vnc novnc websockify supervisor \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt fastapi "uvicorn[standard]"

COPY . /app
COPY docker/browser/browser_agent.py /app/browser_agent.py
COPY docker/browser/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/browser/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    # Auth/secrets.json is gitignored and not present at build time. Bake in an
    # empty placeholder so the docker-compose `secrets` volume (mounted at this
    # exact file path, shared with the web container) initializes as a file
    # mount instead of Docker defaulting to an empty directory mount.
    && test -f /app/Auth/secrets.json || echo '{}' > /app/Auth/secrets.json

EXPOSE 6901 8001

ENTRYPOINT ["/entrypoint.sh"]
