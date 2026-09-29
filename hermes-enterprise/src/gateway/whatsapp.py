"""
WhatsApp Bridge Gateway Connector.
Connects Hermes Enterprise Agent to the local WhatsApp bridge running on port 3000.
Handles incoming webhooks from Baileys / WPPConnect and outgoing message delivery.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status

from src.config import settings
from src.gateway.mapper import GatewayMapper
from src.gateway.worker import AgentJob, enqueue

router = APIRouter(tags=["gateway-whatsapp"])
mapper = GatewayMapper()

WHATSAPP_BRIDGE_URL = "http://localhost:3000"


async def send_whatsapp_message(to: str, message: str) -> Dict[str, Any]:
    """Send an outgoing text message through the local WhatsApp HTTP bridge."""
    endpoint = f"{WHATSAPP_BRIDGE_URL}/api/sendText"
    payload = {
        "chatId": to if "@" in to else f"{to}@c.us",
        "text": message,
        "session": "default",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(endpoint, json=payload)
            if resp.status_code == 200:
                return {"status": "sent", "response": resp.json()}
            return {"status": "error", "code": resp.status_code, "detail": resp.text}
    except Exception as e:
        # Gracefully handle when local bridge is offline or mock
        return {"status": "queued", "bridge_offline": True, "error": str(e)}


@router.get("/status")
async def whatsapp_status():
    """Check connectivity to the local WhatsApp bridge on port 3000."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{WHATSAPP_BRIDGE_URL}/status")
            is_ready = resp.status_code == 200
    except Exception:
        is_ready = False

    return {
        "gateway": "whatsapp",
        "bridge_url": WHATSAPP_BRIDGE_URL,
        "bridge_online": is_ready,
        "channel_status": "ready" if is_ready else "standby",
    }


@router.post("/webhook")
@router.post("")
async def whatsapp_webhook(request: Request):
    """Receive incoming WhatsApp message event from the local bridge."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    sender = body.get("from") or body.get("sender") or body.get("chatId") or "whatsapp_user"
    text = body.get("body") or body.get("text") or body.get("message") or ""

    if not text:
        return {"ok": True, "status": "ignored_empty"}

    # Map message into standard Hermes interaction context
    tenant_id, user_id, conv_id = await mapper.resolve(
        channel="whatsapp",
        external_user_id=sender,
        external_thread_id=sender,
    )

    enqueue(
        AgentJob(
            channel="whatsapp",
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conv_id,
            user_text=text,
            reply_target=sender,
            extra={"raw": body},
        )
    )

    return {"ok": True, "status": "enqueued", "sender": sender}
