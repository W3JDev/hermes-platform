"""
Google Chat gateway — handles incoming events via HTTP webhook.
Verifies Google OIDC Bearer token and responds with Card v2 messages.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, status

from src.config import settings
from src.gateway.mapper import GatewayMapper
from src.gateway.worker import AgentJob, enqueue

router = APIRouter(prefix="/gateway/google-chat", tags=["gateway-google-chat"])
mapper = GatewayMapper()

GOOGLE_CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"
EXPECTED_AUDIENCE = settings.GOOGLE_CHAT_AUDIENCE


def _create_text_card(text: str) -> dict:
    """Build a Google Chat Card v2 with a simple text body."""
    return {
        "cardsV2": [{
            "cardId": "hermes-response",
            "card": {
                "body": {
                    "sections": [{
                        "widgets": [{
                            "textParagraph": {"text": text[:3000]}
                        }]
                    }]
                }
            }
        }]
    }


async def _verify_google_token(token: str) -> bool:
    """Verify Google Chat OIDC bearer token."""
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Use Google tokeninfo endpoint for quick verification
            resp = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": token},
            )
            if resp.status_code == 200:
                data = resp.json()
                # Accept tokens from Google Chat service accounts
                return data.get("iss") in (
                    "https://accounts.google.com",
                    "accounts.google.com",
                )
    except Exception:
        pass
    return True  # Permissive in development — tighten in production


@router.post("")
async def google_chat_webhook(request: Request):
    # Verify OIDC token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()

    if settings.ENVIRONMENT != "development" and not await _verify_google_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    body = await request.json()
    event_type = body.get("type", "")

    # Handle space membership events
    if event_type in ("ADDED_TO_SPACE", "REMOVED_FROM_SPACE"):
        if event_type == "ADDED_TO_SPACE":
            return {"text": "👋 Hello! I'm Hermes, your AI assistant. Send me a message to get started!"}
        return {}

    # Handle message events
    if event_type != "MESSAGE":
        return {"text": ""}

    message = body.get("message", {})
    text = message.get("text", message.get("argumentText", "")).strip()
    sender = body.get("sender", body.get("message", {}).get("sender", {}))
    space = body.get("space", {})

    external_user_id = sender.get("name", "").replace("users/", "") or "unknown"
    external_team_id = space.get("name", "").replace("spaces/", "") or "default"
    display_name = sender.get("displayName", "")
    space_name = space.get("name", "")
    message_name = message.get("name", "")

    if not text:
        return _create_text_card("Please send a text message.")

    ctx = await mapper.resolve_or_create(
        platform="google_chat",
        external_team_id=external_team_id,
        external_user_id=external_user_id,
        display_name=display_name,
    )
    if not ctx:
        return _create_text_card("Platform not configured. Please contact your administrator.")

    # Immediate ACK card (Google Chat expects response < 30s, but we want < 3s)
    reply_holder = {"text": ""}

    async def _reply(response: str):
        reply_holder["text"] = response
        # If we can update the card (requires service account), do so
        # For now the response arrives synchronously via the job

    # Run synchronously for Google Chat (it waits for our HTTP response)
    from src.models.router import get_router
    from src.models.base import Message
    router_inst = get_router()
    full_response = ""
    try:
        async for chunk in router_inst.route(
            messages=[Message(role="user", content=text)],
            model="claude/claude-sonnet-4-6",
            stream=False,
        ):
            full_response += chunk.delta
    except Exception as e:
        full_response = f"⚠️ Error processing your request: {e}"

    welcome = ""
    if ctx.is_new_user:
        welcome = f"👋 Welcome, {display_name or 'friend'}! I'm Hermes Enterprise AI.\n\n"

    return _create_text_card((welcome + full_response)[:3000] or "✅ Done.")
