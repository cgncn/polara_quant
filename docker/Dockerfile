FROM python:3.12-slim
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies only
RUN uv sync --no-dev --no-editable

# Copy source code and config
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Create data directory for SQLite
RUN mkdir -p data

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn polara.api.main:app --host 0.0.0.0 --port 8000"]
