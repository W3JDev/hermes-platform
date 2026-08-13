# Hermes Platform — Self-hosted Multi-Agent Platform

This repo contains the source code for the Hermes Platform — a self-hosted
multi-agent AI platform running on a single Coolify-managed host. Multiple
independent Hermes agents (Jira IT ticketing, helpline support, team projects,
etc.) share infrastructure (env-vault, postgres-hub, minio, camoufox-pool,
voice-gateway, ci-watcher) but maintain fully isolated workspaces.

## Services

| Directory | Subdomain | Purpose | Image |
| --- | --- | --- | --- |
| `env-vault/` | `env-vault.hermes.getbijou.xyz` | Centralized env-var menu (FastAPI + vanilla JS) | Custom (Dockerfile) |
| `postgres-hub/` | (internal) | Shared Postgres with per-profile DBs | `postgres:16-alpine` |
| `minio/` | `minio.hermes.getbijou.xyz` | S3-compatible file storage | `minio/minio:latest` |
| `camoufox-pool/` | `camoufox.hermes.getbijou.xyz` | Anti-detect headless browser pool | Custom (Playwright + Camoufox) |
| `voice-gateway/` | `voice.hermes.getbijou.xyz` | MiniMax TTS service + Hermes skill | Custom (FastAPI + MiniMax) |
| `ci-watcher/` | `ci-watcher.hermes.getbijou.xyz` | Auto-updates Hermes from upstream | Custom (Python cron) |

## Architecture

See `/docs/design.md` in the parent workspace for the full design spec.

## Deploying

Each service is deployed as a separate Coolify "Application" (or "Service" for
multi-container stacks). For custom services, Coolify builds from this GitHub
repo. For off-the-shelf images, Coolify uses `docker_image` deploy.

## License

Internal use only.
