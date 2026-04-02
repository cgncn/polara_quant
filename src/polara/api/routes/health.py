from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from polara.db.connection import ping_db

router = APIRouter()


class HealthResponse(BaseModel):
    status: str  # "ok" or "degraded"
    db: str  # "ok" or "error"
    version: str
    timestamp: str  # UTC ISO 8601


@router.get("/health", response_model=HealthResponse)
async def health_check() -> JSONResponse:
    db_ok = await ping_db()
    body = HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "error",
        version=_get_version(),
        timestamp=datetime.now(UTC).isoformat(),
    )
    status_code = 200 if db_ok else 503
    return JSONResponse(content=body.model_dump(), status_code=status_code)


def _get_version() -> str:
    from polara import __version__

    return __version__
