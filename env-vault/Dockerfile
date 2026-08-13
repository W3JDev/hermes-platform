FROM python:3.11-slim

WORKDIR /app

# Build context is the REPO ROOT (where this Dockerfile lives at env-vault/Dockerfile).
# COPY paths are therefore relative to the repo root, not the Dockerfile directory.
COPY env-vault/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY env-vault/app/ ./app/
COPY env-vault/static/ ./static/

ENV PYTHONUNBUFFERED=1
ENV PORT=8200
ENV DB_PATH=/data/env-vault.db

EXPOSE 8200

# Run as non-root for safety
RUN useradd -m -u 1000 vault && chown -R vault:vault /app
USER vault

# Generate ADMIN_TOKEN on first run if not set, write to /data/INITIAL_ADMIN_TOKEN,
# then start uvicorn. The /data volume is mounted at runtime.
CMD ["sh", "-c", "python -m app.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8200"]
