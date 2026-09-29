"""
Gateway ingress aggregator — mounts Google Chat, Telegram, and Slack routers.
Also handles the WhatsApp bridge already running locally on port 3000.
"""
from __future__ import annotations

from fastapi import APIRouter

from src.gateway.google_chat import router as google_chat_router
from src.gateway.telegram import router as telegram_router
from src.gateway.slack import router as slack_router
from src.gateway.whatsapp import router as whatsapp_router
from src.gateway.worker import start_worker, stop_worker

router = APIRouter()

# Mount all gateway routers
router.include_router(google_chat_router)
router.include_router(telegram_router)
router.include_router(slack_router)
router.include_router(whatsapp_router, prefix="/gateway/whatsapp")
router.include_router(whatsapp_router, prefix="/api/gateway/whatsapp")


def startup():
    """Start the background agent worker on application startup."""
    start_worker()


def shutdown():
    """Stop the background agent worker on application shutdown."""
    stop_worker()
