import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./data/polara.db"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session


async def ping_db() -> bool:
    """
    Run SELECT 1 against the database.
    Returns True if the DB is reachable, False otherwise.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.debug("ping_db failed: %s", exc, exc_info=True)
        return False
