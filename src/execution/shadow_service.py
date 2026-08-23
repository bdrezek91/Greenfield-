"""Production SHADOW service process (Cycle 2): wires the durable queue,
immutable payload store, and audited no-order runtime into one supervised,
SIGTERM/SIGINT-safe loop. No execution adapter is imported anywhere in this
module or its dependencies - the service can never submit a real order.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.execution.mode import TradingMode
from src.execution.shadow_loop import (
    DurableShadowQueue,
    ShadowEventLoop,
    ShadowHealthPublisher,
    ShadowLoopConfig,
    ShadowLoopFatalError,
)
from src.execution.shadow_preflight import run_shadow_preflight
from src.execution.shadow_runtime import (
    ShadowAuditJournal,
    ShadowRuntime,
    ShadowSessionContext,
)
from src.execution.shadow_store import ShadowWorkStore
from src.research.locking import GracefulShutdown
from src.risk.portfolio_engine import PortfolioRiskConfig, PortfolioRiskEngine
from src.risk.portfolio_state_store import PortfolioRiskStateStore

log = structlog.get_logger()

SHADOW_EXIT_OK = 0
SHADOW_EXIT_PREFLIGHT_FAILED = 2
SHADOW_EXIT_FATAL = 3


def run_shadow_service(
    *,
    context: ShadowSessionContext,
    env: Mapping[str, str],
    queue_db_path: Path,
    work_store_dir: Path,
    risk_state_path: Path,
    audit_journal_path: Path,
    health_path: Path,
    risk_config: PortfolioRiskConfig | None = None,
    loop_config: ShadowLoopConfig | None = None,
    shutdown_requested: Callable[[], bool] | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Run the SHADOW service until shutdown is requested. Returns an exit
    code rather than calling sys.exit so callers (and tests) can inspect it.
    `shutdown_requested` is injected for tests; production callers leave it
    None to get a real SIGTERM/SIGINT-driven GracefulShutdown.
    """
    preflight = run_shadow_preflight(
        env=env,
        context=context,
        queue_db_path=queue_db_path,
        work_store_dir=work_store_dir,
        audit_journal_path=audit_journal_path,
    )
    if not preflight.all_passed:
        for failure in preflight.failures():
            log.error("shadow service preflight failed", check=failure.name, detail=failure.detail)
        return SHADOW_EXIT_PREFLIGHT_FAILED

    resolved_risk_config = risk_config or PortfolioRiskConfig()
    risk_store = PortfolioRiskStateStore(risk_state_path)
    journal = ShadowAuditJournal(audit_journal_path)
    work_store = ShadowWorkStore(work_store_dir, now_fn=now_fn)
    queue = DurableShadowQueue(queue_db_path)

    if risk_store.load() is None:
        runtime = ShadowRuntime.initialize_new(
            trading_mode=TradingMode.SHADOW,
            context=context,
            risk_engine=PortfolioRiskEngine(resolved_risk_config),
            risk_store=risk_store,
            journal=journal,
            initialized_at_utc=now_fn(),
        )
        log.info("shadow runtime initialized", session_id=context.session_id)
    else:
        runtime = ShadowRuntime.resume(
            trading_mode=TradingMode.SHADOW,
            context=context,
            risk_store=risk_store,
            journal=journal,
            risk_config=resolved_risk_config,
        )
        log.info("shadow runtime resumed", session_id=context.session_id)

    loop = ShadowEventLoop(
        queue=queue,
        runtime=runtime,
        work_loader=work_store.load,
        config=loop_config or ShadowLoopConfig(),
        health_publisher=ShadowHealthPublisher(health_path),
        now_fn=now_fn,
        sleep_fn=sleep_fn,
    )

    if shutdown_requested is not None:
        return _run_until_stopped(loop, shutdown_requested)

    with GracefulShutdown() as shutdown:
        exit_code = _run_until_stopped(loop, lambda: shutdown.requested)
    log.info("shadow service shut down cleanly")
    return exit_code


def _run_until_stopped(loop: ShadowEventLoop, shutdown_requested: Callable[[], bool]) -> int:
    try:
        loop.run_until(shutdown_requested)
    except ShadowLoopFatalError:
        log.exception("shadow event loop failed fatally; safety hold could not be persisted")
        return SHADOW_EXIT_FATAL
    return SHADOW_EXIT_OK
