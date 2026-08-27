"""Execution calibration must be causal, quality-gated, and reproducible."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.execution.calibration import (
    MARKOUT_HORIZONS_SECONDS,
    CalibrationScenario,
    ExecutionCalibrationConfig,
    JoinIssue,
    PaperOrderObservation,
    TopOfBookQuote,
    assumptions_from_calibration,
    calibrate_execution,
    compare_predicted_to_realized,
    compute_markout_calibration,
    join_orders_to_prior_quotes,
)
from src.execution.intent import IntentSide

NOW = datetime(2026, 8, 23, 17, tzinfo=UTC)


def _quote(
    seconds: float,
    *,
    symbol: str = "BTCUSDT",
    venue: str = "bybit",
    bid: float = 99.9,
    ask: float = 100.1,
) -> TopOfBookQuote:
    return TopOfBookQuote(
        symbol=symbol,
        venue=venue,
        timestamp_utc=NOW + timedelta(seconds=seconds),
        source_sequence=max(0, int(seconds * 10)),
        bid_price=bid,
        ask_price=ask,
        bid_quantity=10.0,
        ask_quantity=12.0,
    )


def _quote_at(
    timestamp,
    *,
    symbol: str = "BTCUSDT",
    venue: str = "bybit",
    bid: float = 100.20,
    ask: float = 100.22,
    sequence: int = 0,
) -> TopOfBookQuote:
    return TopOfBookQuote(
        symbol=symbol,
        venue=venue,
        timestamp_utc=timestamp,
        source_sequence=sequence,
        bid_price=bid,
        ask_price=ask,
        bid_quantity=10.0,
        ask_quantity=12.0,
    )


def _order(
    index: int,
    *,
    symbol: str = "BTCUSDT",
    venue: str = "bybit",
    side: IntentSide = IntentSide.BUY,
    rejected: bool = False,
    partial: bool = False,
    decision_offset: float | None = None,
) -> PaperOrderObservation:
    decision = NOW + timedelta(
        seconds=decision_offset if decision_offset is not None else index + 0.5
    )
    submitted = decision + timedelta(milliseconds=50)
    resolved = submitted + timedelta(milliseconds=100 + index * 10)
    return PaperOrderObservation(
        order_id=f"order-{symbol}-{index}",
        symbol=symbol,
        venue=venue,
        side=side,
        requested_quantity=2.0,
        decision_timestamp_utc=decision,
        submitted_at_utc=submitted,
        resolved_at_utc=resolved,
        filled_price=0.0 if rejected else (100.11 + index * 0.001),
        filled_quantity=0.0 if rejected else (1.0 if partial else 2.0),
        rejected=rejected,
        fee_cost_quote=0.0 if rejected else 0.1 + index * 0.001,
        funding_cost_quote=0.0 if rejected else 0.02 + index * 0.0001,
    )


def _joined(count: int = 10) -> tuple:
    quotes = tuple(_quote(index) for index in range(count + 1))
    orders = tuple(
        _order(index, rejected=index == count - 1, partial=index in {1, 3})
        for index in range(count)
    )
    return join_orders_to_prior_quotes(orders, quotes, maximum_quote_age_seconds=1.0)


def test_asof_join_uses_latest_prior_quote_and_never_future_quote() -> None:
    order = _order(0, decision_offset=1.5)
    prior = _quote(1.0, bid=99.0, ask=101.0)
    future = _quote(2.0, bid=98.0, ask=102.0)

    joined = join_orders_to_prior_quotes(
        (order,), (future, prior), maximum_quote_age_seconds=1.0
    )[0]

    assert joined.quote == prior
    assert joined.quote_age_seconds == pytest.approx(0.5)
    assert joined.issue is None


def test_same_timestamp_uses_highest_source_sequence() -> None:
    order = _order(0, decision_offset=1.0)
    first = replace(_quote(1.0, bid=99.0, ask=101.0), source_sequence=10)
    second = replace(_quote(1.0, bid=98.0, ask=102.0), source_sequence=11)

    joined = join_orders_to_prior_quotes(
        (order,), (second, first), maximum_quote_age_seconds=1.0
    )[0]

    assert joined.quote == second


def test_asof_join_marks_missing_and_stale_quotes() -> None:
    before_history = _order(0, decision_offset=-1.0)
    stale = _order(1, decision_offset=10.0)

    joined = join_orders_to_prior_quotes(
        (before_history, stale), (_quote(0.0),), maximum_quote_age_seconds=2.0
    )

    assert joined[0].issue == JoinIssue.MISSING_QUOTE
    assert joined[1].issue == JoinIssue.STALE_QUOTE


def test_calibration_builds_empirical_market_bucket() -> None:
    calibration = calibrate_execution(
        _joined(),
        calibrated_at_utc=NOW + timedelta(seconds=20),
        dataset_fingerprint="paper-dataset-sha256",
        model_version="execution-calibration-v1",
        config=ExecutionCalibrationConfig(
            minimum_filled_samples_per_market=5,
            maximum_join_issue_fraction=0,
        ),
    )

    bucket = calibration.bucket("BTCUSDT", "BYBIT")
    assert bucket.observation_count == 10
    assert bucket.filled_count == 9
    assert bucket.rejected_count == 1
    assert bucket.partial_fill_count == 2
    assert bucket.rejection_probability == pytest.approx(0.1)
    assert bucket.partial_fill_probability == pytest.approx(2 / 9)
    assert bucket.spread_bps_p50 == pytest.approx(20.0)
    assert bucket.slippage_bps_p95 >= bucket.slippage_bps_p50
    assert bucket.latency_seconds_p99 >= bucket.latency_seconds_p95


def test_scenarios_map_to_increasingly_conservative_assumptions() -> None:
    calibration = calibrate_execution(
        _joined(),
        calibrated_at_utc=NOW + timedelta(seconds=20),
        dataset_fingerprint="dataset",
        model_version="v1",
        config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
    )

    base = assumptions_from_calibration(
        calibration,
        symbol="BTCUSDT",
        venue="bybit",
        scenario=CalibrationScenario.BASE,
    )
    adverse = assumptions_from_calibration(
        calibration,
        symbol="BTCUSDT",
        venue="bybit",
        scenario=CalibrationScenario.ADVERSE,
    )
    severe = assumptions_from_calibration(
        calibration,
        symbol="BTCUSDT",
        venue="bybit",
        scenario=CalibrationScenario.SEVERE,
    )

    assert base.spread_bps <= adverse.spread_bps <= severe.spread_bps
    assert base.slippage_bps <= adverse.slippage_bps <= severe.slippage_bps
    assert base.latency_seconds <= adverse.latency_seconds <= severe.latency_seconds
    assert base.minimum_fill_fraction >= adverse.minimum_fill_fraction
    assert base.reject_probability == adverse.reject_probability


def test_future_observation_is_rejected_instead_of_filtered() -> None:
    with pytest.raises(ValueError, match="future observations"):
        calibrate_execution(
            _joined(),
            calibrated_at_utc=NOW,
            dataset_fingerprint="dataset",
            model_version="v1",
            config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
        )


def test_join_quality_sample_count_and_recency_fail_closed() -> None:
    valid = _joined()
    broken = replace(valid[0], quote=None, quote_age_seconds=None, issue=JoinIssue.MISSING_QUOTE)
    with pytest.raises(ValueError, match="quote-join quality failed"):
        calibrate_execution(
            (broken, *valid[1:]),
            calibrated_at_utc=NOW + timedelta(seconds=20),
            dataset_fingerprint="dataset",
            model_version="v1",
            config=ExecutionCalibrationConfig(
                minimum_filled_samples_per_market=5,
                maximum_join_issue_fraction=0.05,
            ),
        )
    with pytest.raises(ValueError, match="insufficient execution samples"):
        calibrate_execution(
            valid,
            calibrated_at_utc=NOW + timedelta(seconds=20),
            dataset_fingerprint="dataset",
            model_version="v1",
            config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=20),
        )
    with pytest.raises(ValueError, match="observations are stale"):
        calibrate_execution(
            valid,
            calibrated_at_utc=NOW + timedelta(days=2),
            dataset_fingerprint="dataset",
            model_version="v1",
            config=ExecutionCalibrationConfig(
                minimum_filled_samples_per_market=5,
                maximum_observation_age_seconds=3600,
            ),
        )


def test_market_buckets_remain_separate() -> None:
    btc = _joined()
    eth_quotes = tuple(
        _quote(index, symbol="ETHUSDT", bid=49.9, ask=50.1) for index in range(11)
    )
    eth_orders = tuple(
        replace(
            _order(index, symbol="ETHUSDT"),
            filled_price=50.11 + index * 0.001,
        )
        for index in range(10)
    )
    eth = join_orders_to_prior_quotes(
        eth_orders, eth_quotes, maximum_quote_age_seconds=1.0
    )

    calibration = calibrate_execution(
        (*btc, *eth),
        calibrated_at_utc=NOW + timedelta(seconds=20),
        dataset_fingerprint="multi-market",
        model_version="v1",
        config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
    )

    assert {item.symbol for item in calibration.buckets} == {"BTCUSDT", "ETHUSDT"}
    assert calibration.bucket("ETHUSDT", "bybit").spread_bps_p50 > (
        calibration.bucket("BTCUSDT", "bybit").spread_bps_p50
    )


def test_invalid_market_data_and_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="locked or crossed"):
        _quote(0, bid=100, ask=100)
    with pytest.raises(ValueError, match="monotonic"):
        replace(_order(0), submitted_at_utc=NOW + timedelta(seconds=10))
    with pytest.raises(ValueError, match="maximum quote age"):
        join_orders_to_prior_quotes((), (), maximum_quote_age_seconds=0)
    duplicate = _quote(0)
    with pytest.raises(ValueError, match="timestamp and sequence"):
        join_orders_to_prior_quotes(
            (_order(0),), (duplicate, duplicate), maximum_quote_age_seconds=1
        )
    with pytest.raises(ValueError, match="order ids must be unique"):
        join_orders_to_prior_quotes(
            (_order(0), _order(0)), (_quote(0),), maximum_quote_age_seconds=1
        )


def test_markout_is_signed_favorable_and_matches_first_quote_at_or_after_horizon() -> None:
    order = _order(0, decision_offset=0.0)
    fill_time = order.resolved_at_utc
    decision_quote = _quote(-1.0)
    horizon_quotes = tuple(
        _quote_at(fill_time + timedelta(seconds=horizon), sequence=index)
        for index, horizon in enumerate(MARKOUT_HORIZONS_SECONDS)
    )
    joined = join_orders_to_prior_quotes(
        (order,), (decision_quote,), maximum_quote_age_seconds=5.0
    )

    calibrations = compute_markout_calibration(joined, horizon_quotes)

    assert len(calibrations) == 1
    calibration = calibrations[0]
    assert calibration.symbol == "BTCUSDT"
    assert calibration.venue == "bybit"
    assert {item.horizon_seconds for item in calibration.horizons} == set(
        MARKOUT_HORIZONS_SECONDS
    )
    expected_bps = (100.21 - order.filled_price) / order.filled_price * 10_000
    for item in calibration.horizons:
        assert item.sample_count == 1
        assert item.markout_bps_mean == pytest.approx(expected_bps)
        assert item.markout_bps_p50 == pytest.approx(expected_bps)
        assert item.adverse_selection_probability == 0.0


def test_markout_omits_horizons_past_available_quote_history() -> None:
    order = _order(0, decision_offset=0.0)
    fill_time = order.resolved_at_utc
    decision_quote = _quote(-1.0)
    # Only quotes through +2s exist - horizons beyond that must be omitted
    # from the report, never fabricated from the nearest available quote.
    horizon_quotes = tuple(
        _quote_at(fill_time + timedelta(seconds=horizon), sequence=index)
        for index, horizon in enumerate((0.1, 0.25, 0.5, 1.0, 2.0))
    )
    joined = join_orders_to_prior_quotes(
        (order,), (decision_quote,), maximum_quote_age_seconds=5.0
    )

    calibration = compute_markout_calibration(joined, horizon_quotes)[0]

    reported = {item.horizon_seconds for item in calibration.horizons}
    assert reported == {0.1, 0.25, 0.5, 1.0, 2.0}
    assert 5.0 not in reported
    assert 60.0 not in reported


def test_markout_adverse_selection_probability_mixes_favorable_and_unfavorable() -> None:
    base = _order(0, decision_offset=0.0)
    favorable = replace(base, filled_price=100.00)
    unfavorable = replace(
        base,
        order_id="order-BTCUSDT-unfavorable",
        filled_price=100.20,
    )
    decision_quote = _quote(-1.0)
    horizon = 1.0
    quote_time = base.resolved_at_utc + timedelta(seconds=horizon)
    # A mid (100.10) between the two fill prices: favorable (bought at
    # 100.00) sees the market rise afterward - a positive markout - while
    # unfavorable (bought at 100.20) sees it against them - negative.
    reference_quote = _quote_at(quote_time, bid=100.09, ask=100.11, sequence=0)

    joined = join_orders_to_prior_quotes(
        (favorable, unfavorable), (decision_quote,), maximum_quote_age_seconds=5.0
    )

    calibration = compute_markout_calibration(
        joined, (reference_quote,), horizons_seconds=(horizon,)
    )[0]

    assert calibration.horizon(horizon).sample_count == 2
    assert calibration.horizon(horizon).adverse_selection_probability == pytest.approx(0.5)


def test_compare_predicted_to_realized_reports_deltas() -> None:
    predicted = calibrate_execution(
        _joined(),
        calibrated_at_utc=NOW + timedelta(seconds=20),
        dataset_fingerprint="train-dataset",
        model_version="v1",
        config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
    )

    # A fresh, later, disjoint sample with a wider realized spread than the
    # training-period calibration predicted, and no rejections (a better
    # realized fill probability than predicted).
    later_quotes = tuple(_quote(100 + index, bid=99.8, ask=100.2) for index in range(11))
    later_orders = tuple(_order(index, decision_offset=100 + index + 0.5) for index in range(10))
    realized = join_orders_to_prior_quotes(
        later_orders, later_quotes, maximum_quote_age_seconds=1.0
    )

    comparison = compare_predicted_to_realized(
        predicted,
        realized,
        symbol="BTCUSDT",
        venue="bybit",
        config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
    )

    assert comparison.realized_sample_count == 10
    assert comparison.predicted_spread_bps_p50 == pytest.approx(20.0)
    assert comparison.realized_spread_bps_p50 == pytest.approx(40.0)
    assert comparison.spread_bps_error == pytest.approx(20.0)
    assert comparison.predicted_fill_probability == pytest.approx(0.9)
    assert comparison.realized_fill_probability == pytest.approx(1.0)
    assert comparison.fill_probability_error == pytest.approx(
        comparison.realized_fill_probability - comparison.predicted_fill_probability
    )


def test_compare_predicted_to_realized_fails_closed_on_insufficient_or_missing_samples() -> None:
    predicted = calibrate_execution(
        _joined(),
        calibrated_at_utc=NOW + timedelta(seconds=20),
        dataset_fingerprint="train-dataset",
        model_version="v1",
        config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
    )
    sparse = join_orders_to_prior_quotes(
        (_order(0, decision_offset=100.5),), (_quote(100.0),), maximum_quote_age_seconds=1.0
    )

    with pytest.raises(ValueError, match="insufficient realized"):
        compare_predicted_to_realized(
            predicted,
            sparse,
            symbol="BTCUSDT",
            venue="bybit",
            config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=5),
        )
    other_market = join_orders_to_prior_quotes(
        (_order(0, symbol="ETHUSDT", decision_offset=100.5),),
        (_quote(100.0, symbol="ETHUSDT"),),
        maximum_quote_age_seconds=1.0,
    )
    with pytest.raises(ValueError, match="no realized observations"):
        compare_predicted_to_realized(
            predicted,
            other_market,
            symbol="BTCUSDT",
            venue="bybit",
            config=ExecutionCalibrationConfig(minimum_filled_samples_per_market=1),
        )
