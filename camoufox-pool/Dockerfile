FROM mcr.microsoft.com/playwright:v1.45.0-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip curl ca-certificates fonts-liberation libnss3 libatk1.0-0 \
        libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Install camoufox python package
RUN pip3 install --no-cache-dir --break-system-packages camoufox==0.4.10 || \
    pip3 install --no-cache-dir --break-system-packages \
        "camoufox @ git+https://github.com/nicedouble/camoufox-py.git"

RUN python3 -m camoufox fetch

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8201

EXPOSE 8201

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8201"]
