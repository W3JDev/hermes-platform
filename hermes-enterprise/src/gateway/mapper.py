"""
Tenant/User/Session resolver for all omnichannel gateways.
Maps (platform, external_team_id, external_user_id) → (tenant_id, user_id, conversation_id).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    GatewayPlatform,
    OmnichannelSession,
    GatewayBinding,
    User,
    UserRole,
    Conversation,
)
from src.db.session import async_session_factory
from src.auth.jwt import hash_password


@dataclass
class InternalContext:
    tenant_id: UUID
    user_id: UUID
    conversation_id: UUID
    platform: str
    is_new_user: bool = False


class GatewayMapper:
    """
    Resolves external platform identifiers to internal tenant/user/conversation IDs.
    Creates shadow users for new platform members on first contact.
    """

    async def resolve_or_create(
        self,
        platform: str,
        external_team_id: str,
        external_user_id: str,
        display_name: str = "",
    ) -> Optional[InternalContext]:
        async with async_session_factory() as db:
            # 1. Find tenant via GatewayBinding (team_id → tenant)
            binding_result = await db.execute(
                select(GatewayBinding).where(
                    GatewayBinding.platform == platform,
                    GatewayBinding.external_team_id == external_team_id,
                )
            )
            binding = binding_result.scalar_one_or_none()

            if binding is None:
                # No binding — use default tenant for now
                from src.db.models import Tenant
                from src.config import settings
                tenant_result = await db.execute(
                    select(Tenant).where(Tenant.slug == settings.ADMIN_DEFAULT_TENANT)
                )
                tenant = tenant_result.scalar_one_or_none()
                if tenant is None:
                    return None
                tenant_id = tenant.id
            else:
                tenant_id = binding.tenant_id

            # 2. Find or create user for this external_user_id
            user_result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.preferences["gateway_id"].astext == f"{platform}:{external_user_id}",
                )
            )
            user = user_result.scalar_one_or_none()
            is_new = False

            if user is None:
                # Auto-provision a shadow user for this gateway participant
                username = f"{platform}_{external_user_id}"[:50]
                user = User(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    username=username,
                    email=f"{username}@gateway.hermes.local",
                    password_hash=hash_password(uuid4().hex),
                    role=UserRole.MEMBER,
                    is_active=True,
                    preferences={
                        "gateway_id": f"{platform}:{external_user_id}",
                        "display_name": display_name,
                        "platform": platform,
                    },
                )
                db.add(user)
                await db.flush()
                is_new = True

            user_id = user.id

            # 3. Find or create active Conversation
            conv_result = await db.execute(
                select(Conversation).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.user_id == user_id,
                    Conversation.is_active == True,
                ).order_by(Conversation.updated_at.desc())
            )
            conv = conv_result.scalar_one_or_none()

            if conv is None:
                conv = Conversation(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=f"{platform} conversation",
                    model_name="claude/claude-sonnet-4-6",
                    is_active=True,
                    metadata={"platform": platform, "external_user_id": external_user_id},
                )
                db.add(conv)
                await db.flush()

            await db.commit()
            return InternalContext(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conv.id,
                platform=platform,
                is_new_user=is_new,
            )
