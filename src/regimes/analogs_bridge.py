"""Assemble the input frame src.regimes.analogs.find_historical_analogs
requires from an OHLCV frame plus its already-computed feature matrix and
regime labels - find_historical_analogs was fully built and tested but
had zero callers anywhere (found by the same autonomous survey that
seeded Cycle 37's src/regimes/multidomain_bridge.py).

Unlike multidomain_bridge.py, this bridge does NOT pick a regime source
for the caller - find_historical_analogs only needs a `regime` column,
and this project now has two genuinely different, both-valid ways to
produce one (src.regimes.classifier.classify_regimes's single-domain
`trend_regime`, or Cycle 37's classify_multidomain_regimes_from_sources'
richer per-domain labels) - forcing one here would be exactly the kind
of unexplained choice this project's "never guess" principle avoids.
The caller picks and passes a `regime` series already aligned to `df`'s
index.

`data_quality_score` also has no existing project-wide per-bar
convention (src/data/data_quality.py's QualityCheck/PartitionQualityReport
are per-Silver-partition audits, not a per-bar [0, 1] score) - the only
honest, non-fabricated definition available without inventing a new
quality model is binary: 1.0 for a row where every one of `features`'s
own columns is finite (nothing was dropped/NaN for that bar), 0.0
otherwise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def assemble_analog_search_frame(
    df: pd.DataFrame,
    features: pd.DataFrame,
    regime: pd.Series,
) -> pd.DataFrame:
    """Build find_historical_analogs' required schema: `timestamp`,
    `max_source_timestamp` (= `timestamp` - `df` has no separate
    source-lineage timestamp, same reasoning as
    src.features.pipeline.build_feature_matrix's `momentum_flow` extra),
    `close`, `regime`, `data_quality_score`, plus every column of
    `features` (the analog family members `find_historical_analogs`'s
    caller-supplied `AnalogSearchConfig` will reference by name). `df`
    must have `timestamp`/`close`; `features` and `regime` must share
    `df`'s index (e.g. build_feature_matrix's output, and
    classify_regimes's `trend_regime` or Cycle 37's
    classify_multidomain_regimes_from_sources' output, both are).
    """
    required = {"timestamp", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"analog bridge input frame missing columns: {missing}")
    if not features.index.equals(df.index):
        raise ValueError("features must share df's index")
    if not regime.index.equals(df.index):
        raise ValueError("regime must share df's index")

    out = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "max_source_timestamp": df["timestamp"],
            "close": df["close"],
            "regime": regime,
        },
        index=df.index,
    )
    finite = np.isfinite(features.astype(float).to_numpy()).all(axis=1)
    out["data_quality_score"] = finite.astype(float)
    for column in features.columns:
        out[column] = features[column]
    return out.reset_index(drop=True)
