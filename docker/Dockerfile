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

# `data` (Phase 2) and `backtest` (Phase 3) extras are active. `ml` is added
# once that layer is implemented, to keep this image lean.
RUN pip install --no-cache-dir -e ".[dev,data,backtest]"

COPY . .

CMD ["sleep", "infinity"]
