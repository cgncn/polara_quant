# polara_quant

Polara Quant is an automated research and paper-trading platform. It pulls market data, generates trading signals via strategy sleeves, applies risk controls, and places paper orders through Interactive Brokers — all with rigorous validation before any live capital is deployed.

## Quick Start (Docker)

```bash
docker compose up --build
curl http://localhost:8000/health
```

## Local Development

```bash
# Install uv if needed: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev
uv run uvicorn polara.api.main:app --reload
```

## VM Deployment

See `scripts/vm_setup.sh` for one-shot Ubuntu VM bootstrap.

## Architecture

- **API**: FastAPI + Uvicorn on port 8000
- **Database**: SQLite (paper phase) → PostgreSQL (pre-live)
- **Data**: Parquet + DuckDB for market data
- **Broker**: IB Gateway (paper first)

## Build Phases

- Phase 0-1: Foundation (current) — health checks, storage, core schemas
- Phase 2: Broker adapter + IB Gateway
- Phase 3: Data ingestion pipeline
- Phase 4: Research engine + strategies
- Phase 5: Risk guard + order manager
- Phase 6: Control plane UI
