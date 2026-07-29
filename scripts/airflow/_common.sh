#!/usr/bin/env bash

set -euo pipefail

AIRFLOW_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AIRFLOW_REPO_ROOT="$(cd -- "${AIRFLOW_SCRIPT_DIR}/../.." && pwd)"
AIRFLOW_COMPOSE_FILE="${AIRFLOW_REPO_ROOT}/docker-compose.airflow.yml"
AIRFLOW_ENV_FILE_PATH="${AIRFLOW_ENV_FILE:-${AIRFLOW_REPO_ROOT}/.env.airflow}"

airflow_require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command not found: ${command_name}" >&2
    exit 1
  fi
}

airflow_ensure_env_value() {
  local key="$1"
  local value="$2"

  if grep -q "^${key}=" "${AIRFLOW_ENV_FILE_PATH}" 2>/dev/null; then
    return
  fi

  printf '%s=%s\n' "${key}" "${value}" >>"${AIRFLOW_ENV_FILE_PATH}"
}

airflow_append_default_env_values() {
  local managed_keys=(
    "BRANDMATE_AIRFLOW_GCS_LOGS_PREFIX"
    "BRANDMATE_SNS_TREND_PROCESSED_GCS_ROOT"
    "BRANDMATE_SNS_TREND_VALIDATION_SCHEDULE"
    "BRANDMATE_SNS_TREND_SAME_VERSION_POLICY"
    "YOUTUBE_REGION_CODE"
    "YOUTUBE_TOTAL_VIDEOS"
    "YOUTUBE_PAGE_SIZE"
    "YOUTUBE_API_TIMEOUT"
    "YOUTUBE_API_RETRIES"
    "YOUTUBE_TOKENIZER"
    "YOUTUBE_TIMEZONE"
    "BRANDMATE_SNS_TREND_YOUTUBE_LANDING_SCHEDULE"
    "BRANDMATE_SNS_TREND_YOUTUBE_LANDING_LIMIT"
    "BRANDMATE_SNS_TREND_GOGUMAFARM_LANDING_SCHEDULE"
    "BRANDMATE_SNS_TREND_CAREET_LANDING_SCHEDULE"
    "BRANDMATE_AIRFLOW_ALERTS_ENABLED"
    "BRANDMATE_AIRFLOW_DISCORD_WEBHOOK_URL"
    "BRANDMATE_AIRFLOW_ALERT_TIMEOUT_SECONDS"
    "GOOGLE_CLOUD_PROJECT"
  )
  local key
  local has_missing="false"

  for key in "${managed_keys[@]}"; do
    if ! grep -q "^${key}=" "${AIRFLOW_ENV_FILE_PATH}" 2>/dev/null; then
      has_missing="true"
      break
    fi
  done

  if [[ "${has_missing}" == "true" ]]; then
    {
      echo
      echo "# [Design Intent] Non-secret Airflow defaults are appended when an"
      echo "# existing .env.airflow predates newer DAG features."
    } >>"${AIRFLOW_ENV_FILE_PATH}"
  fi

  airflow_ensure_env_value \
    "BRANDMATE_AIRFLOW_GCS_LOGS_PREFIX" \
    "gs://ssakda/projects/brandmate/logs/data_pipeline/airflow"
  airflow_ensure_env_value \
    "BRANDMATE_SNS_TREND_PROCESSED_GCS_ROOT" \
    "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
  airflow_ensure_env_value "BRANDMATE_SNS_TREND_VALIDATION_SCHEDULE" ""
  airflow_ensure_env_value "BRANDMATE_SNS_TREND_SAME_VERSION_POLICY" "skip"
  airflow_ensure_env_value "YOUTUBE_REGION_CODE" "KR"
  airflow_ensure_env_value "YOUTUBE_TOTAL_VIDEOS" "100"
  airflow_ensure_env_value "YOUTUBE_PAGE_SIZE" "50"
  airflow_ensure_env_value "YOUTUBE_API_TIMEOUT" "15"
  airflow_ensure_env_value "YOUTUBE_API_RETRIES" "3"
  airflow_ensure_env_value "YOUTUBE_TOKENIZER" "regex"
  airflow_ensure_env_value "YOUTUBE_TIMEZONE" "Asia/Seoul"
  airflow_ensure_env_value "BRANDMATE_SNS_TREND_YOUTUBE_LANDING_SCHEDULE" "10 20 * * 3"
  airflow_ensure_env_value "BRANDMATE_SNS_TREND_YOUTUBE_LANDING_LIMIT" "100"
  airflow_ensure_env_value "BRANDMATE_SNS_TREND_GOGUMAFARM_LANDING_SCHEDULE" "10 20 * * 3"
  airflow_ensure_env_value "BRANDMATE_SNS_TREND_CAREET_LANDING_SCHEDULE" "10 20 * * 3"
  airflow_ensure_env_value "BRANDMATE_AIRFLOW_ALERTS_ENABLED" "false"
  airflow_ensure_env_value "BRANDMATE_AIRFLOW_DISCORD_WEBHOOK_URL" ""
  airflow_ensure_env_value "BRANDMATE_AIRFLOW_ALERT_TIMEOUT_SECONDS" "5"
  airflow_ensure_env_value "GOOGLE_CLOUD_PROJECT" "ssakda"
}

airflow_generate_env() {
  if [[ -f "${AIRFLOW_ENV_FILE_PATH}" ]]; then
    airflow_append_default_env_values
    return
  fi

  airflow_require_command openssl

  # [Design Intent] Generate local-only credentials instead of encouraging the
  # tracked example passwords to become real development credentials.
  local env_tmp
  local fernet_key
  local admin_password
  local webserver_secret
  env_tmp="$(mktemp "${AIRFLOW_ENV_FILE_PATH}.tmp.XXXXXX")"
  fernet_key="$(openssl rand -base64 32 | tr '/+' '_-' | tr -d '\n')"
  admin_password="$(openssl rand -hex 24)"
  webserver_secret="$(openssl rand -hex 32)"

  umask 077
  {
    echo "AIRFLOW_UID=$(id -u)"
    echo "AIRFLOW_WEB_PORT=8080"
    echo
    echo "AIRFLOW_ADMIN_USERNAME=admin"
    echo "AIRFLOW_ADMIN_PASSWORD=${admin_password}"
    echo "AIRFLOW_ADMIN_EMAIL=admin@example.com"
    echo "AIRFLOW_ADMIN_FIRSTNAME=BrandMate"
    echo "AIRFLOW_ADMIN_LASTNAME=Admin"
    echo
    echo "AIRFLOW__CORE__FERNET_KEY=${fernet_key}"
    echo "AIRFLOW__WEBSERVER__SECRET_KEY=${webserver_secret}"
  } >"${env_tmp}"
  chmod 600 "${env_tmp}"
  mv "${env_tmp}" "${AIRFLOW_ENV_FILE_PATH}"
  airflow_append_default_env_values

  echo "generated private Airflow environment: ${AIRFLOW_ENV_FILE_PATH}"
}

airflow_require_env() {
  if [[ ! -f "${AIRFLOW_ENV_FILE_PATH}" ]]; then
    echo "Airflow environment not found: ${AIRFLOW_ENV_FILE_PATH}" >&2
    echo "run scripts/airflow/up.sh once to generate it" >&2
    exit 1
  fi
}

airflow_compose() {
  airflow_require_command docker
  docker compose \
    --env-file "${AIRFLOW_ENV_FILE_PATH}" \
    -f "${AIRFLOW_COMPOSE_FILE}" \
    "$@"
}

airflow_prepare_writable_dirs() {
  local airflow_uid
  airflow_uid="$(airflow_env_value AIRFLOW_UID "$(id -u)")"

  mkdir -p \
    "${AIRFLOW_REPO_ROOT}/airflow/gcs_data_cache" \
    "${AIRFLOW_REPO_ROOT}/airflow/logs" \
    "${AIRFLOW_REPO_ROOT}/airflow/mock_gcs"

  # [Design Intent] Writable bind mounts must match the non-root Airflow UID.
  # Use a one-shot root container instead of requiring every developer to run
  # host-level sudo/chown commands.
  airflow_compose run \
    --rm \
    --no-deps \
    --user "0:0" \
    --entrypoint bash \
    airflow-init \
    -lc "chown -R ${airflow_uid}:0 /opt/airflow/gcs_data_cache /opt/airflow/logs /opt/airflow/mock_gcs && chmod -R ug+rwX /opt/airflow/gcs_data_cache /opt/airflow/logs /opt/airflow/mock_gcs"
}

airflow_env_value() {
  local key="$1"
  local fallback="$2"
  local value
  value="$(sed -n "s/^${key}=//p" "${AIRFLOW_ENV_FILE_PATH}" | tail -n 1)"
  echo "${value:-${fallback}}"
}
