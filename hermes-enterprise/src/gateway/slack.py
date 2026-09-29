"""Slack App gateway — Events API with HMAC-SHA256 signature verification."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status

from src.config import settings
from src.gateway.mapper import GatewayMapper
from src.gateway.worker import AgentJob, enqueue

router = APIRouter(prefix="/gateway/slack", tags=["gateway-slack"])
mapper = GatewayMapper()


def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> None:
    if not settings.SLACK_SIGNING_SECRET:
        return  # Skip if not configured
    if abs(time.time() - float(timestamp)) > 300:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Request too old")
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        settings.SLACK_SIGNING_SECRET.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature")


async def post_slack_message(channel: str, text: str) -> None:
    if not settings.SLACK_BOT_TOKEN:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json={"channel": channel, "text": text},
        )


@router.post("")
async def slack_events(
    request: Request,
    x_slack_request_timestamp: Optional[str] = Header(None),
    x_slack_signature: Optional[str] = Header(None),
):
    body_bytes = await request.body()

    if x_slack_request_timestamp and x_slack_signature:
        _verify_slack_signature(body_bytes, x_slack_request_timestamp, x_slack_signature)

    body = json.loads(body_bytes)

    # Handle url_verification challenge (Slack app setup)
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    event = body.get("event", {})
    event_type = event.get("type", "")

    # Only handle human messages (ignore bot messages to avoid loops)
    if event_type not in ("message", "app_mention"):
        return {"ok": True}
    if event.get("bot_id") or event.get("subtype"):
        return {"ok": True}

    text = event.get("text", "").strip()
    channel = event.get("channel", "")
    user_id_slack = event.get("user", "")
    team_id = body.get("team_id", "default")

    if not text or not user_id_slack:
        return {"ok": True}

    ctx = await mapper.resolve_or_create(
        platform="slack",
        external_team_id=team_id,
        external_user_id=user_id_slack,
    )
    if not ctx:
        return {"ok": True}

    async def _reply(response: str):
        # Split long responses into chunks
        for chunk in [response[i : i + 3000] for i in range(0, len(response), 3000)]:
            await post_slack_message(channel, chunk)

    await enqueue(AgentJob(context=ctx, text=text, reply_fn=_reply))
    return {"ok": True}
