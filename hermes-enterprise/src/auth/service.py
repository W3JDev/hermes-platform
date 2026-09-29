"""Auth service: user creation, authentication, session management, invite links."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt import (
    create_invite_token,
    hash_password,
    verify_password,
)
from src.config import settings
from src.db.models import TokenUsage, Tenant, User, UserRole, UserSession


# ── Data Transfer Objects ─────────────────────────────────────────────────────

@dataclass
class SessionInfo:
    session_id: UUID
    user_id: UUID
    username: str
    channel: str
    created_at: datetime
    last_seen_at: Optional[datetime]
    is_active: bool


@dataclass
class TokenUsageStat:
    user_id: UUID
    username: str
    model_provider: str
    model_name: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


# ── Core Service Functions ────────────────────────────────────────────────────

async def get_or_create_default_tenant(db: AsyncSession) -> Tenant:
    """Ensure the default tenant exists; create on first boot."""
    result = await db.execute(
        select(Tenant).where(Tenant.slug == settings.ADMIN_DEFAULT_TENANT)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            id=uuid4(),
            name="Default Organization",
            slug=settings.ADMIN_DEFAULT_TENANT,
            plan="enterprise",
            settings={},
        )
        db.add(tenant)
        await db.flush()
    return tenant


async def bootstrap_admin_user(db: AsyncSession) -> User:
    """Create the default admin user on first boot if it doesn't exist."""
    tenant = await get_or_create_default_tenant(db)
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant.id,
            User.username == settings.ADMIN_DEFAULT_USERNAME,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid4(),
            tenant_id=tenant.id,
            username=settings.ADMIN_DEFAULT_USERNAME,
            email=settings.ADMIN_DEFAULT_EMAIL,
            password_hash=hash_password(settings.ADMIN_DEFAULT_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    return user


async def create_user(
    db: AsyncSession,
    tenant_id: UUID,
    username: str,
    email: str,
    password: str,
    role: str = "member",
) -> User:
    """Provision a new team member."""
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=UserRole(role),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(
    db: AsyncSession,
    tenant_id: UUID,
    username: str,
    password: str,
) -> Optional[User]:
    """Verify credentials; return User or None. Supports username or email (case-insensitive)."""
    clean_id = username.strip().lower()
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.is_active == True,
            or_(
                func.lower(User.username) == clean_id,
                func.lower(User.email) == clean_id,
            ),
        )
    )
    user = result.scalar_one_or_none()
    if user and verify_password(password, user.password_hash):
        return user
    return None


async def create_session(db: AsyncSession, user: User, channel: str = "web") -> UserSession:
    """Record a new active session for audit and revocation tracking."""
    session = UserSession(
        id=uuid4(),
        user_id=user.id,
        tenant_id=user.tenant_id,
        channel=channel,
        session_token=secrets.token_urlsafe(32),
        is_active=True,
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()
    return session


async def revoke_session(db: AsyncSession, session_id: UUID) -> None:
    """Mark a session as revoked."""
    await db.execute(
        update(UserSession)
        .where(UserSession.id == session_id)
        .values(is_active=False)
    )


async def list_active_sessions(db: AsyncSession, tenant_id: UUID) -> List[SessionInfo]:
    """List all active sessions for a tenant."""
    result = await db.execute(
        select(UserSession, User.username)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.tenant_id == tenant_id,
            UserSession.is_active == True,
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    rows = result.all()
    return [
        SessionInfo(
            session_id=s.id,
            user_id=s.user_id,
            username=username,
            channel=s.channel,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            is_active=s.is_active,
        )
        for s, username in rows
    ]


async def list_users(db: AsyncSession, tenant_id: UUID) -> List[User]:
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
    )
    return list(result.scalars().all())


async def get_token_usage_stats(db: AsyncSession, tenant_id: UUID) -> List[TokenUsageStat]:
    """Aggregate token usage per user/model for the admin dashboard."""
    from sqlalchemy import func as sqlfunc
    agg_result = await db.execute(
        select(
            TokenUsage.user_id,
            User.username,
            TokenUsage.provider.label("model_provider"),
            TokenUsage.model_name,
            sqlfunc.sum(TokenUsage.prompt_tokens).label("total_input"),
            sqlfunc.sum(TokenUsage.completion_tokens).label("total_output"),
            sqlfunc.sum(TokenUsage.estimated_cost_usd).label("total_cost"),
        )
        .join(User, User.id == TokenUsage.user_id)
        .where(TokenUsage.tenant_id == tenant_id)
        .group_by(TokenUsage.user_id, User.username, TokenUsage.provider, TokenUsage.model_name)
    )
    return [
        TokenUsageStat(
            user_id=row.user_id,
            username=row.username,
            model_provider=row.model_provider,
            model_name=row.model_name,
            total_input_tokens=int(row.total_input or 0),
            total_output_tokens=int(row.total_output or 0),
            total_cost_usd=float(row.total_cost or 0.0),
        )
        for row in agg_result.all()
    ]


def generate_invite_url(tenant_id: UUID, role: str = "member") -> str:
    """Generate a time-limited invite URL for new team members."""
    token = create_invite_token(tenant_id, role)
    return f"{settings.BASE_URL}/auth/accept-invite?token={token}"
