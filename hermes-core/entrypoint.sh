#!/bin/bash
set -e

echo "[Hermes Core] Starting Hermes Agent platform daemons..."

# Start background gateway daemon on port 8642
hermes gateway run &
GATEWAY_PID=$!

echo "[Hermes Core] Background Gateway process launched (PID: $GATEWAY_PID)"

# Wait for gateway endpoint to respond
RETRIES=0
MAX_RETRIES=30
until curl -s http://127.0.0.1:8642/health > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ $RETRIES -ge $MAX_RETRIES ]; then
        echo "[Hermes Core] Gateway failed to become healthy in time. Exiting."
        exit 1
    fi
    echo "[Hermes Core] Waiting for Gateway to listen on port 8642... ($RETRIES/$MAX_RETRIES)"
    sleep 2
done

echo "[Hermes Core] Gateway is live and healthy."

# Launch admin dashboard in foreground
echo "[Hermes Core] Starting Hermes Dashboard on 0.0.0.0:9119..."
exec hermes dashboard --host 0.0.0.0 --port 9119 --no-open --skip-build
