"""
Multimodal Audio Engine for Hermes Enterprise Agent.
Provides real-time Speech-to-Text (STT) via Groq Whisper / Deepgram Nova-2
and Text-to-Speech (TTS) via ElevenLabs / MiniMax.
"""
from __future__ import annotations

import logging
from typing import Optional
import httpx

from src.config import settings

logger = logging.getLogger("hermes.audio")


async def transcribe_audio(audio_bytes: bytes, filename: str = "speech.wav", content_type: str = "audio/wav") -> str:
    """
    Transcribes audio bytes to text using Groq Whisper-large-v3-turbo or Deepgram Nova-2.
    """
    if not audio_bytes:
        return ""

    # 1. Groq Whisper (Ultra fast, sub-second transcription)
    if settings.GROQ_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                files = {"file": (filename, audio_bytes, content_type)}
                data = {"model": "whisper-large-v3-turbo", "response_format": "json"}
                headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
                resp = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                if resp.status_code == 200:
                    text = resp.json().get("text", "").strip()
                    if text:
                        return text
        except Exception as e:
            logger.warning(f"Groq Whisper STT failed: {e}")

    # 2. Deepgram Nova-2 Fallback
    if settings.DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                headers = {
                    "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                    "Content-Type": content_type,
                }
                resp = await client.post(
                    "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true",
                    headers=headers,
                    content=audio_bytes,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    channels = data.get("results", {}).get("channels", [])
                    if channels:
                        alts = channels[0].get("alternatives", [])
                        if alts:
                            transcript = alts[0].get("transcript", "").strip()
                            if transcript:
                                return transcript
        except Exception as e:
            logger.warning(f"Deepgram STT failed: {e}")

    return ""


async def synthesize_speech(text: str, voice_id: Optional[str] = None) -> Optional[bytes]:
    """
    Synthesizes speech audio from text using ElevenLabs.
    """
    if not text or not settings.ELEVENLABS_API_KEY:
        return None

    active_voice = voice_id or settings.ELEVENLABS_VOICE_ID or "21m00Tcm4TlvDq8ikWAM"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "xi-api-key": settings.ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            body = {
                "text": text[:1000],  # cap to 1000 chars for real-time speech responses
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            }
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{active_voice}",
                headers=headers,
                json=body,
            )
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        logger.warning(f"ElevenLabs TTS failed: {e}")

    return None
