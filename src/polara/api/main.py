import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from polara.api.routes.health import router as health_router
from polara.db.connection import DATABASE_URL

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    masked = _mask_db_url(DATABASE_URL)
    logger.info("Polara Quant %s starting — DB: %s", _get_version(), masked)
    yield
    logger.info("Polara Quant %s stopped", _get_version())


def create_app() -> FastAPI:
    app = FastAPI(title="Polara Quant", version=_get_version(), lifespan=_lifespan)

    app.include_router(health_router)

    return app


def _mask_db_url(url: str) -> str:
    """Mask credentials in DB URL for safe logging."""
    # sqlite URLs have no credentials; postgres URLs may have user:pass@host
    if "@" in url:
        scheme, rest = url.split("://", 1)
        host_part = rest.split("@", 1)[1]
        return f"{scheme}://***@{host_part}"
    return url


def _get_version() -> str:
    from polara import __version__

    return __version__


# Module-level app instance for uvicorn
app = create_app()
