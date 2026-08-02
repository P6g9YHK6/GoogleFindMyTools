# Build context is the repo root: docker build -f docker/browser/Dockerfile .
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    GFMT_NONINTERACTIVE=1 \
    GFMT_SECRETS_DIR=/data/auth

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
RUN chmod +x /entrypoint.sh

EXPOSE 6901 8001

ENTRYPOINT ["/entrypoint.sh"]
