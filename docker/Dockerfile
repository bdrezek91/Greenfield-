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

# `data` extras land in Phase 2 alongside the data layer. `backtest` and `ml`
# extras are added once those layers are implemented, to keep this image lean.
RUN pip install --no-cache-dir -e ".[dev,data]"

COPY . .

CMD ["sleep", "infinity"]
