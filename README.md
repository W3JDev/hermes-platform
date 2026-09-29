# Hermes Platform — Self-Hosted Multi-Agent Platform & Web Companion

A complete, production-ready, self-hosted deployment package for the **Nous Hermes Agent Platform**. Runs on any Docker host or Coolify instance with zero vendor lock-in.

---

## What's Included

* 🌐 **Hermes Web Companion (`hermes-companion/`)**: The full Hermes Desktop frontend compiled for standard web browsers and mobile PWA with real-time WebAudio, WebSocket streaming, and defensive platform shims.
* 🤖 **Hermes Core Runtime (`hermes-core/`)**: Official Nous Hermes Agent Gateway (port 8642) and Admin Dashboard (port 9119).
* 🎨 **Hermes Enterprise Platform (`hermes-enterprise/`)**: Interactive GenUI workspace, Canvas, live tool execution stream, and continuous memory engine.
* 🎙️ **Voice Gateway (`voice-gateway/`)**: MiniMax TTS and real-time audio pipeline.
* 🧠 **Vector Memory Hub (`postgres-hub/`)**: PostgreSQL 16 with pgvector for persistent long-term memory across sessions.
* ⚡ **Cache & Message Broker (`redis`)**: Redis 7 for high-speed session caching and pub/sub.
* 🌐 **Centralized Environment Vault (`env-vault/`)**: Centralized credential management.
* 🕵️ **Anti-detect Browser Pool (`camoufox-pool/`)**: Playwright + Camoufox headless pool for web exploration tools.

---

## Quick Start

See [DEPLOYMENT.md](DEPLOYMENT.md) for full deployment instructions for **Coolify**, **Docker Compose**, and **standalone VPS**.

```bash
# 1. Clone repository
git clone https://github.com/W3JDev/hermes-platform.git
cd hermes-platform

# 2. Configure environment
cp .env.example .env

# 3. Launch the full platform
docker compose up -d --build
```

Access the Web Companion at `http://localhost` (or your configured domain).

---

## License & Credits

Built on top of [Nous Research Hermes Agent](https://github.com/nousresearch/hermes-agent). Internal & commercial use permitted.
