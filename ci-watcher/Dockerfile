FROM python:3.11-slim

WORKDIR /app

COPY ci-watcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY ci-watcher/app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8203
ENV POLL_INTERVAL_SECONDS=300
ENV ENV_VAULT_URL="http://env-vault:8200"
ENV DATA_DIR="/data"
ENV ADMIN_TOKEN=""

EXPOSE 8203

CMD ["python", "-m", "app.watcher"]
