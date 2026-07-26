#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] Run the same GCS processed validation smoke on local Docker
# Airflow and VM Docker Airflow without hand-copying Airflow UI JSON config.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

airflow_require_env

dag_id="sns_trend_processed_validation"
version="${AIRFLOW_SNS_TREND_VERSION:-v2}"
source_gcs_prefix="${AIRFLOW_SNS_TREND_GCS_PREFIX:-gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/}"
write_gcs_summary="${AIRFLOW_WRITE_GCS_SUMMARY:-true}"
run_label="${AIRFLOW_RUN_LABEL:-phase2_5_smoke}"
run_timestamp="$(date -u +%Y%m%dT%H%M%S)"
run_id="manual__sns_trend_${version}_gcs_${run_label}_${run_timestamp}"

case "${write_gcs_summary}" in
  true|false)
    ;;
  *)
    echo "AIRFLOW_WRITE_GCS_SUMMARY must be true or false: ${write_gcs_summary}" >&2
    exit 2
    ;;
esac

conf="$(
  printf \
    '{"version":"%s","source_gcs_prefix":"%s","write_gcs_summary":%s}' \
    "${version}" \
    "${source_gcs_prefix}" \
    "${write_gcs_summary}"
)"

echo "triggering ${dag_id}"
echo "run_id=${run_id}"
echo "source_gcs_prefix=${source_gcs_prefix}"
echo "write_gcs_summary=${write_gcs_summary}"

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
      echo "DAG run succeeded: ${run_id}"
      airflow_compose exec -T airflow-scheduler \
        airflow tasks states-for-dag-run "${dag_id}" "${run_id}"
      exit 0
      ;;
    failed)
      echo "DAG run failed: ${run_id}" >&2
      airflow_compose exec -T airflow-scheduler \
        airflow tasks states-for-dag-run "${dag_id}" "${run_id}" >&2
      exit 1
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

echo "DAG run did not finish within timeout: ${run_id}" >&2
airflow_compose exec -T airflow-scheduler \
  airflow tasks states-for-dag-run "${dag_id}" "${run_id}" >&2
exit 1
