FROM python:3.11-slim-bookworm

# Install core runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    libffi-dev \
    ffmpeg \
    ca-certificates \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/hermes-agent

# Clone latest official Hermes Agent from Nous Research
RUN git clone --depth 1 https://github.com/nousresearch/hermes-agent.git /opt/hermes-agent \
    && pip install --no-cache-dir --upgrade pip uv setuptools wheel \
    && pip install --no-cache-dir -e . -r requirements.txt ruamel.yaml

# Setup non-root hermes user for secure execution
RUN useradd -m -u 1000 -s /bin/bash hermes \
    && mkdir -p /home/hermes/.hermes /home/hermes/data \
    && chown -R hermes:hermes /home/hermes /opt/hermes-agent

COPY --chown=hermes:hermes entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER hermes
WORKDIR /home/hermes

ENV HOME=/home/hermes
ENV PATH="/home/hermes/.local/bin:/usr/local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

EXPOSE 8642 9119

HEALTHCHECK --interval=20s --timeout=5s --retries=5 --start-period=30s \
  CMD curl -f http://127.0.0.1:8642/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
