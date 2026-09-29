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

# Install uv for rapid, rock-solid dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /opt/hermes-agent

# Clone latest official Hermes Agent from Nous Research and install dependencies
RUN git clone --depth 1 https://github.com/nousresearch/hermes-agent.git /opt/hermes-agent \
    && python3 -c 'p = "/opt/hermes-agent/pyproject.toml"; c = open(p).read().replace("python_version >= \x273.14\x27", "python_version >= \x273.11\x27"); open(p, "w").write(c)' \
    && uv pip install --system -e ".[all]"

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
  CMD curl -f http://127.0.0.1:8642/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
