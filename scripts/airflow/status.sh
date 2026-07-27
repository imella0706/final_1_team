#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] Report container state and the user-facing web health endpoint
# together so "container is up" is not mistaken for "Airflow is usable."
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

airflow_require_env
airflow_require_command curl
airflow_compose ps airflow-postgres airflow-webserver airflow-scheduler

airflow_web_port="$(airflow_env_value AIRFLOW_WEB_PORT 8080)"
airflow_health_url="http://127.0.0.1:${airflow_web_port}/health"
if curl --fail --silent --show-error "${airflow_health_url}" >/dev/null; then
  echo "webserver health: healthy (${airflow_health_url})"
else
  echo "webserver health: unavailable (${airflow_health_url})" >&2
  exit 1
fi
