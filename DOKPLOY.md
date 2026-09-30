# Dokploy Self-Hosted Deployment Guide

This guide walks you through deploying the **Hermes Platform with OpenMuse Frontdoor** on **[Dokploy](https://dokploy.com/)** using Docker Compose.

---

## 1. Quick Architecture Overview

When deployed in Dokploy, the Compose stack spins up 6 integrated services:
1. **`openmuse-frontdoor`** (Primary Frontdoor): Mobile/Web PWA, Real-time voice (MiniMax/Grok), CopilotKit, AG-UI HermesAdapter.
2. **`openmuse-worker`**: Playwright browser sandbox & OpenComputer task execution.
3. **`hermes-companion`**: Web/Desktop companion UI connected to Hermes core.
4. **`hermes-core`**: Headless Nous Hermes Agent server (`8642`) and Admin Dashboard (`9119`).
5. **`postgres-hub`**: PostgreSQL 16 with `pgvector` HNSW indexes for persistent vector memory.
6. **`redis`**: High-performance agent caching and task coordination.

---

## 2. Step-by-Step Dokploy Deployment

### Step 1: Create a New Compose Application in Dokploy
1. Log in to your Dokploy dashboard.
2. Click **Create Project** (e.g., `hermes-agent`) or select an existing project.
3. Click **Create Service** -> Choose **Compose**.
4. Set the service name to `hermes-platform`.

### Step 2: Configure Git Repository
In the **Source** tab:
- **Repository URL**: `https://github.com/W3JDev/hermes-platform.git`
- **Branch**: `main`
- **Compose Path**: `docker-compose.yml`
- Enable **Auto Deploy** on Git push (optional, recommended).

### Step 3: Set Environment Variables
In the **Environment** tab of your Compose service in Dokploy, copy and paste the contents from `.env.example`, filling in your API keys:

```bash
# Workspace Mode ('sample' for demo/offline, 'live' for production with API keys)
WORKSPACE_MODE=sample

# LLM API Keys
OPENROUTER_API_KEY=your_openrouter_key
GEMINI_API_KEY=your_gemini_key
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
XAI_API_KEY=your_grok_key

# Voice Synthesis (MiniMax / Grok)
MINIMAX_API_KEY=your_minimax_key
MINIMAX_BASE_URL=https://api.minimax.io/v1

# OpenComputer / Boat.dev Browser Sandbox
OPENCOMPUTER_API_KEY=your_boat_dev_key
OPENCOMPUTER_PROJECT_ID=your_boat_dev_project_id

# Hermes Dashboard Authentication (Required for remote hosts)
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=your_secure_password

# Database & JWT
POSTGRES_PASSWORD=generate_a_secure_password_here
JWT_SECRET_KEY=generate_a_minimum_32_character_random_string
```

### Step 4: Configure Domains in Dokploy (Traefik SSL)
In Dokploy's **Domains** section, you can add domains with automatic Let's Encrypt SSL:

1. **OpenMuse Frontdoor**:
   - Domain: `muse.yourdomain.com`
   - Service: `openmuse-frontdoor`
   - Port: `8787`
2. **Hermes Companion (Desktop Web)**:
   - Domain: `companion.yourdomain.com`
   - Service: `hermes-companion`
   - Port: `80`
3. **Hermes Admin Dashboard**:
   - Domain: `dashboard.yourdomain.com`
   - Service: `hermes-core`
   - Port: `9119`

### Step 5: Deploy
Click **Deploy** in the top-right corner. Dokploy will pull the repository, build the images using multi-stage caching, and launch all services with health checks.

---

## 3. Verifying Deployment Health

Once deployment shows **Active**:
- **OpenMuse Web/PWA**: Open `https://muse.yourdomain.com` — the dynamic origin resolver connects directly to your domain without any hardcoded ports.
- **Companion**: Open `https://companion.yourdomain.com` — the reverse proxy seamlessly connects to Hermes Core.
- **Health Probes**:
  ```bash
  curl https://muse.yourdomain.com/api/health
  # {"ok":true,"mode":"sample","agentConfigured":true,"browserConfigured":true}
  ```
