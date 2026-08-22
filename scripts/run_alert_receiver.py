"""Run the durable Greenfield Alertmanager webhook receiver."""

from __future__ import annotations

import signal
import threading
from pathlib import Path
from typing import Annotated

import typer

from src.monitoring.alert_receiver import (
    DEFAULT_FORWARD_TIMEOUT_SECS,
    DEFAULT_MAX_BODY_BYTES,
    build_processor_from_environment,
    create_alert_server,
)

app = typer.Typer(add_completion=False)


@app.command()
def run(
    host: Annotated[str, typer.Option(help="Listen address inside the container.")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Listen port.")] = 8080,
    journal_root: Annotated[
        Path, typer.Option(help="Append-only alert audit journal directory.")
    ] = Path("reports/alerts"),
    max_body_bytes: Annotated[
        int, typer.Option(help="Maximum accepted Alertmanager request body.")
    ] = DEFAULT_MAX_BODY_BYTES,
    forward_timeout_secs: Annotated[
        float, typer.Option(help="Optional external HTTPS webhook timeout.")
    ] = DEFAULT_FORWARD_TIMEOUT_SECS,
) -> None:
    processor = build_processor_from_environment(
        journal_root=journal_root,
        forward_timeout_secs=forward_timeout_secs,
    )
    server = create_alert_server(
        (host, port), processor, max_body_bytes=max_body_bytes
    )
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    server.timeout = 1.0
    typer.echo(f"alert receiver listening on {host}:{port}")
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()


if __name__ == "__main__":
    app()
