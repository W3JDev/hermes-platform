"""voice-gateway: MiniMax TTS service for Hermes Platform.

Provides Hermes skill manifest at /skill.json. Synthesizes speech via MiniMax TTS API.
Caches results in postgres-hub, uploads to minio for shareable signed URLs.
"""
import os
import asyncio
import hashlib
import json
import logging
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("voice-gateway")

ENV_VAULT_URL = os.environ.get("ENV_VAULT_URL", "http://env-vault:8200")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io")
MINIMAX_TTS_ENDPOINT = os.environ.get("MINIMAX_TTS_ENDPOINT", "/v1/audio/speech")
MINIMAX_DEFAULT_VOICE = os.environ.get("MINIMAX_DEFAULT_VOICE", "English_PassionateWarrior")
MINIMAX_DEFAULT_MODEL = os.environ.get("MINIMAX_DEFAULT_MODEL", "speech-2.6-hd")
POSTGRES_URL = os.environ.get("POSTGRES_URL", "")
MINIO_URL = os.environ.get("MINIO_URL", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "hermes-shared-files")

API_KEY: Optional[str] = None
_pg_pool = None
_minio_client = None


async def fetch_env_from_vault(name: str) -> Optional[str]:
    """Fetch an env var from env-vault."""
    if not ADMIN_TOKEN or not ENV_VAULT_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ENV_VAULT_URL}/api/vars/{name}",
                                 headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
            if r.status_code == 200:
                return r.json().get("value")
    except Exception as e:
        logger.warning(f"[voice-gateway] Failed to fetch {name} from env-vault: {e}")
    return None


async def init_backends():
    """Fetch API key from env-vault; init postgres cache + minio client if URLs set."""
    global API_KEY, _pg_pool, _minio_client
    # Fetch API key from env-vault (fallback to env var)
    API_KEY = await fetch_env_from_vault("MINIMAX_API_KEY")
    if not API_KEY:
        API_KEY = os.environ.get("MINIMAX_API_KEY", "")
    if not API_KEY:
        logger.warning("[voice-gateway] MINIMAX_API_KEY not set — TTS calls will fail")
    else:
        logger.info("[voice-gateway] MINIMAX_API_KEY loaded from env-vault" if await fetch_env_from_vault("MINIMAX_API_KEY") else "from env var")

    # Init postgres cache
    if POSTGRES_URL:
        try:
            import psycopg2
            from psycopg2 import pool
            _pg_pool = pool.SimpleConnectionPool(1, 5, dsn=POSTGRES_URL)
            with _pg_pool.getconn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS voice_cache (
                            cache_key TEXT PRIMARY KEY,
                            audio_bytes BYTEA NOT NULL,
                            voice TEXT NOT NULL,
                            model TEXT NOT NULL,
                            text_hash TEXT NOT NULL,
                            created_at INTEGER NOT NULL
                        )
                    """)
                    conn.commit()
            _pg_pool.putconn(conn)
            logger.info("[voice-gateway] postgres cache initialized")
        except Exception as e:
            logger.warning(f"[voice-gateway] postgres cache init failed: {e}")
            _pg_pool = None

    # Init minio
    if MINIO_URL:
        try:
            from minio import Minio
            minio_creds = await fetch_env_from_vault("MINIO_ROOT_USER"), await fetch_env_from_vault("MINIO_ROOT_PASSWORD")
            if not minio_creds[0] or not minio_creds[1]:
                minio_creds = os.environ.get("MINIO_ROOT_USER", ""), os.environ.get("MINIO_ROOT_PASSWORD", "")
            from urllib.parse import urlparse
            u = urlparse(MINIO_URL)
            _minio_client = Minio(u.netloc, access_key=minio_creds[0], secret_key=minio_creds[1], secure=(u.scheme == "https"))
            logger.info(f"[voice-gateway] minio client initialized ({u.netloc})")
        except Exception as e:
            logger.warning(f"[voice-gateway] minio init failed: {e}")
            _minio_client = None


def cache_key(text: str, voice: str, model: str) -> str:
    h = hashlib.sha256(f"{text}|{voice}|{model}".encode("utf-8")).hexdigest()
    return h


async def get_cached(key: str) -> Optional[bytes]:
    if not _pg_pool:
        return None
    try:
        with _pg_pool.getconn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT audio_bytes FROM voice_cache WHERE cache_key = %s", (key,))
                row = cur.fetchone()
                if row:
                    return bytes(row[0])
    except Exception as e:
        logger.warning(f"[voice-gateway] cache get failed: {e}")
    return None


def set_cached(key: str, audio: bytes, voice: str, model: str, text_hash: str):
    if not _pg_pool:
        return
    try:
        with _pg_pool.getconn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO voice_cache (cache_key, audio_bytes, voice, model, text_hash, created_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (cache_key) DO NOTHING",
                    (key, audio, voice, model, text_hash, int(time.time()))
                )
                conn.commit()
    except Exception as e:
        logger.warning(f"[voice-gateway] cache set failed: {e}")


async def upload_to_minio(key: str, audio: bytes) -> Optional[str]:
    if not _minio_client:
        return None
    try:
        from io import BytesIO
        obj_name = f"voice/{key}.mp3"
        _minio_client.put_object(MINIO_BUCKET, obj_name, BytesIO(audio), length=len(audio), content_type="audio/mpeg")
        from datetime import timedelta
        url = _minio_client.presigned_get_object(MINIO_BUCKET, obj_name, expires=timedelta(hours=1))
        return url
    except Exception as e:
        logger.warning(f"[voice-gateway] minio upload failed: {e}")
        return None


async def call_minimax_tts(text: str, voice: str, model: str) -> bytes:
    """Call MiniMax TTS API. The endpoint is OpenAI-compatible."""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="MINIMAX_API_KEY not configured")
    url = f"{MINIMAX_BASE_URL}{MINIMAX_TTS_ENDPOINT}"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    body = {"model": model, "input": text, "voice": voice}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=body)
    if r.status_code != 200:
        logger.error(f"[voice-gateway] MiniMax TTS failed: {r.status_code} {r.text[:200]}")
        raise HTTPException(status_code=502, detail=f"MiniMax TTS returned {r.status_code}: {r.text[:200]}")
    return r.content


class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    model: Optional[str] = None


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_backends()
    yield


app = FastAPI(title="voice-gateway", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "provider": "minimax",
        "api_key_loaded": bool(API_KEY),
        "cache": _pg_pool is not None,
        "minio": _minio_client is not None,
    }


@app.get("/skill.json")
async def skill_manifest():
    return {
        "name": "voice_synth",
        "description": "Synthesize speech from text using MiniMax TTS.",
        "version": "1.0.0",
        "inputs": [
            {"name": "text", "type": "string", "required": True, "description": "Text to speak."},
            {"name": "voice", "type": "string", "required": False, "default": "English_PassionateWarrior", "description": "MiniMax voice id."},
            {"name": "model", "type": "string", "required": False, "default": "speech-2.6-hd", "description": "MiniMax TTS model."},
        ],
        "outputs": [
            {"name": "audio_url", "type": "string", "description": "URL to the synthesized audio (signed, expires in 1h)."}
        ],
        "endpoint": "POST /synthesize",
        "auth": "none-required-for-internal-net",
    }


@app.get("/voices")
async def voices():
    """List available MiniMax voices. Returns a static list for now."""
    return {
        "voices": [
            {"id": "English_PassionateWarrior", "language": "en", "gender": "male", "description": "Deep, confident"},
            {"id": "English_Graceful_Lady", "language": "en", "gender": "female", "description": "Calm, professional"},
            {"id": "English_Trustworth_Man", "language": "en", "gender": "male", "description": "Warm, professional"},
            {"id": "English_PlayfulGirl", "language": "en", "gender": "female", "description": "Upbeat, casual"},
            {"id": "English_InspiringGirl", "language": "en", "gender": "female", "description": "Motivational"},
        ]
    }


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    """Synthesize speech. Returns audio/mpeg bytes (or JSON with audio_url if minio is up)."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    voice = req.voice or MINIMAX_DEFAULT_VOICE
    model = req.model or MINIMAX_DEFAULT_MODEL
    key = cache_key(text, voice, model)
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    # Check cache
    cached = await get_cached(key)
    if cached:
        logger.info(f"[voice-gateway] cache hit for key={key[:8]}")
        return Response(content=cached, media_type="audio/mpeg",
                       headers={"X-Cache": "HIT", "X-Cache-Key": key[:16]})

    # Call MiniMax
    audio = await call_minimax_tts(text, voice, model)

    # Save to cache
    set_cached(key, audio, voice, model, text_hash)

    # Upload to minio (best-effort)
    audio_url = await upload_to_minio(key, audio)
    if audio_url:
        return {"ok": True, "audio_url": audio_url, "voice": voice, "model": model, "size_bytes": len(audio), "cache_key": key}

    # Fall back to inline audio bytes
    return Response(content=audio, media_type="audio/mpeg",
                   headers={"X-Cache": "MISS", "X-Cache-Key": key[:16], "Content-Disposition": f'attachment; filename="voice-{key[:8]}.mp3"'})
