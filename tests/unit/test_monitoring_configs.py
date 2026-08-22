"""Static contracts for the version-pinned Phase 1 observability stack."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_prometheus_scrapes_all_monitoring_targets_and_loads_rules() -> None:
    config = _yaml("monitoring/prometheus/prometheus.yml")
    jobs = {item["job_name"] for item in config["scrape_configs"]}
    assert jobs == {
        "prometheus",
        "greenfield-node",
        "alertmanager",
        "greenfield-alert-receiver",
    }
    assert config["rule_files"] == ["/etc/prometheus/alerts.yml"]
    assert config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == [
        "alertmanager:9093"
    ]


def test_every_alert_has_severity_owner_description_and_runbook() -> None:
    config = _yaml("monitoring/prometheus/alerts.yml")
    rules = [rule for group in config["groups"] for rule in group["rules"]]
    names = {rule["alert"] for rule in rules}
    assert {
        "GreenfieldCollectorSetIncomplete",
        "GreenfieldCollectorHeartbeatStale",
        "GreenfieldCollectorDroppedEvents",
        "GreenfieldCollectorSequenceUncertain",
        "GreenfieldCollectorStorageCritical",
        "GreenfieldCollectorStorageReserveBreached",
        "GreenfieldMonitoringTargetDown",
        "GreenfieldAlertForwardingFailed",
    } <= names
    for rule in rules:
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["labels"]["owner"]
        assert rule["annotations"]["summary"]
        assert rule["annotations"]["description"]
        assert rule["annotations"]["runbook_url"].startswith("https://github.com/")


def test_alertmanager_routes_resolved_and_firing_alerts_to_durable_receiver() -> None:
    config = _yaml("monitoring/alertmanager/alertmanager.yml")
    assert config["route"]["receiver"] == "greenfield-durable-webhook"
    webhook = config["receivers"][0]["webhook_configs"][0]
    assert webhook["url"] == "http://alert-receiver:8080/alerts"
    assert webhook["send_resolved"] is True


def test_monitoring_compose_is_pinned_local_only_and_non_privileged() -> None:
    config = _yaml("docker-compose.monitoring.yml")
    services = config["services"]
    assert set(services) == {
        "node-exporter",
        "alert-receiver",
        "alertmanager",
        "prometheus",
        "grafana",
    }
    for service in services.values():
        assert service["profiles"] == ["monitoring"]
        assert service["restart"] == "unless-stopped"
        assert "no-new-privileges:true" in service["security_opt"]
        image = service.get("image", "")
        assert image and not image.endswith(":latest")
    for name in ("alertmanager", "prometheus", "grafana"):
        assert services[name]["ports"][0].startswith(
            "${MONITORING_BIND_ADDRESS:-127.0.0.1}:"
        )
    password = services["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"]
    assert ":?Set GRAFANA_ADMIN_PASSWORD" in password
    assert services["alert-receiver"]["build"]["dockerfile"] == (
        "docker/Dockerfile.collector"
    )
    assert services["alert-receiver"]["image"] == "greenfield-phase1:collector"
    assert services["node-exporter"]["volumes"] == [
        "${DATA_DIR:-./data}:/textfiles:ro"
    ]


def test_grafana_dashboard_is_provisioned_with_operational_panels() -> None:
    dashboard = json.loads(
        (ROOT / "monitoring/grafana/dashboards/raw-collector-overview.json").read_text()
    )
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert dashboard["uid"] == "greenfield-raw-collector"
    assert {
        "Collector connections",
        "Heartbeat age",
        "Firing critical alerts",
        "Raw event throughput",
        "Writer backlog and queue",
        "Raw volume free",
        "Data-integrity violations",
        "Reconnects since process start",
    } == titles
