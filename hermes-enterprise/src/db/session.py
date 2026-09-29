"""Async SQLAlchemy session factory and database initialization."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database session injection."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables on startup (idempotent). Resilient if DB is not immediately available."""
    from src.db.models import Base
    from sqlalchemy import text

    try:
        async with engine.begin() as conn:
            # Enable pgvector extension if supported
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception as e:
                print(f"[DB] Notice: vector extension: {e}")
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
            # Enable RLS on core tables
            for table in ["agent_memories", "conversations", "messages", "user_sessions"]:
                try:
                    await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                except Exception:
                    pass
            print("[DB] [OK] Database initialized successfully.")
    except Exception as e:
        print(f"[DB] [WARN] DB init deferred (will retry via Auto-Doctor): {e}")


# ── Compatibility aliases for db/__init__.py ──────────────────────────────────
AsyncSessionLocal = async_session_factory


async def get_tenant_db(tenant_id=None):
    """Alias for get_db — tenant context set via RLS separately."""
    async for session in get_db():
        yield session


from contextlib import asynccontextmanager


@asynccontextmanager
async def db_session_scope():
    """Context manager for a single transactional session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def probe_db_health() -> bool:
    """Return True if database is reachable."""
    from sqlalchemy import text
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
