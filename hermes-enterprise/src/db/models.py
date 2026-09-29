"""
SQLAlchemy 2.0 Async Models for Nous Hermes Enterprise Agent.
Defines all 15 tables supporting multi-tenancy, persistent vector memory,
omnichannel gateways, and enterprise administration.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ============================================================================
# Base Declarative Class
# ============================================================================

class Base(AsyncAttrs, DeclarativeBase):
    """Base declarative class with async attribute support."""
    type_annotation_map = {
        dict: JSONB,
        Dict[str, Any]: JSONB,
        List[str]: JSONB,
        List[Dict[str, Any]]: JSONB,
    }


# ============================================================================
# Enumerations
# ============================================================================

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class ChatChannel(str, enum.Enum):
    WEB = "web"
    GOOGLE_CHAT = "google_chat"
    TELEGRAM = "telegram"
    SLACK = "slack"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class GatewayPlatform(str, enum.Enum):
    GOOGLE_CHAT = "google_chat"
    TELEGRAM = "telegram"
    SLACK = "slack"


# ============================================================================
# 1. Tenants Table
# ============================================================================

class Tenant(Base):
    """
    Enterprise tenant/organization root entity.
    Isolates all users, conversations, memories, files, and token quotas.
    """
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    max_monthly_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=50_000_000, server_default="50000000"
    )
    plan: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="enterprise", server_default="enterprise")
    settings: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )

    # Relationships
    users: Mapped[List[User]] = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    conversations: Mapped[List[Conversation]] = relationship(
        "Conversation", back_populates="tenant", cascade="all, delete-orphan"
    )
    user_sessions: Mapped[List[UserSession]] = relationship(
        "UserSession", back_populates="tenant", cascade="all, delete-orphan"
    )
    invitations: Mapped[List[Invitation]] = relationship(
        "Invitation", back_populates="tenant", cascade="all, delete-orphan"
    )
    files: Mapped[List[UserFile]] = relationship(
        "UserFile", back_populates="tenant", cascade="all, delete-orphan"
    )
    memories: Mapped[List[MemoryEmbedding]] = relationship(
        "MemoryEmbedding", back_populates="tenant", cascade="all, delete-orphan"
    )
    token_usages: Mapped[List[TokenUsage]] = relationship(
        "TokenUsage", back_populates="tenant", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List[AuditLog]] = relationship(
        "AuditLog", back_populates="tenant", cascade="all, delete-orphan"
    )
    integrations: Mapped[List[TenantIntegration]] = relationship(
        "TenantIntegration", back_populates="tenant", cascade="all, delete-orphan"
    )
    gateway_configs: Mapped[List[TenantGatewayConfig]] = relationship(
        "TenantGatewayConfig", back_populates="tenant", cascade="all, delete-orphan"
    )


# ============================================================================
# 2. Users Table
# ============================================================================

class User(Base):
    """
    User entity within a specific tenant.
    Supports RBAC ('admin' vs 'member') and isolated workspace ownership.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum", values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserRole.MEMBER, server_default="member"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    @property
    def password_hash(self) -> str:
        return self.hashed_password

    @password_hash.setter
    def password_hash(self, val: str) -> None:
        self.hashed_password = val
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_tenant_username"),
        UniqueConstraint("tenant_id", "email", name="uq_tenant_email"),
        Index("idx_users_tenant_lookup", "tenant_id", "is_active"),
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="users")
    preferences: Mapped[Optional[UserPreference]] = relationship(
        "UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[List[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[List[Conversation]] = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )
    messages: Mapped[List[Message]] = relationship(
        "Message", back_populates="user", cascade="all, delete-orphan"
    )
    files: Mapped[List[UserFile]] = relationship(
        "UserFile", back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[List[MemoryEmbedding]] = relationship(
        "MemoryEmbedding", back_populates="user", cascade="all, delete-orphan"
    )
    token_usages: Mapped[List[TokenUsage]] = relationship(
        "TokenUsage", back_populates="user", cascade="all, delete-orphan"
    )
    gateway_bindings: Mapped[List[UserGatewayBinding]] = relationship(
        "UserGatewayBinding", back_populates="user", cascade="all, delete-orphan"
    )


# ============================================================================
# 3. Invitations Table
# ============================================================================

class Invitation(Base):
    """
    Sharable one-time onboarding invitation tokens.
    Hashed with SHA-256 for secure storage and time-limited acceptance.
    """
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum", values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserRole.MEMBER, server_default="member"
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_invitations_token_lookup", "token_hash", "is_accepted"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="invitations")
    creator: Mapped[Optional[User]] = relationship("User")


# ============================================================================
# 4. User Sessions Table
# ============================================================================

class UserSession(Base):
    """
    Active user session registry for real-time monitoring and instant revocation.
    """
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    session_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="web", server_default="web")
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        Index("idx_sessions_user_tenant", "user_id", "tenant_id", "is_revoked"),
    )

    user: Mapped[User] = relationship("User", back_populates="sessions")
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="user_sessions")


# ============================================================================
# 5. Conversations Table
# ============================================================================

class Conversation(Base):
    """
    Chat conversation thread.
    Can be originated from web, Google Chat, Telegram, or Slack.
    """
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New Conversation", server_default="New Conversation")
    channel: Mapped[ChatChannel] = mapped_column(
        Enum(ChatChannel, name="chat_channel_enum", values_callable=lambda x: [e.value for e in x]), nullable=False, default=ChatChannel.WEB, server_default="web"
    )
    external_channel_thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )

    __table_args__ = (
        Index("idx_conversations_user_tenant", "user_id", "tenant_id", "updated_at"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="conversations")
    user: Mapped[User] = relationship("User", back_populates="conversations")
    messages: Mapped[List[Message]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    memories: Mapped[List[MemoryEmbedding]] = relationship(
        "MemoryEmbedding", back_populates="conversation"
    )


# ============================================================================
# 6. Messages Table
# ============================================================================

class Message(Base):
    """
    Individual conversational turn.
    Stores content, reasoning trace, tool calls, tool results, and token metrics.
    """
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role_enum", values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    tool_results: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id", "created_at"),
        Index("idx_messages_tenant_user", "tenant_id", "user_id"),
    )

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
    tenant: Mapped[Tenant] = relationship("Tenant")
    user: Mapped[User] = relationship("User", back_populates="messages")


# ============================================================================
# 7. Memory Embeddings Table (pgvector & Full-Text Search)
# ============================================================================

class MemoryEmbedding(Base):
    """
    Semantic long-term memory store combining:
    - 768-dimensional dense vector embeddings (HNSW indexed).
    - Lexical tsvector (GIN indexed) for BM25 keyword matching.
    - Used by Reciprocal Rank Fusion (RRF) hybrid search.
    """
    __tablename__ = "memory_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="user", server_default="user")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=False)
    tsv: Mapped[Optional[Any]] = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        Index("idx_memory_tenant_user", "tenant_id", "user_id", "scope"),
        Index(
            "idx_memory_hnsw_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        Index("idx_memory_tsv", "tsv", postgresql_using="gin"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="memories")
    user: Mapped[Optional[User]] = relationship("User", back_populates="memories")
    conversation: Mapped[Optional[Conversation]] = relationship("Conversation", back_populates="memories")


# ============================================================================
# 8. User Preferences Table
# ============================================================================

class UserPreference(Base):
    """
    Isolated user workspace preferences: system prompt override, persona,
    default models, temperature, and active tool switches.
    """
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_prompt_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    persona_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Hermes Enterprise Agent", server_default="Hermes Enterprise Agent"
    )
    default_model: Mapped[str] = mapped_column(
        String(100), nullable=False, default="gemini-2.5-flash", server_default="gemini-2.5-flash"
    )
    temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.70"), server_default="0.70"
    )
    top_p: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.95"), server_default="0.95"
    )
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4096, server_default="4096"
    )
    enabled_tools: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["google_workspace", "composio", "web_browser", "bash"],
        server_default=text('\'["google_workspace", "composio", "web_browser", "bash"]\'::jsonb'),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )

    user: Mapped[User] = relationship("User", back_populates="preferences")
    tenant: Mapped[Tenant] = relationship("Tenant")


# ============================================================================
# 9. User Files Table
# ============================================================================

class UserFile(Base):
    """
    Metadata and integrity checksums for private workspace files.
    Physical files are saved in `/var/hermes/data/tenants/{tid}/users/{uid}/`.
    """
    __tablename__ = "user_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sanitized_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        Index("idx_user_files_lookup", "user_id", "tenant_id"),
    )

    user: Mapped[User] = relationship("User", back_populates="files")
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="files")


# ============================================================================
# 10. Tenant Integrations Table
# ============================================================================

class TenantIntegration(Base):
    """
    Connected SaaS accounts and MCP integrations (Google Workspace, Composio).
    Stores encrypted OAuth tokens (AES-256-GCM) and service configurations.
    """
    __tablename__ = "tenant_integrations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    integration_type: Mapped[str] = mapped_column(String(50), nullable=False)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "integration_type", name="uq_tenant_user_integration"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="integrations")
    user: Mapped[Optional[User]] = relationship("User")


# ============================================================================
# 11. Token Usage Telemetry Table
# ============================================================================

class TokenUsage(Base):
    """
    Granular LLM token consumption and cost accounting.
    Aggregated for tenant quotas and administrative monitoring.
    """
    __tablename__ = "token_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0.000000"), server_default="0.000000"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        Index("idx_token_usage_tenant_ts", "tenant_id", "timestamp"),
        Index("idx_token_usage_user_ts", "user_id", "timestamp"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="token_usages")
    user: Mapped[User] = relationship("User", back_populates="token_usages")


# ============================================================================
# 12. Security Audit Logs Table
# ============================================================================

class AuditLog(Base):
    """
    Immutable audit trail for compliance and administrative review.
    Tracks logins, user provisioning, credential changes, and revocations.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        Index("idx_audit_logs_tenant_ts", "tenant_id", "created_at"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="audit_logs")
    actor: Mapped[Optional[User]] = relationship("User")


# ============================================================================
# 13. Tenant Gateway Configurations Table (Gateway)
# ============================================================================

class TenantGatewayConfig(Base):
    """
    Platform configurations for Google Chat, Telegram, and Slack gateways.
    """
    __tablename__ = "tenant_gateway_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_tenant_identifier: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bot_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("platform", "platform_tenant_identifier", name="uq_gateway_platform_tenant"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="gateway_configs")


# ============================================================================
# 14. User Gateway Bindings Table (Gateway)
# ============================================================================

class UserGatewayBinding(Base):
    """
    Maps external chat identities (Telegram Chat ID, Slack User ID, Google Chat User ID)
    to internal user accounts with pairing code verification.
    """
    __tablename__ = "user_gateway_bindings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    pairing_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    pairing_code_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_gateway_platform_user"),
        Index("idx_gateway_binding_lookup", "platform", "platform_user_id", "is_verified"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant")
    user: Mapped[User] = relationship("User", back_populates="gateway_bindings")


# ============================================================================
# 15. Gateway Conversational Sessions Table (Gateway)
# ============================================================================

class GatewayConversationalSession(Base):
    """
    Maps external chat thread IDs (Google Chat thread name, Telegram topic/thread,
    Slack thread_ts) to persistent internal conversation_id.
    """
    __tablename__ = "gateway_conversational_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_interaction_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        UniqueConstraint("platform", "platform_channel_id", "platform_thread_id", name="uq_gateway_session_channel_thread"),
        Index("idx_gateway_session_lookup", "platform", "platform_channel_id", "platform_thread_id"),
    )

    tenant: Mapped[Tenant] = relationship("Tenant")
    user: Mapped[User] = relationship("User")
    conversation: Mapped[Conversation] = relationship("Conversation")


# ── Compatibility Aliases ───────────────────────────────────────────────────
ModelUsageLog = TokenUsage
AgentMemory = MemoryEmbedding
GatewayBinding = UserGatewayBinding
OmnichannelSession = GatewayConversationalSession
SkillRecord = TenantIntegration
FileRecord = UserFile

