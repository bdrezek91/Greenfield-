from __future__ import annotations

import pytest

from src.research.hypothesis import Hypothesis, make_hypothesis_id


def _kwargs(**overrides):
    base = dict(
        hypothesis_id="HYP-momentum_trend-000001",
        family="momentum_trend",
        rationale="Trend persistence after costs on 4h/1d perpetuals.",
        symbols=("BTCUSDT",),
        timeframes=("4h",),
        parameters={"lookback_bars": 20},
    )
    base.update(overrides)
    return base


def test_hypothesis_requires_rationale() -> None:
    with pytest.raises(ValueError, match="rationale"):
        Hypothesis(**_kwargs(rationale=""))


def test_hypothesis_requires_symbols() -> None:
    with pytest.raises(ValueError, match="symbols"):
        Hypothesis(**_kwargs(symbols=()))


def test_hypothesis_requires_timeframes() -> None:
    with pytest.raises(ValueError, match="timeframes"):
        Hypothesis(**_kwargs(timeframes=()))


def test_valid_hypothesis_constructs() -> None:
    h = Hypothesis(**_kwargs())
    assert h.parent_hypothesis_id is None


def test_content_fingerprint_is_deterministic() -> None:
    h1 = Hypothesis(**_kwargs())
    h2 = Hypothesis(**_kwargs(hypothesis_id="HYP-momentum_trend-000002"))
    assert h1.content_fingerprint() == h2.content_fingerprint()


def test_content_fingerprint_changes_with_parameters() -> None:
    h1 = Hypothesis(**_kwargs())
    h2 = Hypothesis(**_kwargs(parameters={"lookback_bars": 40}))
    assert h1.content_fingerprint() != h2.content_fingerprint()


def test_make_hypothesis_id_format() -> None:
    assert make_hypothesis_id("momentum_trend", 3) == "HYP-momentum_trend-000003"
