"""Admin API router: user provisioning, session management, usage telemetry."""

from __future__ import annotations

from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import AuthenticatedUser, require_admin
from src.auth.service import (
    create_user,
    generate_invite_url,
    get_token_usage_stats,
    list_active_sessions,
    list_users,
    revoke_session,
)
from src.db.session import get_db
from uuid import UUID

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request/Response Models ───────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "member"


class UserOut(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    is_active: bool


class SessionOut(BaseModel):
    session_id: str
    user_id: str
    username: str
    channel: str
    last_seen_at: str | None


class UsageStatOut(BaseModel):
    username: str
    model_provider: str
    model_name: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class InviteOut(BaseModel):
    invite_url: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_team_member(
    body: CreateUserRequest,
    current_user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await create_user(
        db,
        tenant_id=current_user.tenant_id,
        username=body.username,
        email=body.email,
        password=body.password,
        role=body.role,
    )
    await db.commit()
    return UserOut(
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        is_active=user.is_active,
    )


@router.get("/users", response_model=List[UserOut])
async def get_all_users(
    current_user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = await list_users(db, current_user.tenant_id)
    return [
        UserOut(
            user_id=str(u.id),
            username=u.username,
            email=u.email,
            role=u.role.value,
            is_active=u.is_active,
        )
        for u in users
    ]


@router.get("/sessions", response_model=List[SessionOut])
async def get_active_sessions(
    current_user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    sessions = await list_active_sessions(db, current_user.tenant_id)
    return [
        SessionOut(
            session_id=str(s.session_id),
            user_id=str(s.user_id),
            username=s.username,
            channel=s.channel,
            last_seen_at=s.last_seen_at.isoformat() if s.last_seen_at else None,
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kill_session(
    session_id: str,
    current_user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await revoke_session(db, UUID(session_id))
    await db.commit()


@router.get("/usage", response_model=List[UsageStatOut])
async def get_usage(
    current_user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stats = await get_token_usage_stats(db, current_user.tenant_id)
    return [
        UsageStatOut(
            username=s.username,
            model_provider=s.model_provider,
            model_name=s.model_name,
            total_input_tokens=s.total_input_tokens,
            total_output_tokens=s.total_output_tokens,
            total_cost_usd=s.total_cost_usd,
        )
        for s in stats
    ]


@router.post("/users/{user_id}/invite", response_model=InviteOut)
async def invite_user(
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_admin),
):
    url = generate_invite_url(current_user.tenant_id, role="member")
    return InviteOut(invite_url=url)
