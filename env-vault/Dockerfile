FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/

ENV PYTHONUNBUFFERED=1
ENV PORT=8200
ENV ADMIN_TOKEN=""
ENV DB_PATH=/data/env-vault.db

EXPOSE 8200

# Generate ADMIN_TOKEN on first run if not set, write to /data/INITIAL_ADMIN_TOKEN,
# then start uvicorn.
CMD ["sh", "-c", "python -m app.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8200"]
