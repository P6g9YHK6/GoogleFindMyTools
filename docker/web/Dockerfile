# Build context is the repo root: docker build -f docker/web/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-web.txt /app/
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

COPY . /app

# Secrets live in a mounted directory shared with the browser container
# (see Auth/token_cache.py), not at a fixed path inside the image.
ENV GFMT_SECRETS_DIR=/data/auth

EXPOSE 4321

CMD ["uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "4321"]
