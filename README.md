# ai-trading-lab

A modular research platform for systematic trading strategy research on
Kraken Futures (EEA-eligible USD perpetuals) — backtesting, walk-forward
validation, statistical analysis, market regime research, machine
learning, and paper execution.

This is a greenfield project. It is not connected to, and does not reuse,
any previous trading system, strategy, or repository.

The goal is not the highest backtest profit — it's a system that can answer
whether a strategy has a real, stable edge, in which market conditions it
holds, and when it stops working. See `docs/RESEARCH_METHODOLOGY.md`.

## Status

See `docs/PROJECT_STATUS.md` for the current state (data, backtesting,
risk/portfolio, ML, and paper-execution layers are all implemented) and
`docs/PHASE_0_ARCHITECTURE_RESEARCH.md` for the original architecture
decision behind this repository.

## Architecture

```
DATA -> FEATURES -> STRATEGY/SIGNAL -> BACKTEST ENGINE -> RISK ENGINE
     -> PORTFOLIO ENGINE -> EXECUTION -> ANALYTICS -> ML/AI
```

Engine: [NautilusTrader](https://nautilustrader.io) for backtest/paper/live,
[VectorBT](https://vectorbt.dev) for exploratory parameter analysis. Full
rationale in `docs/PHASE_0_ARCHITECTURE_RESEARCH.md`. Layer-by-layer design
in `docs/ARCHITECTURE.md`.

## Getting started

```bash
git clone <repo-url>
cd ai-trading-lab
cp .env.example .env
docker compose build
docker compose up -d research
docker compose run --rm tests
```

See `docs/VPS_DEPLOYMENT.md` for full deployment instructions.

## Runtime modes

`RESEARCH`, `BACKTEST`, `PAPER` are available. `LIVE` is disabled by default
and requires an explicit safety mechanism not yet implemented — see
`docs/VPS_DEPLOYMENT.md`.

## Repository layout

```
src/            data / features / strategies / regimes / backtesting /
                risk / portfolio / execution / ml / analytics
configs/        experiment, symbol, timeframe, risk configuration
scripts/        CLI entry points (data download, backtest runs, reports)
tests/          unit, integration, data_integrity, lookahead, strategy
research/       exploratory, non-production notebooks/scripts
reports/        generated experiment reports (not committed data)
docker/         Dockerfile(s)
docs/           architecture, methodology, data, backtesting, ML, deployment
```

## Documentation

- `docs/PHASE_0_ARCHITECTURE_RESEARCH.md` — technology research and the architecture decision
- `docs/ARCHITECTURE.md` — layer boundaries and how the code implements them
- `docs/RESEARCH_METHODOLOGY.md` — how experiments are validated and judged
- `docs/DATA.md` — data sources, storage, integrity checks
- `docs/BACKTESTING.md` — backtest realism requirements, lookahead protection
- `docs/ML.md` — ML principles, baselines, calibration, explainability
- `docs/VPS_DEPLOYMENT.md` — how to run this on a VPS
- `docs/PROJECT_STATUS.md` — current phase, done/next, open questions

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest -q
```
