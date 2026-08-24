"""Lineage-aware point-in-time joins shared by feature and regime pipelines."""

from __future__ import annotations

import pandas as pd


class PointInTimeJoinError(ValueError):
    """Raised when source lineage cannot prove causal availability."""


def point_in_time_asof(
    timestamps: pd.Series,
    source: pd.DataFrame,
    value_col: str,
) -> pd.Series:
    """Return the latest event observable at each requested timestamp.

    A row is eligible only after both its event ``timestamp`` and its
    ``max_source_timestamp`` have passed.  When an older event arrives late it
    never replaces a newer event that was already observable.  Sources without
    explicit lineage retain the legacy contract where availability equals the
    event timestamp.
    """
    missing = {"timestamp", value_col} - set(source.columns)
    if missing:
        raise PointInTimeJoinError(f"point-in-time source missing columns: {sorted(missing)}")

    decisions = pd.to_datetime(timestamps, utc=True, errors="coerce")
    if decisions.isna().any():
        raise PointInTimeJoinError("decision timestamps must be valid")

    columns = ["timestamp", value_col]
    has_lineage = "max_source_timestamp" in source.columns
    if has_lineage:
        columns.insert(1, "max_source_timestamp")
    right = source.loc[:, columns].copy()
    right["timestamp"] = pd.to_datetime(right["timestamp"], utc=True, errors="coerce")
    if has_lineage:
        right["max_source_timestamp"] = pd.to_datetime(
            right["max_source_timestamp"], utc=True, errors="coerce"
        )
    else:
        right["max_source_timestamp"] = right["timestamp"]

    if right[["timestamp", "max_source_timestamp"]].isna().any().any():
        raise PointInTimeJoinError("source timestamps and lineage must be valid")
    if right["timestamp"].duplicated().any():
        raise PointInTimeJoinError("source event timestamps must be unique")

    right["available_at"] = right[["timestamp", "max_source_timestamp"]].max(axis=1)
    arrivals = right.sort_values(
        ["available_at", "timestamp"], kind="mergesort"
    ).reset_index(drop=True)

    # Build only the state transitions where the latest observable event
    # advances.  A delayed older event is retained in the source dataset but
    # cannot roll the point-in-time state backward when it finally arrives.
    state_rows: list[dict[str, object]] = []
    latest_event: pd.Timestamp | None = None
    for event_at, available_at, value in arrivals[
        ["timestamp", "available_at", value_col]
    ].itertuples(index=False, name=None):
        if latest_event is None or event_at > latest_event:
            latest_event = event_at
            state_rows.append({"available_at": available_at, value_col: value})

    left = pd.DataFrame(
        {"decision_at": decisions, "_original_position": range(len(decisions))}
    ).sort_values("decision_at", kind="mergesort")
    if state_rows:
        states = pd.DataFrame(state_rows).sort_values("available_at", kind="mergesort")
        merged = pd.merge_asof(
            left,
            states,
            left_on="decision_at",
            right_on="available_at",
            direction="backward",
        )
    else:
        merged = left.copy()
        merged[value_col] = pd.NA
    ordered = merged.sort_values("_original_position", kind="mergesort")[value_col]
    return pd.Series(ordered.to_numpy(), index=timestamps.index, name=value_col)
