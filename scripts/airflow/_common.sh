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

airflow_generate_env() {
  if [[ -f "${AIRFLOW_ENV_FILE_PATH}" ]]; then
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

airflow_env_value() {
  local key="$1"
  local fallback="$2"
  local value
  value="$(sed -n "s/^${key}=//p" "${AIRFLOW_ENV_FILE_PATH}" | tail -n 1)"
  echo "${value:-${fallback}}"
}
