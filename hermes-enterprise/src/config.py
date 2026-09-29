"""
Configuration Settings for Nous Hermes Enterprise Agent Platform.
All values loaded from environment variables or .env file.
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Environment ──────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    BASE_URL: str = "http://localhost:8000"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hermes_enterprise"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: float = 30.0
    DB_POOL_RECYCLE: int = 1800

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── File Storage ──────────────────────────────────────────────────────────
    DATA_ROOT_DIR: str = "/var/hermes/data"
    SANDBOX_BASE_DIR: str = "/var/hermes/sandbox"
    MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB
    SKILLS_DIR: str = "/var/hermes/skills"

    # ── Authentication & JWT ──────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_LONG_RANDOM_STRING"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    INVITE_TOKEN_EXPIRE_HOURS: int = 24
    ADMIN_DEFAULT_USERNAME: str = "admin"
    ADMIN_DEFAULT_PASSWORD: str = "hermes-admin-change-me"
    ADMIN_DEFAULT_EMAIL: str = "admin@example.com"
    ADMIN_DEFAULT_TENANT: str = "default"

    # ── Memory & Search ───────────────────────────────────────────────────────
    RRF_K: int = 60
    RRF_W_VEC: float = 0.7
    RRF_W_LEX: float = 0.3
    HNSW_EF_SEARCH: int = 64
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSIONS: int = 768

    # ── AI Model Providers ────────────────────────────────────────────────────
    DEFAULT_MODEL: str = "gemini-2.5-flash"
    GEMINI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    HERMES_VLLM_BASE_URL: str = ""
    HERMES_VLLM_API_KEY: str = "none"

    # ── Official Hermes Agent Framework Root ───────────────────────────────────
    HERMES_AGENT_ROOT: str = r"C:\Users\W3jde\AppData\Local\hermes\hermes-agent"
    HERMES_SPRITES_BASE_URL: str = "https://ai-gateway-bufxd.sprites.app/v1"
    HERMES_SPRITES_API_KEY: str = "sk-17e15ed316373bdd-b6e9de-554652a1"
    HERMES_LOCAL_PORT: int = 9119
    HERMES_LOCAL_API_KEY: str = ""  # Hermes local API key if auth is enabled
    HERMES_LOCAL_DEFAULT_MODEL: str = "claude/claude-sonnet-4-6"
    # Ollama local models (port 11434)
    HERMES_OLLAMA_MODEL: str = "qwen3.5:2b"
    HERMES_OLLAMA_BASE_URL: str = "http://localhost:11434/v1"

    # Audio & Speech Services
    GROQ_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "e72XruyIrGwdOgcQqzw1"
    MINIMAX_API_KEY: str = ""

    # Circuit Breaker
    CB_FAILURE_THRESHOLD: int = 5
    CB_RECOVERY_TIMEOUT: float = 60.0
    CB_SUCCESS_THRESHOLD: int = 2

    # ── Google Workspace ──────────────────────────────────────────────────────
    GOOGLE_CHAT_SERVICE_ACCOUNT_JSON: str = ""
    GOOGLE_CHAT_SERVICE_ACCOUNT_PATH: str = ""
    GOOGLE_CHAT_AUDIENCE: str = "https://chat.googleapis.com"

    # ── Messaging Gateways ────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_USERS: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""

    # ── Composio ──────────────────────────────────────────────────────────────
    COMPOSIO_API_KEY: str = ""
    COMPOSIO_PROJECT_ID: str = ""
    COMPOSIO_ORG_ID: str = ""
    COMPOSIO_USER_ID: str = ""

    # ── Auto-Doctor ───────────────────────────────────────────────────────────
    DOCTOR_PROBE_INTERVAL_SECONDS: int = 30
    DOCTOR_MAX_SELF_HEALING_RETRIES: int = 2


settings = Settings()
