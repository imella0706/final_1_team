#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] Keep routine diagnosis bounded to one service and the latest
# log lines; opt into streaming explicitly with a second --follow argument.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

airflow_require_env

airflow_service="${1:-airflow-scheduler}"
airflow_follow=()
if [[ "${2:-}" == "--follow" || "${2:-}" == "-f" ]]; then
  airflow_follow=(--follow)
fi

case "${airflow_service}" in
  airflow-postgres|airflow-init|airflow-webserver|airflow-scheduler)
    ;;
  *)
    echo "unknown Airflow service: ${airflow_service}" >&2
    exit 2
    ;;
esac

airflow_compose logs \
  --tail "${AIRFLOW_LOG_TAIL:-200}" \
  "${airflow_follow[@]}" \
  "${airflow_service}"
