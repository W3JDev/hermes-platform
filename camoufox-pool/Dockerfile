FROM mcr.microsoft.com/playwright:v1.45.0-jammy

# Build context is the REPO ROOT, not this Dockerfile's directory.
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip curl ca-certificates fonts-liberation libnss3 libatk1.0-0 \
        libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

COPY camoufox-pool/requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Fetch browser binaries; ignore failure so image still builds if network flakes
RUN python3 -m camoufox fetch || true

COPY camoufox-pool/app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8201

EXPOSE 8201

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8201"]
