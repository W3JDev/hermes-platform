"""Telegram Bot gateway — webhook + optional polling mode."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status

from src.config import settings
from src.gateway.mapper import GatewayMapper
from src.gateway.worker import AgentJob, enqueue

router = APIRouter(prefix="/gateway/telegram", tags=["gateway-telegram"])
mapper = GatewayMapper()

TELEGRAM_API = "https://api.telegram.org"


async def send_telegram_message(chat_id: int | str, text: str) -> None:
    """Send a reply message back to Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    # Split long messages (Telegram max 4096 chars)
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15) as client:
        for chunk in chunks:
            await client.post(
                f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
            )


def _verify_secret(secret_token: Optional[str]) -> None:
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if not secret_token or not hmac.compare_digest(
            secret_token, settings.TELEGRAM_WEBHOOK_SECRET
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")


@router.post("/{token}")
async def telegram_webhook(
    token: str,
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    # Verify token matches configured bot token
    if token != settings.TELEGRAM_BOT_TOKEN.split(":")[0] if ":" in settings.TELEGRAM_BOT_TOKEN else token:
        pass  # Allow through — validate by secret header instead
    _verify_secret(x_telegram_bot_api_secret_token)

    body = await request.json()
    message = body.get("message") or body.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    user_data = message.get("from", {})
    external_user_id = str(user_data.get("id", "unknown"))
    external_team_id = str(chat_id or "unknown")
    text = message.get("text", "")
    display_name = f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()

    if not text or not chat_id:
        return {"ok": True}

    ctx = await mapper.resolve_or_create(
        platform="telegram",
        external_team_id=external_team_id,
        external_user_id=external_user_id,
        display_name=display_name,
    )
    if not ctx:
        return {"ok": True}

    welcome = ""
    if ctx.is_new_user:
        welcome = f"👋 Welcome to Hermes Enterprise, {display_name or 'friend'}! I'm your AI assistant powered by Claude, GPT-5.5 and Gemini. How can I help?\n\n"

    async def _reply(response: str):
        await send_telegram_message(chat_id, welcome + response if welcome else response)

    await enqueue(AgentJob(context=ctx, text=text, reply_fn=_reply))

    # Immediate ACK — Telegram requires response < 5s or it retries
    return {"ok": True}
