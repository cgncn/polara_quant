#!/usr/bin/env sh
set -e
uv run alembic upgrade head
exec uv run uvicorn polara.api.main:app --host 0.0.0.0 --port 8000
