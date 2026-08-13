FROM python:3.11-slim

WORKDIR /app

# Build context is the REPO ROOT (where this Dockerfile lives at env-vault/Dockerfile).
# COPY paths are therefore relative to the repo root, not the Dockerfile directory.
COPY env-vault/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install curl for Coolify's healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY env-vault/app/ ./app/
COPY env-vault/static/ ./static/

# Ensure /data exists and is writable by any user (we run as root for simplicity)
RUN mkdir -p /data && chmod 777 /data

ENV PYTHONUNBUFFERED=1
ENV PORT=8200
ENV DB_PATH=/data/env-vault.db

EXPOSE 8200

# Run as root — /data needs to be writable, and there's no untrusted input
CMD ["sh", "-c", "python -m app.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8200"]
