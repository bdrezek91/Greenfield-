"""Strict Bybit Demo REST gateway; no configurable or mainnet execution host."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, cast

from pybit.unified_trading import HTTP

from src.execution.intent import IntentSide

BYBIT_DEMO_REST_URL = "https://api-demo.bybit.com"
BYBIT_PUBLIC_REST_URL = "https://api.bybit.com"
_ORDER_LINK_ID = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


class BybitDemoGatewayError(RuntimeError):
    """The Demo endpoint rejected a request or returned an invalid payload."""


class DemoOrderStatus(StrEnum):
    NEW = "New"
    PARTIALLY_FILLED = "PartiallyFilled"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"
    DEACTIVATED = "Deactivated"


@dataclass(frozen=True, slots=True)
class DemoPreflightReport:
    endpoint: str
    api_key_verified: bool
    trade_permissions_verified: bool
    ip_restriction_verified: bool
    restricted_ips: tuple[str, ...]
    provider_bundled_permission_categories: tuple[str, ...]
    wallet_rows: int
    position_rows: int
    open_order_rows: int


@dataclass(frozen=True, slots=True)
class DemoOrderAck:
    order_id: str
    order_link_id: str

    def __post_init__(self) -> None:
        if not self.order_id.strip() or not _ORDER_LINK_ID.fullmatch(self.order_link_id):
            raise BybitDemoGatewayError("invalid Demo order acknowledgement")


@dataclass(frozen=True, slots=True)
class DemoOrderSnapshot:
    order_id: str
    order_link_id: str
    symbol: str
    status: DemoOrderStatus
    cumulative_filled_quantity: Decimal
    updated_at_utc: datetime
    reject_reason: str | None

    def __post_init__(self) -> None:
        if (
            not self.order_id.strip()
            or not _ORDER_LINK_ID.fullmatch(self.order_link_id)
            or not self.symbol.strip()
            or self.cumulative_filled_quantity < 0
            or self.updated_at_utc.tzinfo is None
        ):
            raise BybitDemoGatewayError("invalid Demo order snapshot")


@dataclass(frozen=True, slots=True)
class DemoExecution:
    execution_id: str
    order_link_id: str
    quantity: Decimal
    price: Decimal
    fee_quote: Decimal
    executed_at_utc: datetime

    def __post_init__(self) -> None:
        if (
            not self.execution_id.strip()
            or not _ORDER_LINK_ID.fullmatch(self.order_link_id)
            or self.quantity <= 0
            or self.price <= 0
            or self.fee_quote < 0
            or self.executed_at_utc.tzinfo is None
        ):
            raise BybitDemoGatewayError("invalid Demo execution")


@dataclass(frozen=True, slots=True)
class DemoPositionSnapshot:
    symbol: str
    position_index: int
    side: str | None
    size: Decimal
    leverage: Decimal

    def __post_init__(self) -> None:
        if (
            not self.symbol.strip()
            or self.position_index not in {0, 1, 2}
            or self.side not in {None, "Buy", "Sell"}
            or not self.size.is_finite()
            or self.size < 0
            or not self.leverage.is_finite()
            or self.leverage <= 0
        ):
            raise BybitDemoGatewayError("invalid Demo position snapshot")


@dataclass(frozen=True, slots=True)
class PublicLinearInstrumentSnapshot:
    symbol: str
    last_price: Decimal
    quantity_step: Decimal
    minimum_order_quantity: Decimal

    def __post_init__(self) -> None:
        if (
            not self.symbol.strip()
            or not self.last_price.is_finite()
            or self.last_price <= 0
            or not self.quantity_step.is_finite()
            or self.quantity_step <= 0
            or not self.minimum_order_quantity.is_finite()
            or self.minimum_order_quantity <= 0
        ):
            raise BybitDemoGatewayError("invalid Bybit public instrument snapshot")


class BybitDemoGateway(Protocol):
    endpoint: str

    def preflight(self) -> DemoPreflightReport: ...

    def place_post_only(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        price: Decimal,
    ) -> DemoOrderAck: ...

    def cancel(self, *, order_link_id: str, symbol: str) -> DemoOrderAck: ...

    def set_leverage(self, *, symbol: str, leverage: int) -> None: ...

    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck: ...

    def fetch_positions(self, *, symbol: str) -> tuple[DemoPositionSnapshot, ...]: ...

    def open_order_count(self, *, symbol: str) -> int: ...

    def fetch_order(
        self, *, order_link_id: str, symbol: str
    ) -> DemoOrderSnapshot | None: ...

    def fetch_executions(
        self, *, order_link_id: str, symbol: str
    ) -> tuple[DemoExecution, ...]: ...


class _PybitClient(Protocol):
    endpoint: str

    def get_api_key_information(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_wallet_balance(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_positions(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_open_orders(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_order_history(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_executions(self, **kwargs: Any) -> dict[str, Any]: ...

    def place_order(self, **kwargs: Any) -> dict[str, Any]: ...

    def cancel_order(self, **kwargs: Any) -> dict[str, Any]: ...

    def set_leverage(self, **kwargs: Any) -> dict[str, Any]: ...


class _PybitPublicClient(Protocol):
    endpoint: str

    def get_tickers(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_instruments_info(self, **kwargs: Any) -> dict[str, Any]: ...


class PybitBybitDemoGateway:
    """Authenticated execution gateway pinned to Bybit's Demo host.

    There is intentionally no endpoint, testnet, or demo constructor option.
    The concrete pybit client is always built with ``testnet=False`` and
    ``demo=True`` and is rejected if its resolved endpoint differs from the
    official Demo URL.
    """

    endpoint = BYBIT_DEMO_REST_URL

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        client: _PybitClient | None = None,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Bybit Demo API key and secret are required")
        self._client: _PybitClient = client or cast(
            _PybitClient,
            HTTP(
                testnet=False,
                demo=True,
                api_key=api_key,
                api_secret=api_secret,
            ),
        )
        if self._client.endpoint != BYBIT_DEMO_REST_URL:
            raise BybitDemoGatewayError(
                f"refusing non-Demo Bybit endpoint: {self._client.endpoint!r}"
            )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> PybitBybitDemoGateway:
        values = os.environ if env is None else env
        return cls(
            api_key=values.get("BYBIT_DEMO_API_KEY", ""),
            api_secret=values.get("BYBIT_DEMO_API_SECRET", ""),
        )

    def preflight(self) -> DemoPreflightReport:
        key_info = self._result(
            self._client.get_api_key_information(),
            "API key info",
        )
        restricted_ips, bundled_categories = _validate_demo_key_authorization(key_info)
        wallet = self._result(
            self._client.get_wallet_balance(accountType="UNIFIED"),
            "wallet balance",
        )
        positions = self._result(
            self._client.get_positions(category="linear", settleCoin="USDT"),
            "positions",
        )
        orders = self._result(
            self._client.get_open_orders(category="linear", settleCoin="USDT"),
            "open orders",
        )
        return DemoPreflightReport(
            endpoint=self.endpoint,
            api_key_verified=True,
            trade_permissions_verified=True,
            ip_restriction_verified=True,
            restricted_ips=restricted_ips,
            provider_bundled_permission_categories=bundled_categories,
            wallet_rows=len(_rows(wallet, "wallet balance")),
            position_rows=len(_rows(positions, "positions")),
            open_order_rows=len(_rows(orders, "open orders")),
        )

    def place_post_only(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        price: Decimal,
    ) -> DemoOrderAck:
        _validate_order_fields(order_link_id, symbol, quantity, price)
        result = self._result(
            self._client.place_order(
                category="linear",
                symbol=symbol,
                side="Buy" if side is IntentSide.BUY else "Sell",
                orderType="Limit",
                qty=_decimal_text(quantity),
                price=_decimal_text(price),
                timeInForce="PostOnly",
                positionIdx=0,
                orderLinkId=order_link_id,
                reduceOnly=False,
            ),
            "place order",
        )
        return _ack(result, expected_order_link_id=order_link_id)

    def cancel(self, *, order_link_id: str, symbol: str) -> DemoOrderAck:
        _validate_identity(order_link_id, symbol)
        result = self._result(
            self._client.cancel_order(
                category="linear",
                symbol=symbol,
                orderLinkId=order_link_id,
            ),
            "cancel order",
        )
        return _ack(result, expected_order_link_id=order_link_id)

    def set_leverage(self, *, symbol: str, leverage: int) -> None:
        _validate_identity("leverage-check", symbol)
        if not 1 <= leverage <= 100:
            raise ValueError("Bybit Demo leverage must be between 1 and 100")
        self._result(
            self._client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            ),
            "set leverage",
        )

    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck:
        _validate_order_fields(order_link_id, symbol, quantity, Decimal("1"))
        result = self._result(
            self._client.place_order(
                category="linear",
                symbol=symbol,
                side="Buy" if side is IntentSide.BUY else "Sell",
                orderType="Market",
                qty=_decimal_text(quantity),
                positionIdx=0,
                orderLinkId=order_link_id,
                reduceOnly=reduce_only,
            ),
            "place market order",
        )
        return _ack(result, expected_order_link_id=order_link_id)

    def fetch_positions(self, *, symbol: str) -> tuple[DemoPositionSnapshot, ...]:
        _validate_identity("position-check", symbol)
        result = self._result(
            self._client.get_positions(category="linear", symbol=symbol),
            "positions",
        )
        return tuple(_position(row, expected_symbol=symbol) for row in _rows(result, "positions"))

    def open_order_count(self, *, symbol: str) -> int:
        _validate_identity("open-order-check", symbol)
        result = self._result(
            self._client.get_open_orders(category="linear", symbol=symbol),
            "open orders",
        )
        return len(_rows(result, "open orders"))

    def fetch_order(
        self, *, order_link_id: str, symbol: str
    ) -> DemoOrderSnapshot | None:
        _validate_identity(order_link_id, symbol)
        for response, operation in (
            (
                self._client.get_open_orders(
                    category="linear",
                    symbol=symbol,
                    orderLinkId=order_link_id,
                ),
                "open orders",
            ),
            (
                self._client.get_order_history(
                    category="linear",
                    symbol=symbol,
                    orderLinkId=order_link_id,
                    limit=1,
                ),
                "order history",
            ),
        ):
            result = self._result(response, operation)
            rows = _rows(result, operation)
            if rows:
                return _order_snapshot(rows[0], expected_order_link_id=order_link_id)
        return None

    def fetch_executions(
        self, *, order_link_id: str, symbol: str
    ) -> tuple[DemoExecution, ...]:
        _validate_identity(order_link_id, symbol)
        result = self._result(
            self._client.get_executions(
                category="linear",
                symbol=symbol,
                orderLinkId=order_link_id,
                limit=100,
            ),
            "executions",
        )
        return tuple(
            _execution(row, expected_order_link_id=order_link_id)
            for row in _rows(result, "executions")
        )

    @staticmethod
    def _result(response: dict[str, Any], operation: str) -> dict[str, Any]:
        try:
            code = int(response["retCode"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BybitDemoGatewayError(
                f"Bybit Demo {operation} response has no valid retCode"
            ) from exc
        if code != 0:
            message = str(response.get("retMsg", "unknown error"))
            raise BybitDemoGatewayError(
                f"Bybit Demo {operation} failed with retCode={code}: {message}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise BybitDemoGatewayError(
                f"Bybit Demo {operation} response has no result object"
            )
        return result


class PybitPublicLinearMarketData:
    """Unauthenticated public market metadata; never an execution client."""

    endpoint = BYBIT_PUBLIC_REST_URL

    def __init__(self, *, client: _PybitPublicClient | None = None) -> None:
        self._client: _PybitPublicClient = client or cast(
            _PybitPublicClient,
            HTTP(testnet=False),
        )
        if self._client.endpoint != BYBIT_PUBLIC_REST_URL:
            raise BybitDemoGatewayError(
                f"refusing unexpected Bybit public endpoint: {self._client.endpoint!r}"
            )

    def instrument_snapshot(self, *, symbol: str) -> PublicLinearInstrumentSnapshot:
        _validate_identity("public-market-check", symbol)
        ticker_result = PybitBybitDemoGateway._result(
            self._client.get_tickers(category="linear", symbol=symbol),
            "public tickers",
        )
        instrument_result = PybitBybitDemoGateway._result(
            self._client.get_instruments_info(category="linear", symbol=symbol),
            "public instruments",
        )
        ticker_rows = _rows(ticker_result, "public tickers")
        instrument_rows = _rows(instrument_result, "public instruments")
        if len(ticker_rows) != 1 or len(instrument_rows) != 1:
            raise BybitDemoGatewayError("Bybit public snapshot is not unique")
        instrument = instrument_rows[0]
        lot_size = instrument.get("lotSizeFilter")
        if not isinstance(lot_size, dict):
            raise BybitDemoGatewayError("Bybit public instrument has no lot-size filter")
        try:
            return PublicLinearInstrumentSnapshot(
                symbol=symbol,
                last_price=Decimal(str(ticker_rows[0]["lastPrice"])),
                quantity_step=Decimal(str(lot_size["qtyStep"])),
                minimum_order_quantity=Decimal(str(lot_size["minOrderQty"])),
            )
        except (KeyError, ValueError) as exc:
            raise BybitDemoGatewayError("invalid Bybit public snapshot fields") from exc


def _validate_identity(order_link_id: str, symbol: str) -> None:
    if not _ORDER_LINK_ID.fullmatch(order_link_id):
        raise ValueError("Bybit orderLinkId must match [A-Za-z0-9_-]{1,36}")
    if not symbol or symbol != symbol.upper() or not symbol.isalnum():
        raise ValueError("Bybit Demo symbol must be uppercase alphanumeric")


def _validate_demo_key_authorization(
    result: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        read_only = int(result["readOnly"])
        permissions = result["permissions"]
        ips = result["ips"]
    except (KeyError, TypeError, ValueError) as exc:
        raise BybitDemoGatewayError("invalid Bybit Demo API-key authorization payload") from exc
    if read_only != 0:
        raise BybitDemoGatewayError("Bybit Demo API key is read-only")
    if not isinstance(permissions, dict) or not isinstance(ips, list):
        raise BybitDemoGatewayError("invalid Bybit Demo API-key permissions or IP list")
    contract_permissions = permissions.get("ContractTrade")
    contract_values = (
        {str(value) for value in contract_permissions}
        if isinstance(contract_permissions, list)
        else set()
    )
    if contract_values != {"Order", "Position"}:
        raise BybitDemoGatewayError(
            "Bybit Demo API key must have exactly ContractTrade Order/Position permissions"
        )
    provider_bundles = {
        "Spot": {"SpotTrade"},
        "Derivatives": {"DerivativesTrade"},
        "Options": {"OptionsTrade"},
    }
    bundled_categories: list[str] = []
    unexpected_categories: list[str] = []
    for name, values in permissions.items():
        if name == "ContractTrade" or not isinstance(values, list) or not values:
            continue
        actual_values = {str(value) for value in values}
        if provider_bundles.get(str(name)) == actual_values:
            bundled_categories.append(str(name))
        else:
            unexpected_categories.append(str(name))
    if unexpected_categories:
        category_names = ", ".join(sorted(unexpected_categories))
        raise BybitDemoGatewayError(
            "Bybit Demo API key has unexpected permissions "
            f"({category_names}); use least privilege"
        )
    restricted_ips = tuple(str(value).strip() for value in ips if str(value).strip())
    if not restricted_ips or any(value in {"*", "0.0.0.0/0"} for value in restricted_ips):
        raise BybitDemoGatewayError("Bybit Demo API key is not restricted to named IPs")
    return restricted_ips, tuple(sorted(bundled_categories))


def _validate_order_fields(
    order_link_id: str,
    symbol: str,
    quantity: Decimal,
    price: Decimal,
) -> None:
    _validate_identity(order_link_id, symbol)
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("Bybit Demo quantity must be finite and positive")
    if not price.is_finite() or price <= 0:
        raise ValueError("Bybit Demo price must be finite and positive")


def _rows(result: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    rows = result.get("list")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise BybitDemoGatewayError(f"Bybit Demo {operation} result has no valid list")
    return cast(list[dict[str, Any]], rows)


def _ack(result: dict[str, Any], *, expected_order_link_id: str) -> DemoOrderAck:
    order_id = str(result.get("orderId", ""))
    order_link_id = str(result.get("orderLinkId", ""))
    if order_link_id != expected_order_link_id:
        raise BybitDemoGatewayError("Bybit Demo acknowledgement orderLinkId mismatch")
    return DemoOrderAck(order_id=order_id, order_link_id=order_link_id)


def _order_snapshot(
    row: dict[str, Any], *, expected_order_link_id: str
) -> DemoOrderSnapshot:
    order_link_id = str(row.get("orderLinkId", ""))
    if order_link_id != expected_order_link_id:
        raise BybitDemoGatewayError("Bybit Demo order snapshot orderLinkId mismatch")
    try:
        status = DemoOrderStatus(str(row["orderStatus"]))
        updated_at = _milliseconds(row["updatedTime"], "order updatedTime")
        cumulative = Decimal(str(row.get("cumExecQty", "0")))
    except (KeyError, ValueError) as exc:
        raise BybitDemoGatewayError("invalid Bybit Demo order snapshot fields") from exc
    reject_reason = str(row.get("rejectReason", "")).strip() or None
    return DemoOrderSnapshot(
        order_id=str(row.get("orderId", "")),
        order_link_id=order_link_id,
        symbol=str(row.get("symbol", "")),
        status=status,
        cumulative_filled_quantity=cumulative,
        updated_at_utc=updated_at,
        reject_reason=reject_reason,
    )


def _execution(row: dict[str, Any], *, expected_order_link_id: str) -> DemoExecution:
    order_link_id = str(row.get("orderLinkId", ""))
    if order_link_id != expected_order_link_id:
        raise BybitDemoGatewayError("Bybit Demo execution orderLinkId mismatch")
    try:
        quantity = Decimal(str(row["execQty"]))
        price = Decimal(str(row["execPrice"]))
        fee = abs(Decimal(str(row.get("execFee", "0"))))
        executed_at = _milliseconds(row["execTime"], "execution execTime")
    except (KeyError, ValueError) as exc:
        raise BybitDemoGatewayError("invalid Bybit Demo execution fields") from exc
    return DemoExecution(
        execution_id=str(row.get("execId", "")),
        order_link_id=order_link_id,
        quantity=quantity,
        price=price,
        fee_quote=fee,
        executed_at_utc=executed_at,
    )


def _position(
    row: dict[str, Any], *, expected_symbol: str
) -> DemoPositionSnapshot:
    symbol = str(row.get("symbol", ""))
    if symbol != expected_symbol:
        raise BybitDemoGatewayError("Bybit Demo position symbol mismatch")
    raw_side = str(row.get("side", "")).strip()
    try:
        return DemoPositionSnapshot(
            symbol=symbol,
            position_index=int(row["positionIdx"]),
            side=raw_side or None,
            size=Decimal(str(row["size"])),
            leverage=Decimal(str(row["leverage"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BybitDemoGatewayError("invalid Bybit Demo position fields") from exc


def _milliseconds(value: object, name: str) -> datetime:
    try:
        milliseconds = int(str(value))
    except ValueError as exc:
        raise BybitDemoGatewayError(f"invalid Bybit Demo {name}") from exc
    if milliseconds <= 0:
        raise BybitDemoGatewayError(f"invalid Bybit Demo {name}")
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
