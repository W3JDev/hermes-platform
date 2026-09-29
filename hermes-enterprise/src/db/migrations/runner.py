"""
Automatic Database Migration Runner for Application Startup.
Utilizes PostgreSQL Advisory Locking to prevent multi-instance race conditions.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings

logger = logging.getLogger("hermes.db.migrations")

# Deterministic 64-bit integer for PostgreSQL advisory lock
HERMES_MIGRATION_ADVISORY_LOCK_ID = 849201948


def _get_alembic_config() -> Config:
    """Constructs Alembic Config object pointing to the repository alembic.ini."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    ini_path = project_root / "alembic.ini"
    if not ini_path.exists():
        ini_path = project_root / "src" / "db" / "migrations" / "alembic.ini"

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(project_root / "src" / "db" / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return alembic_cfg


def _run_upgrade_sync() -> None:
    """Executes alembic upgrade head synchronously."""
    cfg = _get_alembic_config()
    command.upgrade(cfg, "head")


async def run_migrations_with_advisory_lock(
    max_retries: int = 15,
    retry_delay_seconds: float = 2.0,
) -> None:
    """
    Connects to PostgreSQL, acquires an exclusive advisory lock, and applies
    all pending Alembic migrations. If another instance holds the lock, waits
    until migrations are complete.
    """
    logger.info("Initializing database connection and migration verification...")
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

    # 1. Wait for database readiness
    connected = False
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1;"))
            connected = True
            logger.info("Database connection established successfully.")
            break
        except Exception as exc:
            logger.warning(
                f"Database not ready yet (attempt {attempt}/{max_retries}): {exc}. "
                f"Retrying in {retry_delay_seconds}s..."
            )
            await asyncio.sleep(retry_delay_seconds)

    if not connected:
        await engine.dispose()
        raise RuntimeError("Failed to connect to PostgreSQL database after maximum retries.")

    # 2. Acquire Advisory Lock and Run Upgrade
    async with engine.connect() as conn:
        logger.info(f"Attempting to acquire migration advisory lock ({HERMES_MIGRATION_ADVISORY_LOCK_ID})...")
        lock_acquired = False

        try:
            for _ in range(30):
                result = await conn.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id);"),
                    {"lock_id": HERMES_MIGRATION_ADVISORY_LOCK_ID},
                )
                lock_acquired = bool(result.scalar())
                if lock_acquired:
                    break
                logger.info("Migration lock held by another process; waiting 2s...")
                await asyncio.sleep(2.0)

            if lock_acquired:
                logger.info("Acquired migration lock. Running Alembic upgrade head...")
                await asyncio.to_thread(_run_upgrade_sync)
                logger.info("Alembic migrations completed successfully.")
            else:
                logger.warning(
                    "Could not acquire migration lock within timeout. "
                    "Proceeding assuming leader worker finished migrations."
                )
        finally:
            if lock_acquired:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:lock_id);"),
                    {"lock_id": HERMES_MIGRATION_ADVISORY_LOCK_ID},
                )
                logger.info("Released migration advisory lock.")

    await engine.dispose()


async def check_migration_status() -> Dict[str, Any]:
    """
    Diagnostic telemetry probe for the Auto-Doctor (/doctor) endpoint.
    Returns current DB revision and head revision.
    """
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            def _get_status(sync_conn: Any) -> Dict[str, Any]:
                cfg = _get_alembic_config()
                script = ScriptDirectory.from_config(cfg)
                head_rev = script.get_current_head()
                context = MigrationContext.configure(sync_conn)
                current_rev = context.get_current_revision()
                return {
                    "current_revision": current_rev,
                    "head_revision": head_rev,
                    "is_up_to_date": current_rev == head_rev,
                }

            status = await conn.run_sync(_get_status)
            return status
    except Exception as exc:
        return {
            "current_revision": None,
            "head_revision": None,
            "is_up_to_date": False,
            "error": str(exc),
        }
    finally:
        await engine.dispose()
