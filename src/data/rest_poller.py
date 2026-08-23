"""Shared poll-forever loop for REST-based (non-WebSocket) live collectors -
extracted from src/data/binance_derivatives_collector.py in Cycle 18 so a
third exchange's poller (src/data/okx_derivatives_collector.py) doesn't
duplicate the same ~15 lines a third time. Bybit's
src/data/long_short_ratio_collector.py predates this extraction and keeps
its own inline copy rather than being retrofitted here - out of scope for
this cycle, and it already works.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger()


def raise_keyboard_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def run_polling_loop(
    *,
    name: str,
    poll_once: Callable[[], int],
    poll_interval_secs: float,
    sleep: Callable[[float], None] = time.sleep,
    extra_log_fields: dict[str, Any] | None = None,
) -> None:
    """SIGTERM -> KeyboardInterrupt (so `docker stop` triggers the same
    clean shutdown path as Ctrl-C), one bad poll logged and retried rather
    than killing the whole loop.
    """
    fields = extra_log_fields or {}
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)
    log.info(f"{name} collector starting", poll_interval_secs=poll_interval_secs, **fields)
    try:
        while True:
            try:
                n = poll_once()
                if n:
                    log.info(f"{name} poll", new_rows=n, **fields)
            except Exception as exc:  # noqa: BLE001 - one bad poll must not kill the loop
                log.error(f"{name} poll failed", error=str(exc), **fields)
            sleep(poll_interval_secs)
    except KeyboardInterrupt:
        log.info(f"{name} collector stopping", **fields)
