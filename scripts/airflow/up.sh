#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] One command builds the pinned image, runs idempotent metadata
# initialization, and waits until the web UI is actually ready.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

airflow_generate_env
airflow_require_command curl
airflow_compose build airflow-init
airflow_prepare_writable_dirs
airflow_compose up -d --no-build

airflow_web_port="$(airflow_env_value AIRFLOW_WEB_PORT 8080)"
airflow_health_url="http://127.0.0.1:${airflow_web_port}/health"

for attempt in {1..30}; do
  if curl --fail --silent --show-error "${airflow_health_url}" >/dev/null 2>&1; then
    echo "Airflow webserver is healthy: http://127.0.0.1:${airflow_web_port}"
    echo "[auto] Unpausing core SNS trend collection & validation DAGs..."
    for dag in sns_trend_youtube_landing_collection sns_trend_gogumafarm_landing_collection sns_trend_careet_landing_collection sns_trend_processed_validation; do
      airflow_compose exec -T airflow-scheduler airflow dags unpause "$dag" >/dev/null 2>&1 || true
    done
    airflow_compose ps airflow-postgres airflow-webserver airflow-scheduler
    exit 0
  fi
  sleep 2
done

echo "Airflow webserver did not become healthy: ${airflow_health_url}" >&2
airflow_compose ps airflow-postgres airflow-webserver airflow-scheduler
exit 1
