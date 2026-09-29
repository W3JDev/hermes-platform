# Hermes Platform — Self-Hosted Deployment Guide

This repository contains the complete, enterprise-grade deployment stack for the **Nous Hermes Agent Platform**, including:
1. **Hermes Web Companion**: Full Hermes Desktop frontend running directly in the browser & mobile PWA with real-time audio, WebSocket streaming, and defensive shims.
2. **Hermes Core Runtime**: Official Nous Hermes Agent background Gateway (port 8642) and Admin Dashboard (port 9119).
3. **Hermes Enterprise Platform**: GenUI Canvas, PostgreSQL 16 + pgvector lifelong memory, and real-time streaming tools.
4. **Voice Gateway**: MiniMax TTS & Grok ultra-low-latency real-time voice speech pipelines.

---

## Architecture Overview

```
[Browser / Mobile PWA / Desktop App]
             │
             ▼
   [hermes-companion:80] (Nginx API Gateway + Web Client)
    ├── /           ──> Web Companion UI (HTML5/React/PWA)
    ├── /ws         ──> Reverse-proxied to hermes-core:9119/api/ws
    ├── /api/       ──> Reverse-proxied to hermes-core:9119/api/
    ├── /gateway/   ──> Reverse-proxied to hermes-core:8642/
    └── /enterprise/──> Reverse-proxied to hermes-enterprise:8001/
             │
   ┌─────────┴─────────┬──────────────────┐
   ▼                   ▼                  ▼
[hermes-core]    [hermes-enterprise]   [voice-gateway]
   │                   │
   ▼                   ▼
[Postgres pgvector]  [Redis 7]
```

---

## 1-Click Deployment on Coolify

1. Open your **Coolify Dashboard**.
2. Click **Create New Project** -> **Production**.
3. Choose **Add Resource** -> **From Git Repository**.
4. Select `W3JDev/hermes-platform` (or your GitHub mirror).
5. Choose **Docker Compose** as the build pack.
6. Configure your environment variables using `.env.example` in the Coolify environment tab.
7. Set your public domain (e.g. `hermes.yourdomain.com`).
8. Click **Deploy**.

Coolify will automatically provision SSL certificates via Let's Encrypt and launch the multi-container stack.

---

## Standalone Deployment (Docker Compose on Any VPS)

### Prerequisites
- Ubuntu 22.04 / 24.04 or Debian 12
- Docker 24+ & Docker Compose v2 (`sudo apt install docker.io docker-compose-v2`)
- 2+ vCPU and 4GB+ RAM (8GB recommended for local vector search)

### Step 1: Clone Repository
```bash
git clone https://github.com/W3JDev/hermes-platform.git
cd hermes-platform
```

### Step 2: Configure Environment
```bash
cp .env.example .env
nano .env  # Add your API keys and secrets
```

### Step 3: Launch Stack
```bash
docker compose up -d --build
```

### Step 4: Verify Health
```bash
docker compose ps
docker compose logs -f hermes-companion
```

Visit `http://<your-server-ip>` in your browser to immediately access your Hermes Web Companion.

---

## Mobile PWA Installation

1. Open `https://your-domain` in Safari (iOS) or Chrome (Android).
2. Tap **Share** -> **Add to Home Screen** (iOS) or tap the **Install App** banner (Android/Chrome).
3. The app will launch in full-screen standalone mode with native microphone support and responsive layout.
