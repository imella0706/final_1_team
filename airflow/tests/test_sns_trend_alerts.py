from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sns_trend.alerts import build_discord_failure_payload, notify_airflow_failure


class FakeTaskInstance:
    dag_id = "sns_trend_processed_validation"
    task_id = "validate_package"
    run_id = "manual__test"
    try_number = 1
    log_url = "http://localhost:8080/log"

    def xcom_pull(self, *, task_ids: str) -> dict[str, Any] | None:
        if task_ids != "resolve_processed_package":
            return None
        return {
            "version": "v3",
            "source_type": "gcs",
            "source_gcs_prefix": (
                "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
                "v3/cross_platform_signal_top_candidates/"
            ),
        }


def test_build_discord_failure_payload_uses_airflow_context() -> None:
    payload = build_discord_failure_payload(
        {
            "task_instance": FakeTaskInstance(),
            "dag_run": SimpleNamespace(run_id="manual__test", conf={}),
            "exception": RuntimeError("schema mismatch"),
            "logical_date": "2026-07-27T05:30:00+09:00",
        }
    )

    embed = payload["embeds"][0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert payload["username"] == "BrandMate Airflow"
    assert "Airflow failure" in payload["content"]
    assert embed["title"] == "sns_trend processed validation failed"
    assert fields["dag_id"] == "sns_trend_processed_validation"
    assert fields["task_id"] == "validate_package"
    assert fields["run_id"] == "manual__test"
    assert fields["version"] == "v3"
    assert fields["source_type"] == "gcs"
    assert fields["source_gcs_prefix"].endswith(
        "/v3/cross_platform_signal_top_candidates/"
    )
    assert fields["exception"] == "schema mismatch"
    assert fields["log_url"] == "http://localhost:8080/log"


def test_notify_airflow_failure_skips_when_alerts_disabled() -> None:
    result = notify_airflow_failure(
        {"task_instance": FakeTaskInstance()},
        env={"BRANDMATE_AIRFLOW_ALERTS_ENABLED": "false"},
    )

    assert result == {"status": "skipped", "reason": "alerts disabled"}


def test_notify_airflow_failure_skips_when_webhook_missing() -> None:
    result = notify_airflow_failure(
        {"task_instance": FakeTaskInstance()},
        env={"BRANDMATE_AIRFLOW_ALERTS_ENABLED": "true"},
    )

    assert result == {"status": "skipped", "reason": "discord webhook url missing"}


def test_notify_airflow_failure_posts_when_enabled() -> None:
    calls: list[dict[str, Any]] = []

    def fake_post_json(
        webhook_url: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        calls.append(
            {
                "webhook_url": webhook_url,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"status": "sent", "http_status": 204}

    result = notify_airflow_failure(
        {
            "task_instance": FakeTaskInstance(),
            "dag_run": SimpleNamespace(run_id="manual__test", conf={}),
            "exception": ValueError("bad payload"),
        },
        env={
            "BRANDMATE_AIRFLOW_ALERTS_ENABLED": "true",
            "BRANDMATE_AIRFLOW_DISCORD_WEBHOOK_URL": "https://discord.example/webhook",
            "BRANDMATE_AIRFLOW_ALERT_TIMEOUT_SECONDS": "3",
        },
        post_json=fake_post_json,
    )

    assert result == {"status": "sent", "http_status": 204}
    assert calls[0]["webhook_url"] == "https://discord.example/webhook"
    assert calls[0]["timeout_seconds"] == 3
    assert calls[0]["payload"]["embeds"][0]["fields"][1]["value"] == "validate_package"
