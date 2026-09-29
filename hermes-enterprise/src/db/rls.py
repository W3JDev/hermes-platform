"""
PostgreSQL Row-Level Security (RLS) Context Isolation & Context Managers.
Guarantees strict tenant and user isolation across asyncpg connection pools.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
import logging
from typing import Any, AsyncGenerator, Optional
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("hermes.db.rls")

# ---------------------------------------------------------------------------
# 1. Async Task-Local Context Variables
# ---------------------------------------------------------------------------
_tenant_id_ctx: ContextVar[Optional[UUID]] = ContextVar("tenant_id_ctx", default=None)
_user_id_ctx: ContextVar[Optional[UUID]] = ContextVar("user_id_ctx", default=None)
_is_admin_ctx: ContextVar[bool] = ContextVar("is_admin_ctx", default=False)
_system_bypass_ctx: ContextVar[bool] = ContextVar("system_bypass_ctx", default=False)


def get_current_tenant_id_ctx() -> Optional[UUID]:
    """Retrieve the current coroutine-local tenant ID."""
    return _tenant_id_ctx.get()


def get_current_user_id_ctx() -> Optional[UUID]:
    """Retrieve the current coroutine-local user ID."""
    return _user_id_ctx.get()


def is_admin_ctx() -> bool:
    """Check if the current coroutine context has tenant admin privileges."""
    return _is_admin_ctx.get()


def is_system_bypass_ctx() -> bool:
    """Check if the current coroutine context has system bypass privileges."""
    return _system_bypass_ctx.get()


# ---------------------------------------------------------------------------
# 2. Database Session Context Injector (SET LOCAL)
# ---------------------------------------------------------------------------
async def set_rls_context(
    session: AsyncSession,
    tenant_id: Optional[UUID],
    user_id: Optional[UUID] = None,
    is_admin: bool = False,
    system_bypass: bool = False,
) -> None:
    """
    Set PostgreSQL transaction-local configuration parameters for RLS.
    Must be executed inside an active transaction.
    """
    if system_bypass:
        await session.execute(text("SET LOCAL app.bypass_rls = 'on';"))
        logger.debug("Database RLS context set: SYSTEM_BYPASS=ON")
        return

    await session.execute(text("SET LOCAL app.bypass_rls = 'off';"))

    if tenant_id:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :val, true);"),
            {"val": str(tenant_id)},
        )
    else:
        await session.execute(text("SELECT set_config('app.current_tenant_id', '', true);"))

    if user_id:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :val, true);"),
            {"val": str(user_id)},
        )
    else:
        await session.execute(text("SELECT set_config('app.current_user_id', '', true);"))

    admin_str = "true" if is_admin else "false"
    await session.execute(
        text("SELECT set_config('app.is_admin', :val, true);"),
        {"val": admin_str},
    )

    logger.debug(
        "Database RLS context set: tenant_id=%s, user_id=%s, is_admin=%s",
        tenant_id,
        user_id,
        is_admin,
    )


# ---------------------------------------------------------------------------
# 3. High-Level Async Context Managers
# ---------------------------------------------------------------------------
@asynccontextmanager
async def tenant_transaction_context(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: Optional[UUID] = None,
    is_admin: bool = False,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager establishing a secure, isolated database transaction.
    Sets both Python contextvars and PostgreSQL SET LOCAL parameters.
    Automatically commits on normal exit and rolls back on exception.
    """
    t_token = _tenant_id_ctx.set(tenant_id)
    u_token = _user_id_ctx.set(user_id)
    a_token = _is_admin_ctx.set(is_admin)
    b_token = _system_bypass_ctx.set(False)

    try:
        in_tx = session.in_transaction() if callable(getattr(session, "in_transaction", None)) else False
        if hasattr(in_tx, "__await__"):
            # In case of AsyncMock in tests
            in_tx = False
    except Exception:
        in_tx = False

    try:
        if not in_tx:
            begin_ctx = session.begin()
            if hasattr(begin_ctx, "__aenter__"):
                async with begin_ctx:
                    await set_rls_context(
                        session=session,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        is_admin=is_admin,
                        system_bypass=False,
                    )
                    yield session
            else:
                await set_rls_context(
                    session=session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    is_admin=is_admin,
                    system_bypass=False,
                )
                yield session
        else:
            await set_rls_context(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                is_admin=is_admin,
                system_bypass=False,
            )
            yield session
    finally:
        _tenant_id_ctx.reset(t_token)
        _user_id_ctx.reset(u_token)
        _is_admin_ctx.reset(a_token)
        _system_bypass_ctx.reset(b_token)


@asynccontextmanager
async def system_transaction_context(
    session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for background daemons (Auto-Doctor, maintenance, migrations)
    requiring cross-tenant access with explicit auditability.
    """
    b_token = _system_bypass_ctx.set(True)
    try:
        in_tx = session.in_transaction() if callable(getattr(session, "in_transaction", None)) else False
        if hasattr(in_tx, "__await__"):
            in_tx = False
    except Exception:
        in_tx = False

    try:
        if not in_tx:
            begin_ctx = session.begin()
            if hasattr(begin_ctx, "__aenter__"):
                async with begin_ctx:
                    await set_rls_context(
                        session=session,
                        tenant_id=None,
                        user_id=None,
                        is_admin=False,
                        system_bypass=True,
                    )
                    yield session
            else:
                await set_rls_context(
                    session=session,
                    tenant_id=None,
                    user_id=None,
                    is_admin=False,
                    system_bypass=True,
                )
                yield session
        else:
            await set_rls_context(
                session=session,
                tenant_id=None,
                user_id=None,
                is_admin=False,
                system_bypass=True,
            )
            yield session
    finally:
        _system_bypass_ctx.reset(b_token)


# ---------------------------------------------------------------------------
# 4. FastAPI Dependency Injections
# ---------------------------------------------------------------------------
async def get_isolated_db_session(
    user: Any,
    session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding an AsyncSession pre-configured with RLS
    matching the authenticated request context.
    """
    is_admin = (getattr(user, "role", "") == "admin")
    tenant_id = getattr(user, "tenant_id", None)
    user_id = getattr(user, "id", None) or getattr(user, "user_id", None)

    async with tenant_transaction_context(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        is_admin=is_admin,
    ) as isolated_session:
        yield isolated_session


# ---------------------------------------------------------------------------
# 5. Connection Pool Sanitization (Defense-In-Depth)
# ---------------------------------------------------------------------------
def configure_pool_sanitization(sync_engine: Any) -> None:
    """
    Attach pool event listeners ensuring physical connections are sanitized
    upon return to the pool.
    """
    @event.listens_for(sync_engine, "checkin")
    def receive_checkin(dbapi_connection: Any, connection_record: Any) -> None:
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("RESET ALL;")
            cursor.close()
        except Exception as exc:
            logger.warning("Error resetting pooled connection state: %s", exc)
