#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] Run Phase 4 Step 14 Landing Collection DAG Smoke on local Docker
# Airflow and GCP VM Docker Airflow with a single command. Verifies YouTube,
# Gogumafarm, and Careet landing collection, contract verification, and GCS upload tasks.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

airflow_require_env

sources=("youtube" "gogumafarm" "careet")
target_source="${1:-all}"

run_timestamp="$(date -u +%Y%m%dT%H%M%S)"
week="${AIRFLOW_LANDING_WEEK:-2026-W31}"
run_date="${AIRFLOW_LANDING_RUN_DATE:-2026-07-27}"
upload_gcs="${AIRFLOW_UPLOAD_GCS:-true}"

trigger_and_wait_dag() {
  local source_name="$1"
  local dag_id="sns_trend_${source_name}_landing_collection"
  local run_id="manual__${source_name}_phase4_14_smoke_${run_timestamp}"
  
  local conf
  conf="$(
    printf \
      '{"week":"%s","run_date":"%s","run_id":"%s","upload_gcs":%s}' \
      "${week}" \
      "${run_date}" \
      "${run_id}" \
      "${upload_gcs}"
  )"

  echo "========================================================"
  echo "Triggering Landing DAG: ${dag_id}"
  echo "run_id=${run_id}"
  echo "week=${week}, run_date=${run_date}, upload_gcs=${upload_gcs}"
  echo "========================================================"

  airflow_compose exec -T airflow-scheduler \
    airflow dags trigger "${dag_id}" \
    --run-id "${run_id}" \
    --conf "${conf}"

  for _ in {1..60}; do
    state="$(
      airflow_compose exec -T airflow-scheduler \
        airflow dags list-runs -d "${dag_id}" --no-backfill -o plain \
        | awk -v run_id="${run_id}" '$2 == run_id {print $3; exit}'
    )"

    case "${state}" in
      success)
        echo "SUCCESS: ${dag_id} (${run_id})"
        airflow_compose exec -T airflow-scheduler \
          airflow tasks states-for-dag-run "${dag_id}" "${run_id}"
        return 0
        ;;
      failed)
        echo "FAILED: ${dag_id} (${run_id})" >&2
        airflow_compose exec -T airflow-scheduler \
          airflow tasks states-for-dag-run "${dag_id}" "${run_id}" >&2
        return 1
        ;;
      queued|running|scheduled|"")
        sleep 3
        ;;
      *)
        echo "DAG run state=${state}; waiting: ${run_id}"
        sleep 3
        ;;
    esac
  done

  echo "TIMEOUT: ${dag_id} (${run_id})" >&2
  airflow_compose exec -T airflow-scheduler \
    airflow tasks states-for-dag-run "${dag_id}" "${run_id}" >&2
  return 1
}

if [[ "${target_source}" == "all" ]]; then
  for src in "${sources[@]}"; do
    trigger_and_wait_dag "${src}"
  done
else
  trigger_and_wait_dag "${target_source}"
fi

echo "========================================================"
echo "Phase 4 Step 14 Landing DAG Smoke Triggering Completed Successfully"
echo "========================================================"
