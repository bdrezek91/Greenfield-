"""Assemble the individual feature modules into one feature matrix.

The single entry point ML code (Phase 12) and research notebooks are meant
to use - keeps feature-set changes to one place rather than scattered
across callers, and gives every feature a stable, documented column name.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.features import price, structure, volatility, volume
from src.features.divergence import price_cvd_divergence_frame
from src.features.momentum_flow import momentum_money_flow_frame
from src.features.point_in_time import point_in_time_asof


@dataclass(frozen=True)
class FeatureConfig:
    momentum_lookback: int = 10
    high_low_lookback: int = 20
    trend_slope_lookback: int = 20
    atr_period: int = 14
    realized_vol_period: int = 20
    range_percentile_lookback: int = 100
    relative_volume_lookback: int = 20
    volume_trend_lookback: int = 10
    structure_lookback: int = 10
    # src.features.momentum_flow.momentum_money_flow_frame's own tunable
    # windows - defaults match that function's defaults exactly.
    momentum_flow_channel_span: int = 10
    momentum_flow_momentum_span: int = 21
    momentum_flow_signal_window: int = 4
    momentum_flow_money_flow_window: int = 14
    momentum_flow_rsi_window: int = 14
    momentum_flow_pivot_left: int = 2
    momentum_flow_pivot_right: int = 2
    # src.features.divergence.price_cvd_divergence_frame's own tunable
    # pivot-confirmation windows - defaults match that function's exactly.
    cvd_divergence_left_bars: int = 2
    cvd_divergence_right_bars: int = 2


def build_feature_matrix(
    df: pd.DataFrame,
    config: FeatureConfig | None = None,
    *,
    funding: pd.DataFrame | None = None,
    open_interest: pd.DataFrame | None = None,
    trade_flow: pd.DataFrame | None = None,
    l2_imbalance: pd.DataFrame | None = None,
    volume_profile: pd.DataFrame | None = None,
    vwap: pd.DataFrame | None = None,
    momentum_flow: bool = False,
    derivatives_context: pd.DataFrame | None = None,
    cross_market_context: pd.DataFrame | None = None,
    book_liquidity_change: pd.DataFrame | None = None,
    trade_interaction: pd.DataFrame | None = None,
    cvd_divergence: bool = False,
    cross_venue_context: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return a new DataFrame of point-in-time features indexed the same as
    `df` (expects columns: timestamp, open, high, low, close, volume).
    Rows without enough trailing history are NaN, never a guessed value -
    callers (e.g. a training pipeline) are responsible for dropping or
    otherwise handling NaN rows explicitly.

    `funding`/`open_interest`/`trade_flow`/`l2_imbalance`/`volume_profile`/
    `vwap`/`momentum_flow` are all optional and independent (default None
    or False -> output is exactly FEATURE_COLUMNS, unchanged from before
    any of them existed - existing callers/saved models are unaffected
    regardless of which extras a caller adds later).

    `momentum_flow`: unlike every other extra above, this is a bool, not a
    pre-computed frame - src.features.momentum_flow.momentum_money_flow_frame
    (the independent, original Market-Cipher-like momentum/money-flow/
    divergence family - no proprietary code) needs only `df` itself
    (high/low/close/volume), so it is computed here directly rather than
    requiring the caller to build and pass a frame first. `df` has no
    separate source-lineage timestamp the way normalized Silver rows do,
    so `max_source_timestamp` is set equal to each bar's own `timestamp`
    - klines ARE the source here, not a fabricated value. Tunable via
    `config`'s `momentum_flow_*` fields. See MOMENTUM_FLOW_FEATURE_COLUMNS.

    `funding`/`open_interest`: frames from src/data/storage.py's
    read_funding/read_open_interest (columns timestamp+funding_rate /
    timestamp+open_interest) - see EXTENDED_FEATURE_COLUMNS.

    `trade_flow`/`l2_imbalance`: frames from
    src.features.order_flow.trade_flow_frame/l2_imbalance_frame (built
    from normalized Silver trade/order-book rows, NOT computed here - this
    function only as-of joins pre-computed frames onto `df`'s bar
    timestamps, matching how funding/open_interest are handled) - see
    TRADE_FLOW_FEATURE_COLUMNS/L2_IMBALANCE_FEATURE_COLUMNS. Each is its
    own independent extra (a caller may have trade data without L2 data,
    or vice versa), unlike funding/open_interest, which this module has
    always treated as an all-or-nothing pair.

    `volume_profile`/`vwap`: frames from
    src.features.auction.rolling_volume_profile_frame/anchored_vwap_frame
    (columns timestamp+poc+vah+val / timestamp+vwap). Raw price levels
    are not stationary/comparable across assets or price regimes, so
    (unlike funding_rate/cvd/book_imbalance, which are joined as-is) these
    are converted to `df["close"]`-relative, scale-invariant features
    before being added - see VOLUME_PROFILE_FEATURE_COLUMNS/
    VWAP_FEATURE_COLUMNS.

    `derivatives_context`: a frame from
    src.features.derivatives.derivatives_context_frame (built by the
    caller from its own point-in-time-aligned mark_price/index_price/
    open_interest/funding_rate[/long_short_ratio/liquidation volumes] -
    NOT computed here, matching trade_flow/l2_imbalance). Only the
    already-normalized/derived columns are joined (funding_zscore,
    basis_zscore, derivatives_crowding_score, oi_price_confirmation,
    liquidation_imbalance) - the frame's raw mark_return/oi_change/
    basis_bps/funding_rate/funding_annualized_pct are skipped as
    redundant with (or a less ML-ready version of) what open_interest/
    funding already provide above. See DERIVATIVES_CONTEXT_FEATURE_COLUMNS.

    `cross_market_context`: a frame from
    src.features.cross_market.cross_market_context_frame, which is
    LONG-format (one row per timestamp+asset, multiple assets) - unlike
    every other extra, the caller must pre-filter it down to just the
    asset `df` itself represents before passing it in (this function has
    no `symbol` parameter and never guesses which asset's row is
    relevant). `spot_return`/`benchmark_return` are skipped as redundant
    with `return_1` (computed from `df` directly, above). See
    CROSS_MARKET_FEATURE_COLUMNS.

    `book_liquidity_change`/`trade_interaction`: frames from
    src.features.interaction.book_liquidity_change_frame/
    trade_interaction_frame (built from normalized Silver order-book/trade
    rows, NOT computed here - same shape as trade_flow/l2_imbalance
    above). Independent of each other and of every other extra. Joined
    as-is (raw volumes/flags/scores, not further transformed) - see
    BOOK_LIQUIDITY_CHANGE_FEATURE_COLUMNS/TRADE_INTERACTION_FEATURE_COLUMNS.

    `cvd_divergence`: unlike every other extra, this bool does not stand
    on its own - src.features.divergence.price_cvd_divergence_frame is
    computed FROM the same raw `trade_flow` frame already required for
    the `trade_flow` extra above (it needs `trade_flow`'s own
    `trade_vwap`/`cvd` columns as its price/oscillator series), so passing
    `cvd_divergence=True` without also passing `trade_flow` raises
    ValueError rather than silently producing nothing. Tunable via
    `config`'s `cvd_divergence_left_bars`/`cvd_divergence_right_bars`. See
    CVD_DIVERGENCE_FEATURE_COLUMNS.

    `cross_venue_context`: a frame from
    src.features.cross_venue.cross_venue_series_frame (itself a new,
    Cycle-35 walk-forward wrapper around cross_venue_snapshot, which is a
    POINT-in-time, one-row-per-venue function incompatible with a direct
    as-of join - see cross_venue_series_frame's own docstring). The
    caller builds this frame (it needs the venue-identifying
    `canonical_instrument_id` cross_venue_snapshot requires, which this
    function has no parameter for and never guesses - same reasoning as
    `cross_market_context`'s per-asset pre-filtering requirement).
    `cross_venue_median_price` is a raw price level, so - like
    volume_profile/vwap above - it is converted to a `df["close"]`-relative
    `cross_venue_median_distance` rather than joined as-is; the rest of
    the frame's columns are already scale-invariant counts/bps and are
    joined directly. See CROSS_VENUE_CONTEXT_FEATURE_COLUMNS.

    Every extra is as-of joined to the most recent reading at or before
    each bar - never a future one.
    """
    config = config or FeatureConfig()
    out = pd.DataFrame(index=df.index)
    if "timestamp" in df.columns:
        out["timestamp"] = df["timestamp"]

    out["return_1"] = price.returns(df, periods=1)
    out["momentum"] = price.momentum(df, config.momentum_lookback)
    out["distance_from_high"] = price.distance_from_high(df, config.high_low_lookback)
    out["distance_from_low"] = price.distance_from_low(df, config.high_low_lookback)
    out["trend_slope"] = price.trend_slope(df, config.trend_slope_lookback)

    out["atr"] = volatility.atr(df, config.atr_period)
    out["realized_vol"] = volatility.realized_volatility(df, config.realized_vol_period)
    out["range_percentile"] = volatility.range_percentile(
        df, config.atr_period, config.range_percentile_lookback
    )

    out["relative_volume"] = volume.relative_volume(df, config.relative_volume_lookback)
    out["volume_trend"] = volume.volume_trend(df, config.volume_trend_lookback)

    out["higher_high"] = structure.higher_high(df, config.structure_lookback)
    out["lower_low"] = structure.lower_low(df, config.structure_lookback)
    out["breakout"] = structure.breakout_flag(df, config.structure_lookback)
    out["breakdown"] = structure.breakdown_flag(df, config.structure_lookback)

    if funding is not None:
        out["funding_rate"] = _as_of_join(df["timestamp"], funding, "funding_rate")
    if open_interest is not None:
        oi = _as_of_join(df["timestamp"], open_interest, "open_interest")
        out["oi_change"] = oi.pct_change()
    if trade_flow is not None:
        out["cvd"] = _as_of_join(df["timestamp"], trade_flow, "cvd")
        out["trade_delta"] = _as_of_join(df["timestamp"], trade_flow, "trade_delta")
    if l2_imbalance is not None:
        out["book_imbalance"] = _as_of_join(df["timestamp"], l2_imbalance, "book_imbalance")
        out["spread"] = _as_of_join(df["timestamp"], l2_imbalance, "spread")
    if volume_profile is not None:
        poc = _as_of_join(df["timestamp"], volume_profile, "poc")
        vah = _as_of_join(df["timestamp"], volume_profile, "vah")
        val = _as_of_join(df["timestamp"], volume_profile, "val")
        out["poc_distance"] = (df["close"] - poc) / df["close"]
        out["value_area_width"] = (vah - val) / df["close"]
        out["in_value_area"] = ((df["close"] >= val) & (df["close"] <= vah)).astype(float)
        # A NaN poc/vah/val (bar before the profile's own trailing window
        # is full) must produce a NaN in_value_area, not a False comparison
        # result - pandas' comparison ops already return False for NaN
        # operands, so mask it back to NaN explicitly.
        out.loc[poc.isna(), "in_value_area"] = float("nan")
    if vwap is not None:
        vwap_value = _as_of_join(df["timestamp"], vwap, "vwap")
        out["vwap_distance"] = (df["close"] - vwap_value) / df["close"]
    if momentum_flow:
        momentum_input = pd.DataFrame(
            {
                "timestamp": df["timestamp"],
                "max_source_timestamp": df["timestamp"],
                "high": df["high"],
                "low": df["low"],
                "close": df["close"],
                "volume": df["volume"],
            }
        )
        momentum_result = momentum_money_flow_frame(
            momentum_input,
            channel_span=config.momentum_flow_channel_span,
            momentum_span=config.momentum_flow_momentum_span,
            signal_window=config.momentum_flow_signal_window,
            money_flow_window=config.momentum_flow_money_flow_window,
            rsi_window=config.momentum_flow_rsi_window,
            pivot_left=config.momentum_flow_pivot_left,
            pivot_right=config.momentum_flow_pivot_right,
        ).set_index("timestamp")
        for column in MOMENTUM_FLOW_FEATURE_COLUMNS:
            if column in momentum_result.columns:
                out[column] = df["timestamp"].map(momentum_result[column])
            else:
                # momentum_money_flow_frame drops the divergence columns
                # entirely (not present-but-zero) when no confirmed pivot
                # exists anywhere in the input - matches its own "no
                # divergence found" convention (0, not NaN) here too.
                out[column] = 0
    if derivatives_context is not None:
        for column in DERIVATIVES_CONTEXT_FEATURE_COLUMNS:
            out[column] = _as_of_join(df["timestamp"], derivatives_context, column)
    if cross_market_context is not None:
        for column in CROSS_MARKET_FEATURE_COLUMNS:
            out[column] = _as_of_join(df["timestamp"], cross_market_context, column)
    if book_liquidity_change is not None:
        for column in BOOK_LIQUIDITY_CHANGE_FEATURE_COLUMNS:
            out[column] = _as_of_join(df["timestamp"], book_liquidity_change, column)
    if trade_interaction is not None:
        for column in TRADE_INTERACTION_FEATURE_COLUMNS:
            out[column] = _as_of_join(df["timestamp"], trade_interaction, column)
    if cvd_divergence:
        if trade_flow is None:
            raise ValueError("cvd_divergence=True requires trade_flow to also be passed")
        divergence_frame = price_cvd_divergence_frame(
            trade_flow,
            left_bars=config.cvd_divergence_left_bars,
            right_bars=config.cvd_divergence_right_bars,
        )
        for column in CVD_DIVERGENCE_FEATURE_COLUMNS:
            out[column] = _as_of_join(df["timestamp"], divergence_frame, column)
    if cross_venue_context is not None:
        out["cross_venue_count"] = _as_of_join(
            df["timestamp"], cross_venue_context, "cross_venue_count"
        )
        out["cross_venue_max_abs_deviation_bps"] = _as_of_join(
            df["timestamp"], cross_venue_context, "cross_venue_max_abs_deviation_bps"
        )
        out["cross_venue_outlier_count"] = _as_of_join(
            df["timestamp"], cross_venue_context, "cross_venue_outlier_count"
        )
        median_price = _as_of_join(
            df["timestamp"], cross_venue_context, "cross_venue_median_price"
        )
        out["cross_venue_median_distance"] = (df["close"] - median_price) / df["close"]

    return out


def _as_of_join(timestamps: pd.Series, source: pd.DataFrame, value_col: str) -> pd.Series:
    return point_in_time_asof(timestamps, source, value_col)


FEATURE_COLUMNS: tuple[str, ...] = (
    "return_1",
    "momentum",
    "distance_from_high",
    "distance_from_low",
    "trend_slope",
    "atr",
    "realized_vol",
    "range_percentile",
    "relative_volume",
    "volume_trend",
    "higher_high",
    "lower_low",
    "breakout",
    "breakdown",
)

# FEATURE_COLUMNS plus the optional funding/open-interest features - only
# present in build_feature_matrix()'s output when `funding`/`open_interest`
# are passed in. A caller opting into these must pass both `funding` and
# `open_interest` and use this tuple (not FEATURE_COLUMNS) as the model's
# feature schema.
EXTENDED_FEATURE_COLUMNS: tuple[str, ...] = FEATURE_COLUMNS + ("funding_rate", "oi_change")

# Present only when `trade_flow`/`l2_imbalance` (src.features.order_flow's
# trade_flow_frame/l2_imbalance_frame) are passed in - each independent of
# the other and of EXTENDED_FEATURE_COLUMNS's funding/OI pair. A caller
# combines whichever tuples match the extras it actually passed, e.g.
# `FEATURE_COLUMNS + TRADE_FLOW_FEATURE_COLUMNS` for trade flow alone.
TRADE_FLOW_FEATURE_COLUMNS: tuple[str, ...] = ("cvd", "trade_delta")
L2_IMBALANCE_FEATURE_COLUMNS: tuple[str, ...] = ("book_imbalance", "spread")

# Present only when `volume_profile`/`vwap` (src.features.auction's
# rolling_volume_profile_frame/anchored_vwap_frame) are passed in - each
# independent of every other extra above.
VOLUME_PROFILE_FEATURE_COLUMNS: tuple[str, ...] = (
    "poc_distance",
    "value_area_width",
    "in_value_area",
)
VWAP_FEATURE_COLUMNS: tuple[str, ...] = ("vwap_distance",)

# Present only when `momentum_flow=True` - src.features.momentum_flow's
# independent Market-Cipher-like momentum/money-flow family plus its
# built-in divergence-vs-own-price evidence.
MOMENTUM_FLOW_FEATURE_COLUMNS: tuple[str, ...] = (
    "momentum_wave",
    "momentum_signal",
    "momentum_histogram",
    "money_flow",
    "rsi",
    "regular_bullish_divergence",
    "hidden_bullish_divergence",
    "regular_bearish_divergence",
    "hidden_bearish_divergence",
    "confirmed_pivot_low",
    "confirmed_pivot_high",
    "pivot_age_bars",
)

# Present only when `derivatives_context` (src.features.derivatives's
# derivatives_context_frame) is passed in - only the already-normalized/
# derived subset of that frame's columns (see build_feature_matrix's
# docstring for why the raw ones are skipped).
DERIVATIVES_CONTEXT_FEATURE_COLUMNS: tuple[str, ...] = (
    "funding_zscore",
    "basis_zscore",
    "derivatives_crowding_score",
    "oi_price_confirmation",
    "liquidation_imbalance",
)

# Present only when `cross_market_context` (src.features.cross_market's
# cross_market_context_frame, pre-filtered by the caller to df's own
# asset) is passed in - skips spot_return/benchmark_return as redundant
# with return_1 above (see build_feature_matrix's docstring).
CROSS_MARKET_FEATURE_COLUMNS: tuple[str, ...] = (
    "spot_perpetual_basis_bps",
    "relative_strength_log_return",
    "cross_sectional_return_rank",
    "market_breadth_positive_fraction",
    "cross_asset_return_dispersion",
    "benchmark_rolling_correlation",
    "benchmark_lead_correlation",
)

# Present only when `book_liquidity_change`/`trade_interaction`
# (src.features.interaction's book_liquidity_change_frame/
# trade_interaction_frame) are passed in - each independent of the other
# and of every extra above.
BOOK_LIQUIDITY_CHANGE_FEATURE_COLUMNS: tuple[str, ...] = (
    "bid_added",
    "ask_added",
    "bid_cancelled",
    "ask_cancelled",
    "bid_replenished",
    "ask_replenished",
)
TRADE_INTERACTION_FEATURE_COLUMNS: tuple[str, ...] = (
    "buy_sweep",
    "sell_sweep",
    "buy_sweep_levels",
    "sell_sweep_levels",
    "buy_absorption",
    "sell_absorption",
    "buy_absorption_score",
    "sell_absorption_score",
    "buy_exhaustion",
    "sell_exhaustion",
    "price_progress_ticks",
)

# Present only when `cvd_divergence=True` (which also requires
# `trade_flow`) - src.features.divergence.price_cvd_divergence_frame's
# price-vs-CVD regular/hidden divergence evidence, computed FROM the same
# raw trade_flow frame (see build_feature_matrix's docstring).
CVD_DIVERGENCE_FEATURE_COLUMNS: tuple[str, ...] = (
    "cvd_regular_bullish_divergence",
    "cvd_hidden_bullish_divergence",
    "cvd_regular_bearish_divergence",
    "cvd_hidden_bearish_divergence",
    "cvd_confirmed_price_pivot_low",
    "cvd_confirmed_price_pivot_high",
    "cvd_pivot_age_bars",
)

# Present only when `cross_venue_context`
# (src.features.cross_venue.cross_venue_series_frame, pre-built by the
# caller for df's own canonical_instrument_id) is passed in -
# cross_venue_median_price is skipped in favor of the close-relative
# cross_venue_median_distance (see build_feature_matrix's docstring).
CROSS_VENUE_CONTEXT_FEATURE_COLUMNS: tuple[str, ...] = (
    "cross_venue_count",
    "cross_venue_max_abs_deviation_bps",
    "cross_venue_outlier_count",
    "cross_venue_median_distance",
)
