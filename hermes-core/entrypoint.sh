#!/bin/bash
set -e

echo "[Hermes Core] Starting Hermes Agent platform daemons..."

mkdir -p /home/hermes/.hermes/logs /home/hermes/data

# Start background gateway (messaging platforms) in background
hermes gateway run &

# Start headless backend server on port 8642 (REST & WebSocket gateway)
hermes serve --host 0.0.0.0 --port 8642 --skip-build &
SERVE_PID=$!
echo "[Hermes Core] Hermes Serve API & WebSocket engine launched (PID: $SERVE_PID)"

# Wait for backend server endpoint to respond
RETRIES=0
MAX_RETRIES=30
until curl -s http://127.0.0.1:8642/api/health > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ $RETRIES -ge $MAX_RETRIES ]; then
        echo "[Hermes Core] Backend server failed to become healthy on port 8642 in time. Exiting."
        exit 1
    fi
    echo "[Hermes Core] Waiting for Backend to listen on port 8642... ($RETRIES/$MAX_RETRIES)"
    sleep 1
done

echo "[Hermes Core] Backend on port 8642 is live and healthy."

# Launch admin dashboard in foreground on port 9119
echo "[Hermes Core] Starting Hermes Dashboard on 0.0.0.0:9119..."
exec hermes dashboard --host 0.0.0.0 --port 9119 --no-open --skip-build

