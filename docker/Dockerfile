FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install uv (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.6.11 /uv /uvx /bin/

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies only
RUN uv sync --no-dev --no-editable --frozen

# Copy source code and config
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Create data directory for SQLite
RUN mkdir -p data

# Run as non-root user
RUN addgroup --system polara && adduser --system --ingroup polara --home /app polara
RUN chown -R polara:polara /app
ENV HOME=/app
USER polara

COPY --chmod=755 docker/entrypoint.sh ./entrypoint.sh
CMD ["./entrypoint.sh"]
