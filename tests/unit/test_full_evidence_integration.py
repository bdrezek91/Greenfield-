"""All six ConfirmationFamily evidence producers (Cycles 42-47), each
built from its own real source function, feeding one
evaluate_directional_setup call together with realistic DEFAULT
thresholds (DirectionalEngineConfig() - minimum_confirming_families=3,
family_vote_threshold=0.25) for the first time - the capstone of the
research-stage v1 evidence layer this project's src/engines/ needed to
become reachable at all.

`maximum_data_age_seconds` is the one config value relaxed here (the
default's own staleness gate is already covered by
tests/unit/test_directional_engine.py and exercised realistically in
tests/unit/test_evidence_integration.py's two-family test) - each
family's synthetic fixture below uses its own natural granularity
(hourly derivatives bars, minute trade buckets, option quotes,
historical-analog queries), so their real timestamps land within
minutes of each other, not the same instant a live system would produce.
Widening the staleness window here isolates what this test actually
checks: do six independently-built pieces of real evidence combine
correctly under the engine's real voting/threshold defaults.
"""

from __future__ import annotations

from datetime import UTC, timedelta

import numpy as np
import pandas as pd

from src.data.instruments import ProductType, VenueInstrument
from src.engines.contracts import (
    DataQualityStatus,
    EngineGateState,
    LegSide,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupLeg,
)
from src.engines.cross_market_evidence import cross_market_family_evidence
from src.engines.derivatives_evidence import derivatives_family_evidence
from src.engines.directional import (
    DirectionalEngineConfig,
    DirectionalSetupRequest,
    evaluate_directional_setup,
)
from src.engines.order_flow_evidence import order_flow_family_evidence
from src.engines.price_auction_evidence import price_auction_family_evidence
from src.engines.regime_analog_evidence import regime_analog_family_evidence
from src.engines.volatility_options_evidence import volatility_options_family_evidence
from src.features.cross_market import cross_market_context_frame
from src.features.derivatives import derivatives_context_frame
from src.features.options import OptionQuote, build_option_surface_snapshot
from src.features.pipeline import build_feature_matrix
from src.regimes.analogs import AnalogFamily, AnalogSearchConfig, find_historical_analogs
from src.regimes.analogs_bridge import assemble_analog_search_frame
from src.regimes.classifier import RegimeConfig, classify_regimes

_AS_OF = pd.Timestamp("2024-01-02T00:00:00Z")
_SMALL_REGIME_CONFIG = RegimeConfig(
    short_ma_period=3, long_ma_period=5, adx_period=3, vol_period=3, vol_lookback=5, atr_period=3
)


def _derivatives_evidence():
    ts = pd.date_range(end=_AS_OF, periods=25, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    mark_price = 100.0 + rng.normal(0, 0.05, size=25)
    oi = 1_000.0 + rng.normal(0, 1.0, size=25)
    mark_price[-1] = mark_price[-2] * 1.05
    oi[-1] = oi[-2] * 1.05
    raw = pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "mark_price": mark_price,
            "index_price": mark_price,
            "open_interest": oi,
            "funding_rate": 0.0001,
        }
    )
    return derivatives_family_evidence(derivatives_context_frame(raw, rolling_window=10))


def _order_flow_evidence():
    ts = pd.date_range(end=_AS_OF, periods=25, freq="1min", tz="UTC")
    rng = np.random.default_rng(1)
    vwap = 100.0 + rng.normal(0, 0.05, size=25)
    delta = rng.normal(0, 1.0, size=25)
    vwap[-1] = vwap[-2] * 1.05
    delta[-1] = abs(delta[-2])
    trade_flow = pd.DataFrame(
        {"timestamp": ts, "max_source_timestamp": ts, "trade_vwap": vwap, "trade_delta": delta}
    )
    return order_flow_family_evidence(trade_flow)


def _cross_market_evidence():
    ts = pd.date_range(end=_AS_OF, periods=30, freq="1h", tz="UTC")
    rng = np.random.default_rng(2)
    base_moves = rng.normal(0, 0.3, size=30)
    prices = {
        "BTC": 100 + np.cumsum(base_moves + rng.normal(0, 0.05, size=30)),
        "ETH": 50 + np.cumsum(base_moves + rng.normal(0, 0.05, size=30)),
        "SOL": 20 + np.cumsum(base_moves + rng.normal(0, 0.05, size=30)),
    }
    for asset in prices:
        prices[asset][-1] = prices[asset][-2] + (3.0 if asset == "BTC" else -1.0)
    rows = []
    for index, timestamp in enumerate(ts):
        for asset, series in prices.items():
            spot = float(series[index])
            rows.append(
                {
                    "timestamp": timestamp,
                    "max_source_timestamp": timestamp,
                    "asset": asset,
                    "spot_price": spot,
                    "perpetual_price": spot * 1.0005,
                }
            )
    panel = cross_market_context_frame(pd.DataFrame(rows), rolling_window=5)
    btc_only = panel[panel["asset"] == "BTC"].drop(columns="asset").reset_index(drop=True)
    return cross_market_family_evidence(btc_only)


def _price_auction_evidence():
    context = pd.DataFrame(
        {"timestamp": [_AS_OF], "poc": [100.0], "vah": [101.0], "val": [99.0], "close": [104.0]}
    )
    return price_auction_family_evidence(context)


def _regime_analog_evidence():
    ts = pd.date_range(end=_AS_OF, periods=120, freq="1h", tz="UTC")
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0.02, 0.6, size=120))
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0 + rng.normal(0, 10, size=120).cumsum().clip(min=0),
        }
    )
    features = build_feature_matrix(df)[["return_1", "momentum"]]
    regime = classify_regimes(df, _SMALL_REGIME_CONFIG)["trend_regime"]
    assembled = assemble_analog_search_frame(df, features, regime)
    warm = assembled.iloc[10:].reset_index(drop=True)
    config = AnalogSearchConfig(
        families=(AnalogFamily("price", ("return_1", "momentum")),),
        horizons_bars=(1,),
        neighbor_count=5,
        minimum_neighbors=2,
        maximum_distance=10.0,
        minimum_quality_score=0.5,
        require_same_regime=False,
    )
    result = find_historical_analogs(
        warm,
        query_timestamp=warm["timestamp"].iloc[-1],
        config=config,
        dataset_version="test-dataset",
        code_version="test-code",
    )
    if not result.is_meaningful:
        return None
    return regime_analog_family_evidence(result, horizon_bars=1)


def _volatility_options_evidence():
    def quote(*, strike: float, right: str, mark_iv: float, delta: float) -> OptionQuote:
        expiry = _AS_OF.to_pydatetime() + timedelta(days=30)
        instrument = VenueInstrument(
            exchange="deribit",
            market_type="option",
            venue_symbol=f"BTC-{expiry:%d%b%y}-{strike:g}-{right[0].upper()}",
            base_asset="BTC",
            quote_asset="USD",
            product_type=ProductType.OPTION,
            settlement_asset="BTC",
            expiry_utc=expiry.replace(tzinfo=UTC),
            option_strike=f"{strike:g}",
            option_right=right,
        )
        received = _AS_OF.to_pydatetime().replace(tzinfo=UTC) - timedelta(seconds=1)
        return OptionQuote(
            instrument=instrument,
            event_at_utc=received - timedelta(milliseconds=25),
            received_at_utc=received,
            underlying_price=100.0,
            mark_iv=mark_iv,
            bid_iv=mark_iv - 1.0,
            ask_iv=mark_iv + 1.0,
            open_interest=10.0,
            delta=delta,
        )

    quotes = [
        quote(strike=90, right="call", mark_iv=62, delta=0.75),
        quote(strike=90, right="put", mark_iv=60, delta=-0.25),
        quote(strike=100, right="call", mark_iv=50, delta=0.50),
        quote(strike=100, right="put", mark_iv=52, delta=-0.50),
        # Bullish skew: 25-delta calls pricier than 25-delta puts.
        quote(strike=110, right="call", mark_iv=63, delta=0.25),
        quote(strike=110, right="put", mark_iv=55, delta=-0.75),
    ]
    as_of = _AS_OF.to_pydatetime().replace(tzinfo=UTC)
    snapshot = build_option_surface_snapshot(quotes, as_of_utc=as_of)
    return volatility_options_family_evidence(snapshot)


def _gates() -> EngineGateState:
    return EngineGateState(
        kill_switch_active=False,
        operational_healthy=True,
        promotion_eligible=True,
        promotion_state="RESEARCH",
        risk_approved=True,
        risk_reason="approved",
    )


def test_all_six_families_combine_under_realistic_default_thresholds() -> None:
    evidence = (
        _derivatives_evidence(),
        _order_flow_evidence(),
        _cross_market_evidence(),
        _price_auction_evidence(),
        _regime_analog_evidence(),
        _volatility_options_evidence(),
    )
    assert all(item is not None for item in evidence), evidence
    latest_source = max(item.max_source_timestamp_utc for item in evidence)
    decision_time = latest_source + timedelta(seconds=1)

    request = DirectionalSetupRequest(
        target=MarketTarget("BTCUSDT", ("bybit",)),
        decision_timestamp_utc=decision_time,
        data_cutoff_utc=decision_time,
        horizon="1h-4h",
        evidence=evidence,
        regimes=(("trend", "UPTREND"),),
        entry_condition="limit inside validated entry zone",
        invalidation="a majority of families reverse",
        stop_logic="hard stop below invalidation",
        expected_gross_value_bps=NumericRange(20, 35, 55),
        expected_cost_bps=NumericRange(2, 4, 8),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="six-family-evidence-v1",
        feature_version="gold-v1",
        gates=_gates(),
    )
    # Only maximum_data_age_seconds is widened - see this module's own
    # docstring for why. minimum_confirming_families/family_vote_threshold
    # are the engine's real defaults.
    config = DirectionalEngineConfig(maximum_data_age_seconds=10_000_000.0)

    decision = evaluate_directional_setup(request, config)

    assert decision.action == SetupAction.LONG
    assert decision.legs == (SetupLeg("BTCUSDT", "bybit", LegSide.BUY),)
    assert len(decision.evidence) == 6
