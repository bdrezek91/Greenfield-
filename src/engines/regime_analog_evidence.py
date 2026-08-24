"""Research-stage v1: build one REGIME_ANALOG ConfirmationFamily
FamilyEvidence from src.regimes.analogs.find_historical_analogs's own
output (Cycle 38).

Fifth of six ConfirmationFamily evidence producers (see
src/engines/derivatives_evidence.py's module docstring for the full
"one family, one established idea, research-stage v1" rationale).

Unlike derivatives/order-flow (separate direction + confirmation series)
or price-auction (one quantity giving both), this family already has
its own dedicated causal/quality machinery
(`AnalogSearchConfig.minimum_neighbors`/`maximum_distance`/
`minimum_quality_score`, non-overlapping-neighbor selection, and the
`is_meaningful`/`warning` verdict) - reusing that verdict directly rather
than re-deriving a parallel one is the most defensible v1 choice here:

    `is_meaningful=False` -> no evidence at all (`None`), trusting
    find_historical_analogs's own "insufficient similar history" judgment
    rather than second-guessing it.
    Direction/magnitude come from the requested horizon's
    `AnalogDistribution.positive_probability` (already bounded [0, 1] -
    the literal empirical win-rate among the selected historical
    analogs) linearly remapped to [-1, 1], the same well-established
    "historical precedent" idea find_historical_analogs exists to
    compute, not a new one invented here.
    CONFIDENCE scales with `AnalogDistribution.sample_size` relative to
    `confidence_full_sample_size` (more historical precedents behind the
    read = more statistical confidence in it - an uncontroversial,
    mechanical measure, not a trading heuristic).
"""

from __future__ import annotations

from src.engines.contracts import ConfirmationFamily, FamilyEvidence
from src.regimes.analogs import HistoricalAnalogResult


def regime_analog_family_evidence(
    result: HistoricalAnalogResult,
    *,
    horizon_bars: int,
    confidence_full_sample_size: int = 20,
) -> FamilyEvidence | None:
    """Build one FamilyEvidence(family=REGIME_ANALOG) from a
    src.regimes.analogs.find_historical_analogs result, for one of its
    requested `horizon_bars`.

    Returns `None` (not a synthetic zero-quality entry) when
    `result.is_meaningful` is False (find_historical_analogs' own
    verdict that there wasn't enough similar, high-quality history to
    trust) or `horizon_bars` wasn't one of the horizons that search
    actually computed a distribution for.
    """
    if confidence_full_sample_size <= 0:
        raise ValueError("confidence_full_sample_size must be positive")
    if not result.is_meaningful:
        return None
    distribution = result.distributions.get(horizon_bars)
    if distribution is None:
        return None

    score = max(-1.0, min(1.0, 2.0 * (distribution.positive_probability - 0.5)))
    confidence = min(1.0, distribution.sample_size / confidence_full_sample_size)
    rationale = (
        f"{distribution.sample_size} non-overlapping historical analogs in regime "
        f"{result.regime!r}: {distribution.positive_probability:.0%} positive over "
        f"{horizon_bars} bars, mean return {distribution.mean_return:+.4%}"
    )

    return FamilyEvidence(
        family=ConfirmationFamily.REGIME_ANALOG,
        score=score,
        confidence=confidence,
        quality=1.0,
        max_source_timestamp_utc=result.data_cutoff_utc,
        component_ids=("positive_probability", "sample_size"),
        rationale=rationale,
    )
