"""src.data.deribit_option_instrument's Deribit option instrument-name
parser and near-ATM selection logic (Cycle 36).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.data.deribit_option_instrument import (
    DeribitInstrumentNameError,
    parse_deribit_option_instrument_name,
    select_near_atm_option_instruments,
)


def test_parses_a_real_put_instrument_name() -> None:
    parsed = parse_deribit_option_instrument_name("BTC-25JUN27-150000-P")

    assert parsed.base_currency == "BTC"
    assert parsed.expiry_utc == datetime(2027, 6, 25, 8, 0, tzinfo=UTC)
    assert parsed.strike == 150_000.0
    assert parsed.option_right == "put"


def test_parses_a_real_call_instrument_name() -> None:
    parsed = parse_deribit_option_instrument_name("BTC-28AUG26-94000-C")

    assert parsed.base_currency == "BTC"
    assert parsed.expiry_utc == datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
    assert parsed.strike == 94_000.0
    assert parsed.option_right == "call"


def test_parses_a_single_digit_day() -> None:
    parsed = parse_deribit_option_instrument_name("ETH-5SEP26-4000-C")

    assert parsed.expiry_utc == datetime(2026, 9, 5, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "name",
    [
        "BTC-25JUN27-150000",  # missing right code
        "BTC-25XYZ27-150000-P",  # unrecognized month
        "BTC-25JUN27-abc-P",  # unparseable strike
        "BTC-25JUN27-150000-X",  # unrecognized right code
        "BTC-PERPETUAL",  # not an option at all
    ],
)
def test_rejects_malformed_names(name: str) -> None:
    with pytest.raises(DeribitInstrumentNameError):
        parse_deribit_option_instrument_name(name)


def _summary_rows() -> list[dict[str, object]]:
    underlying = 100_000.0
    rows = []
    for expiry in ("24AUG26", "25AUG26", "26SEP26"):
        for strike in (95_000, 97_500, 99_000, 100_000, 101_000, 102_500, 105_000):
            for right in ("C", "P"):
                rows.append(
                    {
                        "instrument_name": f"BTC-{expiry}-{strike}-{right}",
                        "underlying_price": underlying,
                    }
                )
    return rows


def test_select_near_atm_picks_the_nearest_expiries_and_strikes() -> None:
    selected = select_near_atm_option_instruments(
        _summary_rows(), expiries_count=2, strikes_per_side=2
    )

    # 2 expiries * 2 strikes/side * 2 sides (call+put) = 8.
    assert len(selected) == 8
    names = set(selected)
    # Nearest expiry (soonest date) must be included; the farthest must not.
    assert any(name.startswith("BTC-24AUG26-") for name in names)
    assert not any(name.startswith("BTC-26SEP26-") for name in names)
    # The two strikes nearest 100_000 on each side: 99000/100000 (put side
    # ties resolved by absolute distance) - just check the far strikes
    # (95000/105000) are excluded.
    assert not any("95000" in name for name in names)
    assert not any("105000" in name for name in names)


def test_select_near_atm_ignores_unparseable_or_incomplete_rows() -> None:
    rows = _summary_rows() + [
        {"instrument_name": "BTC-PERPETUAL", "underlying_price": 100_000.0},
        {"instrument_name": "BTC-24AUG26-99000-C"},  # missing underlying_price
    ]

    selected = select_near_atm_option_instruments(rows, expiries_count=1, strikes_per_side=1)

    assert "BTC-PERPETUAL" not in selected
    assert len(selected) == 2  # 1 expiry * 1 strike/side * 2 sides


def test_select_near_atm_returns_empty_for_no_usable_rows() -> None:
    assert select_near_atm_option_instruments([], expiries_count=1, strikes_per_side=1) == []


def test_select_near_atm_rejects_non_positive_parameters() -> None:
    with pytest.raises(ValueError, match="positive"):
        select_near_atm_option_instruments(_summary_rows(), expiries_count=0, strikes_per_side=1)
    with pytest.raises(ValueError, match="positive"):
        select_near_atm_option_instruments(_summary_rows(), expiries_count=1, strikes_per_side=0)
