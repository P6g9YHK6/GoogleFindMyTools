# Build context is the repo root: docker build -f docker/web/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-web.txt /app/
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

COPY . /app

# Auth/secrets.json is gitignored and not present at build time. Bake in an
# empty placeholder so the docker-compose `secrets` volume (mounted at this
# exact file path, shared with the browser container) initializes as a file
# mount instead of Docker defaulting to an empty directory mount.
RUN test -f /app/Auth/secrets.json || echo '{}' > /app/Auth/secrets.json

EXPOSE 8080

CMD ["uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "8080"]
