from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable


class AlertError(RuntimeError):
    """Raised when an alert transport fails."""


PostJsonFunc = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _bool_env(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _stringify(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _truncate(value: Any, *, limit: int = 900) -> str:
    text = _stringify(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _attr(value: Any, name: str) -> Any:
    return getattr(value, name, None) if value is not None else None


def _pull_resolved_config(context: dict[str, Any]) -> dict[str, Any]:
    task_instance = context.get("task_instance") or context.get("ti")
    if task_instance is None or not hasattr(task_instance, "xcom_pull"):
        return {}

    try:
        config = task_instance.xcom_pull(task_ids="resolve_processed_package")
    except Exception:
        return {}
    return config if isinstance(config, dict) else {}


def build_discord_failure_payload(context: dict[str, Any]) -> dict[str, Any]:
    dag_run = context.get("dag_run")
    task_instance = context.get("task_instance") or context.get("ti")
    dag = context.get("dag")
    exception = context.get("exception")
    resolved_config = _pull_resolved_config(context)
    dag_conf = _attr(dag_run, "conf") or {}
    if not isinstance(dag_conf, dict):
        dag_conf = {}

    dag_id = _attr(task_instance, "dag_id") or _attr(dag, "dag_id")
    task_id = _attr(task_instance, "task_id")
    run_id = _attr(dag_run, "run_id") or _attr(task_instance, "run_id")
    log_url = _attr(task_instance, "log_url")
    try_number = _attr(task_instance, "try_number")
    logical_date = context.get("logical_date") or _attr(dag_run, "logical_date")

    version = (
        resolved_config.get("version")
        or dag_conf.get("version")
        or _attr(dag_run, "version")
    )
    source_gcs_prefix = (
        resolved_config.get("source_gcs_prefix")
        or dag_conf.get("source_gcs_prefix")
        or dag_conf.get("processed_gcs_prefix")
    )

    fields = [
        {"name": "dag_id", "value": _stringify(dag_id), "inline": True},
        {"name": "task_id", "value": _stringify(task_id), "inline": True},
        {"name": "run_id", "value": _truncate(run_id), "inline": False},
        {"name": "version", "value": _stringify(version), "inline": True},
        {
            "name": "source_type",
            "value": _stringify(resolved_config.get("source_type")),
            "inline": True,
        },
        {
            "name": "source_gcs_prefix",
            "value": _truncate(source_gcs_prefix),
            "inline": False,
        },
        {
            "name": "exception",
            "value": _truncate(exception),
            "inline": False,
        },
        {
            "name": "logical_date",
            "value": _stringify(logical_date),
            "inline": True,
        },
        {"name": "try_number", "value": _stringify(try_number), "inline": True},
    ]
    if log_url:
        fields.append({"name": "log_url", "value": _truncate(log_url), "inline": False})

    return {
        "username": "BrandMate Airflow",
        "content": f"Airflow failure: `{_stringify(dag_id)}` / `{_stringify(task_id)}`",
        "embeds": [
            {
                "title": "sns_trend processed validation failed",
                "description": (
                    "The Airflow validation gate failed. "
                    "Check task logs before re-running the DAG."
                ),
                "color": 15158332,
                "fields": fields,
            }
        ],
    }


def post_json_to_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "brandmate-airflow-alerts/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 0))
            if status_code >= 400:
                raise AlertError(f"Discord webhook returned HTTP {status_code}")
            return {"status": "sent", "http_status": status_code}
    except urllib.error.URLError as error:
        raise AlertError(f"Discord webhook request failed: {error}") from error


def notify_airflow_failure(
    context: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
    post_json: PostJsonFunc = post_json_to_webhook,
) -> dict[str, Any]:
    active_env = env or os.environ
    enabled = _bool_env(
        active_env.get("BRANDMATE_AIRFLOW_ALERTS_ENABLED"),
        default=False,
    )
    if not enabled:
        return {"status": "skipped", "reason": "alerts disabled"}

    webhook_url = active_env.get("BRANDMATE_AIRFLOW_DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return {"status": "skipped", "reason": "discord webhook url missing"}

    timeout_seconds = float(
        active_env.get("BRANDMATE_AIRFLOW_ALERT_TIMEOUT_SECONDS", "5")
    )
    payload = build_discord_failure_payload(context)

    try:
        return post_json(webhook_url, payload, timeout_seconds)
    except AlertError as error:
        # [Design Intent] Alert transport failure must not hide the original
        # Airflow task failure. Airflow will log this callback result.
        return {"status": "failed", "reason": str(error)}
