FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Core + dev deps only in Phase 1. The `data`, `backtest` and `ml` extras are
# installed once the corresponding layers are implemented, to keep this base
# image lean.
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

CMD ["sleep", "infinity"]
