from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pybit.exceptions import InvalidRequestError

from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BYBIT_PUBLIC_REST_URL,
    BybitDemoGatewayError,
    DemoOrderStatus,
    PybitBybitDemoGateway,
    PybitPublicLinearMarketData,
)
from src.execution.intent import IntentSide


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"retCode": 0, "retMsg": "OK", "result": result}


class FakePybitClient:
    def __init__(self, *, endpoint: str = BYBIT_DEMO_REST_URL) -> None:
        self.endpoint = endpoint
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.open_rows: list[dict[str, Any]] = []
        self.position_rows: list[dict[str, Any]] = [{"symbol": "BTCUSDT"}]
        self.history_rows: list[dict[str, Any]] = []
        self.execution_rows: list[dict[str, Any]] = []
        self.fee_rows: list[dict[str, Any]] = [
            {"symbol": "BTCUSDT", "makerFeeRate": "0.0002", "takerFeeRate": "0.00055"}
        ]
        self.leverage_error_code: int | None = None

    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))

    def get_api_key_information(self, **kwargs: Any) -> dict[str, Any]:
        self._record("key", kwargs)
        return _ok(
            {
                "readOnly": 0,
                "permissions": {
                    "ContractTrade": ["Order", "Position"],
                    "Spot": ["SpotTrade"],
                    "Derivatives": ["DerivativesTrade"],
                    "Options": ["OptionsTrade"],
                    "Wallet": [],
                },
                "ips": ["57.128.220.89"],
            }
        )

    def get_wallet_balance(self, **kwargs: Any) -> dict[str, Any]:
        self._record("wallet", kwargs)
        return _ok(
            {
                "list": [
                    {
                        "accountType": "UNIFIED",
                        "totalEquity": "100.25",
                        "totalWalletBalance": "100.00",
                        "totalAvailableBalance": "99.75",
                    }
                ]
            }
        )

    def get_positions(self, **kwargs: Any) -> dict[str, Any]:
        self._record("positions", kwargs)
        return _ok({"list": self.position_rows})

    def get_open_orders(self, **kwargs: Any) -> dict[str, Any]:
        self._record("open", kwargs)
        return _ok({"list": self.open_rows})

    def get_order_history(self, **kwargs: Any) -> dict[str, Any]:
        self._record("history", kwargs)
        return _ok({"list": self.history_rows})

    def get_executions(self, **kwargs: Any) -> dict[str, Any]:
        self._record("executions", kwargs)
        return _ok({"list": self.execution_rows})

    def get_fee_rates(self, **kwargs: Any) -> dict[str, Any]:
        self._record("fee", kwargs)
        return _ok({"list": self.fee_rows})

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        self._record("place", kwargs)
        return _ok({"orderId": "exchange-1", "orderLinkId": kwargs["orderLinkId"]})

    def cancel_order(self, **kwargs: Any) -> dict[str, Any]:
        self._record("cancel", kwargs)
        return _ok({"orderId": "exchange-1", "orderLinkId": kwargs["orderLinkId"]})

    def set_leverage(self, **kwargs: Any) -> dict[str, Any]:
        self._record("leverage", kwargs)
        if self.leverage_error_code is not None:
            raise InvalidRequestError(
                request="POST /v5/position/set-leverage",
                message="leverage not modified",
                status_code=self.leverage_error_code,
                time="now",
                resp_headers=None,
            )
        return _ok({})


class FakePublicClient:
    endpoint = BYBIT_PUBLIC_REST_URL

    def get_tickers(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"category": "linear", "symbol": "BTCUSDT"}
        return _ok(
            {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "lastPrice": "101234.5",
                        "fundingRate": "0.0001",
                        "openInterest": "12345.6",
                    }
                ]
            }
        )

    def get_instruments_info(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"category": "linear", "symbol": "BTCUSDT"}
        return _ok(
            {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"},
                    }
                ]
            }
        )


def test_gateway_rejects_any_non_demo_endpoint() -> None:
    client = FakePybitClient(endpoint="https://api.bybit.com")
    with pytest.raises(BybitDemoGatewayError, match="non-Demo"):
        PybitBybitDemoGateway(  # pragma: allowlist secret
            api_key="key",  # pragma: allowlist secret
            api_secret="secret",  # pragma: allowlist secret
            client=client,  # pragma: allowlist secret
        )


def test_preflight_is_read_only_and_sanitized() -> None:
    client = FakePybitClient()
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )

    report = gateway.preflight()

    assert report.endpoint == BYBIT_DEMO_REST_URL
    assert report.api_key_verified
    assert report.trade_permissions_verified
    assert report.ip_restriction_verified
    assert report.restricted_ips == ("57.128.220.89",)
    assert report.provider_bundled_permission_categories == (
        "Derivatives",
        "Options",
        "Spot",
    )
    assert (report.wallet_rows, report.position_rows, report.open_order_rows) == (1, 1, 0)
    assert [name for name, _ in client.calls] == ["key", "wallet", "positions", "open"]


def test_account_balance_reads_sanitized_unified_totals() -> None:
    client = FakePybitClient()
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )

    balance = gateway.account_balance()

    assert balance.total_equity_usd == Decimal("100.25")
    assert balance.total_wallet_balance_usd == Decimal("100.00")
    assert balance.total_available_balance_usd == Decimal("99.75")
    assert client.calls == [("wallet", {"accountType": "UNIFIED"})]


def test_fee_rate_reads_exact_linear_account_rates() -> None:
    client = FakePybitClient()
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )

    fee_rate = gateway.fee_rate(symbol="BTCUSDT")

    assert fee_rate.symbol == "BTCUSDT"
    assert fee_rate.maker_fee_rate == Decimal("0.0002")
    assert fee_rate.taker_fee_rate == Decimal("0.00055")
    assert client.calls == [("fee", {"category": "linear", "symbol": "BTCUSDT"})]


def test_fee_rate_rejects_wrong_symbol_or_negative_rate() -> None:
    client = FakePybitClient()
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )
    client.fee_rows = [
        {"symbol": "ETHUSDT", "makerFeeRate": "0.0002", "takerFeeRate": "0.00055"}
    ]
    with pytest.raises(BybitDemoGatewayError, match="requested symbol"):
        gateway.fee_rate(symbol="BTCUSDT")

    client.fee_rows = [
        {"symbol": "BTCUSDT", "makerFeeRate": "-0.0001", "takerFeeRate": "0.00055"}
    ]
    with pytest.raises(BybitDemoGatewayError, match="maker fee rate"):
        gateway.fee_rate(symbol="BTCUSDT")


def test_account_exposure_returns_only_nonzero_positions_and_open_orders() -> None:
    client = FakePybitClient()
    client.position_rows = [
        {
            "symbol": "BTCUSDT",
            "positionIdx": 0,
            "side": "Buy",
            "size": "0.25",
            "leverage": "100",
        },
        {
            "symbol": "ETHUSDT",
            "positionIdx": 0,
            "side": "",
            "size": "0",
            "leverage": "100",
        },
    ]
    client.open_rows = [
        {
            "orderId": "manual-1",
            "orderLinkId": "",
            "symbol": "SOLUSDT",
            "side": "Sell",
            "orderType": "Limit",
            "qty": "2",
            "leavesQty": "1.5",
            "reduceOnly": False,
        }
    ]
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )

    exposure = gateway.account_exposure()

    assert [(item.symbol, item.side, item.size) for item in exposure.positions] == [
        ("BTCUSDT", "Buy", Decimal("0.25"))
    ]
    assert len(exposure.open_orders) == 1
    assert exposure.open_orders[0].order_link_id is None
    assert exposure.open_orders[0].leaves_quantity == Decimal("1.5")
    assert [name for name, _ in client.calls] == ["positions", "open"]


def test_place_and_cancel_are_fixed_to_linear_post_only() -> None:
    client = FakePybitClient()
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )

    ack = gateway.place_post_only(
        order_link_id="gfd-0123456789abcdef0123456789abcdef",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=Decimal("0.001"),
        price=Decimal("99900.1"),
    )
    gateway.cancel(order_link_id=ack.order_link_id, symbol="BTCUSDT")

    place = next(kwargs for name, kwargs in client.calls if name == "place")
    assert place == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "orderType": "Limit",
        "qty": "0.001",
        "price": "99900.1",
        "timeInForce": "PostOnly",
        "positionIdx": 0,
        "orderLinkId": ack.order_link_id,
        "reduceOnly": False,
    }
    cancel = next(kwargs for name, kwargs in client.calls if name == "cancel")
    assert cancel["category"] == "linear"
    assert cancel["orderLinkId"] == ack.order_link_id


def test_market_round_trip_methods_are_fixed_to_linear_and_reduce_only() -> None:
    client = FakePybitClient()
    client.position_rows = [
        {
            "symbol": "BTCUSDT",
            "positionIdx": 0,
            "side": "",
            "size": "0",
            "leverage": "100",
        }
    ]
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,
    )

    gateway.set_leverage(symbol="BTCUSDT", leverage=100)
    gateway.place_market(
        order_link_id="gfd-entry-0123456789abcdef0123456789",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=Decimal("0.001"),
        reduce_only=False,
    )
    gateway.place_market(
        order_link_id="gfd-close-0123456789abcdef0123456789",
        symbol="BTCUSDT",
        side=IntentSide.SELL,
        quantity=Decimal("0.001"),
        reduce_only=True,
    )

    leverage = next(kwargs for name, kwargs in client.calls if name == "leverage")
    assert leverage == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "buyLeverage": "100",
        "sellLeverage": "100",
    }
    markets = [kwargs for name, kwargs in client.calls if name == "place"]
    assert markets[0]["orderType"] == "Market" and markets[0]["reduceOnly"] is False
    assert markets[1]["orderType"] == "Market" and markets[1]["reduceOnly"] is True
    assert all(kwargs["positionIdx"] == 0 for kwargs in markets)


def test_setting_existing_leverage_is_idempotent_but_other_errors_propagate() -> None:
    client = FakePybitClient()
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )
    client.leverage_error_code = 110043
    gateway.set_leverage(symbol="BTCUSDT", leverage=100)

    client.leverage_error_code = 110001
    with pytest.raises(InvalidRequestError):
        gateway.set_leverage(symbol="BTCUSDT", leverage=100)


def test_positions_open_order_count_and_public_instrument_snapshot() -> None:
    client = FakePybitClient()
    client.position_rows = [
        {
            "symbol": "BTCUSDT",
            "positionIdx": 0,
            "side": "Buy",
            "size": "0.001",
            "leverage": "100",
        }
    ]
    client.open_rows = [{"orderId": "existing"}]
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,
    )

    positions = gateway.fetch_positions(symbol="BTCUSDT")
    count = gateway.open_order_count(symbol="BTCUSDT")
    public = PybitPublicLinearMarketData(client=FakePublicClient()).instrument_snapshot(
        symbol="BTCUSDT"
    )

    assert positions[0].size == Decimal("0.001")
    assert positions[0].leverage == Decimal("100")
    assert count == 1
    assert public.last_price == Decimal("101234.5")
    assert public.quantity_step == public.minimum_order_quantity == Decimal("0.001")


def test_public_funding_snapshot_parses_funding_rate_and_open_interest() -> None:
    funding = PybitPublicLinearMarketData(client=FakePublicClient()).funding_snapshot(
        symbol="BTCUSDT"
    )
    assert funding.funding_rate == Decimal("0.0001")
    assert funding.open_interest == Decimal("12345.6")


def test_fetch_order_and_executions_parse_exchange_identity() -> None:
    client = FakePybitClient()
    order_link_id = "gfd-0123456789abcdef0123456789abcdef"
    client.history_rows = [
        {
            "orderId": "exchange-1",
            "orderLinkId": order_link_id,
            "symbol": "BTCUSDT",
            "orderStatus": "Cancelled",
            "cumExecQty": "0.001",
            "updatedTime": "1787594401000",
            "rejectReason": "",
        }
    ]
    client.execution_rows = [
        {
            "execId": "exec-1",
            "orderLinkId": order_link_id,
            "execQty": "0.001",
            "execPrice": "100000.1",
            "execFee": "-0.02",
            "execTime": "1787594400000",
        }
    ]
    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=client,  # pragma: allowlist secret
    )

    order = gateway.fetch_order(order_link_id=order_link_id, symbol="BTCUSDT")
    executions = gateway.fetch_executions(order_link_id=order_link_id, symbol="BTCUSDT")

    assert order is not None and order.status is DemoOrderStatus.CANCELLED
    assert order.cumulative_filled_quantity == Decimal("0.001")
    assert executions[0].execution_id == "exec-1"
    assert executions[0].fee_quote == Decimal("0.02")


def test_nonzero_retcode_and_identity_mismatch_fail_closed() -> None:
    class RejectingClient(FakePybitClient):
        def place_order(self, **kwargs: Any) -> dict[str, Any]:
            return {"retCode": 10001, "retMsg": "bad request", "result": {}}

    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=RejectingClient(),
    )
    with pytest.raises(BybitDemoGatewayError, match="retCode=10001"):
        gateway.place_post_only(
            order_link_id="gfd-0123456789abcdef0123456789abcdef",
            symbol="BTCUSDT",
            side=IntentSide.BUY,
            quantity=Decimal("0.001"),
            price=Decimal("99900.1"),
        )


@pytest.mark.parametrize(
    "key_info",
    [
        {
            "readOnly": 1,
            "permissions": {"ContractTrade": ["Order", "Position"]},
            "ips": ["57.128.220.89"],
        },
        {
            "readOnly": 0,
            "permissions": {"ContractTrade": ["Order"]},
            "ips": ["57.128.220.89"],
        },
        {
            "readOnly": 0,
            "permissions": {
                "ContractTrade": ["Order", "Position"],
                "Wallet": ["AccountTransfer"],
            },
            "ips": ["57.128.220.89"],
        },
        {
            "readOnly": 0,
            "permissions": {"ContractTrade": ["Order", "Position"]},
            "ips": ["*"],
        },
    ],
)
def test_preflight_rejects_unsafe_key_authorization(key_info: dict[str, Any]) -> None:
    class UnsafeClient(FakePybitClient):
        def get_api_key_information(self, **kwargs: Any) -> dict[str, Any]:
            return _ok(key_info)

    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=UnsafeClient(),
    )
    with pytest.raises(BybitDemoGatewayError):
        gateway.preflight()


def test_preflight_reports_only_unexpected_permission_category_names() -> None:
    class UnexpectedPermissionClient(FakePybitClient):
        def get_api_key_information(self, **kwargs: Any) -> dict[str, Any]:
            return _ok(
                {
                    "readOnly": 0,
                    "permissions": {
                        "ContractTrade": ["Order", "Position"],
                        "Wallet": ["AccountTransfer-sensitive-value"],
                    },
                    "ips": ["57.128.220.89"],
                }
            )

    gateway = PybitBybitDemoGateway(  # pragma: allowlist secret
        api_key="key",  # pragma: allowlist secret
        api_secret="secret",  # pragma: allowlist secret
        client=UnexpectedPermissionClient(),
    )
    with pytest.raises(BybitDemoGatewayError, match=r"\(Wallet\)") as error:
        gateway.preflight()
    assert "sensitive-value" not in str(error.value)
