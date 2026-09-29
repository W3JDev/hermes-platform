"""
FastAPI application entry point for Hermes Enterprise Agent Platform.
Mounts all routers, serves static Web UI, and manages application lifespan.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import logging
from pydantic import BaseModel

from src.agent.hermes_native import NativeHermesAgentEngine
from src.auth.rbac import AuthenticatedUser, get_current_user
from src.auth.router import router as auth_router
from src.admin.router import router as admin_router
from src.config import settings
from src.db.session import init_db
from src.doctor.daemon import get_doctor, run_full_doctor
from src.models.base import Message
from src.models.router import get_router

logger = logging.getLogger("hermes.main")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()

    # Bootstrap default admin on first run
    try:
        from src.db.session import async_session_factory
        from src.auth.service import bootstrap_admin_user
        async with async_session_factory() as db:
            await bootstrap_admin_user(db)
            await db.commit()
    except Exception as e:
        print(f"[WARN] Admin bootstrap: {e}")

    # Start model router (pre-warms connections)
    get_router()

    # Start gateway worker
    try:
        from src.gateway.router import startup as gw_startup
        gw_startup()
    except Exception as e:
        print(f"[WARN] Gateway worker: {e}")

    # Start Auto-Doctor daemon
    doctor = get_doctor()
    doctor.start()
    print("[Hermes] [OK] Platform started - Auto-Doctor active")

    yield

    # Shutdown
    try:
        from src.gateway.router import shutdown as gw_shutdown
        gw_shutdown()
    except Exception:
        pass
    doctor.stop()
    print("[Hermes] [STOP] Platform shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Hermes Enterprise Agent Platform",
    version="1.0.0",
    description="Multi-tenant AI agent platform with persistent memory, omnichannel gateways, and self-healing.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(admin_router)

# Tools router
try:
    from src.tools.router import router as tools_router
    app.include_router(tools_router)
except ImportError as e:
    print(f"[WARN] Tools router: {e}")

# Gateway routers
try:
    from src.gateway.router import router as gateway_router
    app.include_router(gateway_router)
except ImportError as e:
    print(f"[WARN] Gateway router: {e}")

# API v1 & Contract Routers
try:
    from src.api_v1 import api_v1_router, gateway_v1_router
    app.include_router(api_v1_router)
    app.include_router(gateway_v1_router)
except ImportError as e:
    print(f"[WARN] API v1 router: {e}")


# ── Static Web UI ─────────────────────────────────────────────────────────────
import os
static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")


# ── Agent Chat Endpoint ───────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: Optional[List[Dict]] = None
    message: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True
    temperature: float = 0.7
    audio_base64: Optional[str] = None
    images: Optional[List[str]] = None


@app.post("/agent/chat")
async def agent_chat(
    body: ChatRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Authenticated streaming chat endpoint connected to the multi-model router with continuous learning."""
    from src.db.session import async_session_factory
    from src.db.memory_auto import recall_relevant_memories, learn_from_interaction
    from src.models.audio import transcribe_audio
    import base64

    router = get_router()

    # Process audio attachment if present
    user_audio_text = ""
    if body.audio_base64:
        try:
            raw_audio = base64.b64decode(body.audio_base64)
            user_audio_text = await transcribe_audio(raw_audio)
        except Exception:
            pass

    if body.messages:
        msgs = [
            Message(
                role=m.get("role", "user"),
                content=m.get("content", ""),
            )
            for m in body.messages
        ]
    elif body.message or user_audio_text:
        content = body.message or user_audio_text
        msgs = [Message(role="user", content=content)]
    else:
        msgs = [Message(role="user", content="Hello")]

    # If audio transcription was made and user sent text, append it
    if user_audio_text and body.message:
        msgs.append(Message(role="user", content=f"[Audio Transcript]: {user_audio_text}"))

    # ── Continuous Learning: Recall long-term memories ───────────────────────────
    user_last_prompt = msgs[-1].content if msgs and isinstance(msgs[-1].content, str) else ""
    async with async_session_factory() as db:
        memories_context = await recall_relevant_memories(
            session=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            query_text=user_last_prompt,
            limit=4,
        )

    # Inject system instruction with memories
    system_prompt = (
        "You are Hermes, a hyper-intelligent, proactive enterprise AI agent equipped with continuous learning, "
        "multimodal perception, and live Generative UI capabilities.\n"
        "When appropriate, you render interactive UI elements for the user:\n"
        "- For data comparisons, metrics, and trends: generate interactive Chart.js widgets using fenced code ```chart\n"
        "  {\"type\":\"bar|line|doughnut\",\"data\":{...},\"options\":{...}}\n```\n"
        "- For workflows, timelines, and architectures: use fenced ```mermaid\n...\n``` diagrams\n"
        "- For interactive HTML components, dashboards, or live widgets: use fenced ```html\n...\n```\n"
        "- When writing code, write complete, robust code blocks."
    )
    if memories_context:
        system_prompt += f"\n{memories_context}"

    augmented_msgs = [Message(role="system", content=system_prompt)] + msgs

    async def sse_stream():
        import json
        full_reply = []
        try:
            executed_native = False
            if NativeHermesAgentEngine.is_available():
                try:
                    history = []
                    for m in msgs[:-1]:
                        c = m.content if isinstance(m.content, str) else str(m.content)
                        history.append({"role": m.role, "content": c})

                    async for event in NativeHermesAgentEngine.run_turn_stream(
                        user_message=user_last_prompt,
                        model_name=body.model,
                        system_prompt=system_prompt,
                        conversation_history=history,
                        session_id=str(current_user.user_id),
                    ):
                        executed_native = True
                        ev_type = event.get("type")
                        if ev_type == "delta":
                            d = event.get("delta", "")
                            full_reply.append(d)
                            yield f"data: {json.dumps({'delta': d})}\n\n"
                        elif ev_type == "action_start":
                            yield f"event: action_start\ndata: {json.dumps(event)}\n\n"
                        elif ev_type == "action_complete":
                            yield f"event: action_complete\ndata: {json.dumps(event)}\n\n"
                        elif ev_type == "thinking":
                            yield f"event: thinking\ndata: {json.dumps(event)}\n\n"
                        elif ev_type == "done":
                            yield "data: [DONE]\n\n"
                except Exception as native_exc:
                    logger.warning("NativeHermesAgentEngine turn failed: %s; falling back to router", native_exc)
                    executed_native = False

            if not executed_native:
                async for chunk in router.route(
                    messages=augmented_msgs,
                    model=body.model,
                    stream=body.stream,
                    temperature=body.temperature,
                ):
                    if chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            tool_name = tc.get("name", "tool")
                            action_type = "terminal" if ("bash" in tool_name or "powershell" in tool_name) else ("browser_use" if "browse" in tool_name else "tool")
                            yield f"event: action_start\ndata: {json.dumps({'action_type': action_type, 'tool_name': tool_name, 'action_id': tc.get('id', tool_name)})}\n\n"
                    if chunk.delta:
                        full_reply.append(chunk.delta)
                        yield f"data: {json.dumps({'delta': chunk.delta})}\n\n"
                    if chunk.finish_reason:
                        yield "data: [DONE]\n\n"

            # Auto-learn and persist memories into pgvector in background
            assistant_full = "".join(full_reply)
            if user_last_prompt and assistant_full:
                try:
                    async with async_session_factory() as db:
                        await learn_from_interaction(
                            session=db,
                            tenant_id=current_user.tenant_id,
                            user_id=current_user.user_id,
                            user_text=user_last_prompt,
                            assistant_text=assistant_full,
                        )
                        await db.commit()
                except Exception:
                    pass

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


# ── Multimodal Audio Endpoints ────────────────────────────────────────────────

@app.post("/audio/transcribe")
async def audio_transcribe_endpoint(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Real-time Speech-to-Text via Groq Whisper-large-v3-turbo."""
    from src.models.audio import transcribe_audio
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload")
    text = await transcribe_audio(audio_bytes, content_type=request.headers.get("content-type", "audio/wav"))
    return {"text": text}


class SpeakRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None


@app.post("/audio/speak")
async def audio_speak_endpoint(
    body: SpeakRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Text-to-Speech via ElevenLabs."""
    from src.models.audio import synthesize_speech
    audio_data = await synthesize_speech(body.text, voice_id=body.voice_id)
    if not audio_data:
        raise HTTPException(status_code=503, detail="TTS service unavailable or key not configured")
    from fastapi.responses import Response
    return Response(content=audio_data, media_type="audio/mpeg")


# ── Continuous Memory Management Endpoints ────────────────────────────────────

@app.get("/memory/list")
async def memory_list(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Returns stored semantic memories for the authenticated user."""
    from src.db.session import async_session_factory
    from sqlalchemy import select
    from src.db.models import MemoryEmbedding

    async with async_session_factory() as db:
        stmt = (
            select(MemoryEmbedding)
            .where(
                MemoryEmbedding.tenant_id == current_user.tenant_id,
                MemoryEmbedding.user_id == current_user.user_id,
            )
            .order_by(MemoryEmbedding.created_at.desc())
            .limit(30)
        )
        res = await db.execute(stmt)
        memories = res.scalars().all()
        return [
            {
                "id": str(m.id),
                "content": m.content,
                "scope": m.scope,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ]


class AddMemoryRequest(BaseModel):
    content: str
    scope: str = "user"


@app.post("/memory/add")
async def memory_add(
    body: AddMemoryRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Manually add a memory or fact to Hermes pgvector storage."""
    from src.db.session import async_session_factory
    from src.db.memory import default_memory_service
    from src.models.embeddings import get_embedding

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content required")

    async with async_session_factory() as db:
        embedding = await get_embedding(body.content)
        mem_id = await default_memory_service.add_memory(
            session=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            content=body.content.strip(),
            embedding=embedding,
            scope=body.scope,
            metadata={"source": "manual_user_entry"},
        )
        await db.commit()
        return {"status": "ok", "id": str(mem_id)}


# ── Integrations & Composio Endpoints ─────────────────────────────────────────

@app.get("/integrations/status")
async def integrations_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Returns connected tools and integrations for the user."""
    from src.tools.composio import ComposioAdapter, SUPPORTED_APPS
    adapter = ComposioAdapter()
    connected = await adapter.get_user_connected_apps(current_user.tenant_id, current_user.user_id)
    return {
        "composio_configured": bool(settings.COMPOSIO_API_KEY),
        "connected_apps": connected,
        "available_apps": SUPPORTED_APPS,
        "telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "google_chat_configured": bool(settings.GOOGLE_CHAT_SERVICE_ACCOUNT_PATH or settings.GOOGLE_CHAT_SERVICE_ACCOUNT_JSON),
    }


@app.get("/integrations/connect/{app_name}")
async def integrations_connect(
    app_name: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Generates OAuth connection URL for external tool (Gmail, Calendar, Drive, GitHub, Slack, etc.)."""
    from src.tools.composio import ComposioAdapter
    adapter = ComposioAdapter()
    url = await adapter.get_oauth_url(current_user.tenant_id, current_user.user_id, app_name.upper())
    if not url:
        raise HTTPException(status_code=400, detail=f"Could not generate connection URL for {app_name}")
    return {"app": app_name.upper(), "connection_url": url}


# ── Health & Doctor Endpoints ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/doctor")
async def doctor():
    report = await run_full_doctor()
    doctor_daemon = get_doctor()
    report["self_healing_events_last_hour"] = doctor_daemon.healing_count
    return report


# ── Root redirect ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)
