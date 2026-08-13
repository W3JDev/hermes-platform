FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8202
ENV ENV_VAULT_URL="http://env-vault:8200"
ENV ADMIN_TOKEN=""
ENV MINIMAX_BASE_URL="https://api.minimax.io"
ENV MINIMAX_TTS_ENDPOINT="/v1/audio/speech"
ENV MINIMAX_DEFAULT_VOICE="English_PassionateWarrior"
ENV MINIMAX_DEFAULT_MODEL="speech-2.6-hd"
ENV POSTGRES_URL=""
ENV MINIO_URL=""
ENV MINIO_BUCKET="hermes-shared-files"

EXPOSE 8202

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8202"]
