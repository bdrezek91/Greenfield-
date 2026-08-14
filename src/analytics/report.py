"""Render an experiment record + metrics as a Markdown report under reports/experiments/."""

from __future__ import annotations

import json
from pathlib import Path

from src.analytics.experiment import DEFAULT_STORE_PATH, ExperimentRecord

DEFAULT_REPORTS_DIR = DEFAULT_STORE_PATH.parent


def render_markdown(record: ExperimentRecord) -> str:
    lines = [
        f"# {record.experiment_id}",
        "",
        f"- Created: {record.created_at}",
        f"- Git commit: `{record.git_commit}`",
        f"- Dataset version: `{record.dataset_version}`",
        f"- Date range: {record.date_range[0]} → {record.date_range[1]}",
        f"- Symbols: {', '.join(record.symbols)}",
        f"- Timeframes: {', '.join(record.timeframes)}",
        f"- Strategy version: {record.strategy_version}",
        "",
        "## Parameters",
        "```json",
        json.dumps(record.parameters, indent=2, sort_keys=True),
        "```",
        "",
        "## Cost assumptions",
        "```json",
        json.dumps(
            {
                "fees": record.fees,
                "slippage": record.slippage,
                "funding": record.funding_assumptions,
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Metrics",
        "```json",
        json.dumps(record.metrics, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


def save_report(record: ExperimentRecord, reports_dir: Path = DEFAULT_REPORTS_DIR) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{record.experiment_id}.md"
    path.write_text(render_markdown(record))
    return path
