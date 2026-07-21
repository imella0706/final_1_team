#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$PROJECT_ROOT/apps/api"
WEB_DIR="$PROJECT_ROOT/apps/web"
DASHBOARD_DIR="$PROJECT_ROOT/apps/visitor_flow_l2_dashboard"
API_COMPOSE_FILE="$PROJECT_ROOT/docker-compose.api.yml"

if [[ -d "$HOME/ComfyUI" ]]; then
  DEFAULT_COMFYUI_DIR="$HOME/ComfyUI"
else
  DEFAULT_COMFYUI_DIR="$HOME/personal/ComfyUI"
fi

COMFYUI_DIR="${COMFYUI_DIR:-$DEFAULT_COMFYUI_DIR}"
API_ENV="${API_ENV:-ssakda}"
COMFYUI_ENV="${COMFYUI_ENV:-comfyui}"
CONDA_BIN="${CONDA_EXE:-conda}"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-7660}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-5501}"
if [[ -n "${BRANDMATE_POSTGRES_PORT:-}" ]]; then
  POSTGRES_PORT="$BRANDMATE_POSTGRES_PORT"
elif grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  POSTGRES_PORT="55432"
else
  POSTGRES_PORT="5433"
fi
export BRANDMATE_POSTGRES_PORT="$POSTGRES_PORT"
if [[ "$POSTGRES_PORT" != "5433" && -z "${BRANDMATE_DATABASE_URL:-}" ]]; then
  export BRANDMATE_DATABASE_URL="postgresql+asyncpg://brandmate:brandmate-local-only@127.0.0.1:${POSTGRES_PORT}/brandmate"
fi
DASHBOARD_HOST="${DASHBOARD_HOST:-127.0.0.1}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8503}"
COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
RUN_DB_MIGRATIONS="${RUN_DB_MIGRATIONS:-true}"
START_COMFYUI="${START_COMFYUI:-auto}"
START_DASHBOARD="${START_DASHBOARD:-false}"

API_URL="http://127.0.0.1:${API_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"
DASHBOARD_URL="http://127.0.0.1:${DASHBOARD_PORT}"
COMFYUI_URL="http://127.0.0.1:${COMFYUI_PORT}"

LOG_DIR="${BRANDMATE_SERVICE_LOG_DIR:-$PROJECT_ROOT/outputs/brandmate_services}"
PID_DIR="$LOG_DIR/pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

usage() {
  cat <<'USAGE'
Usage:
  scripts/manage_brandmate_services_gcp.sh             Start Postgres, migrations, FastAPI, frontend, and ComfyUI when available.
  scripts/manage_brandmate_services_gcp.sh serve       Start Postgres, migrations, FastAPI, frontend, and ComfyUI when available.
  scripts/manage_brandmate_services_gcp.sh status      Check service readiness.
  scripts/manage_brandmate_services_gcp.sh logs        Tail service logs.
  scripts/manage_brandmate_services_gcp.sh stop        Stop processes started by this script.
  scripts/manage_brandmate_services_gcp.sh restart     Stop once, then start services once.
  scripts/manage_brandmate_services_gcp.sh qa [args]   Start services, then run run_local_vision_eval.sh.

Environment overrides:
  API_ENV=ssakda
  COMFYUI_ENV=comfyui
  COMFYUI_DIR=$HOME/ComfyUI
  API_PORT=7660
  WEB_PORT=5501
  DASHBOARD_PORT=8503
  COMFYUI_PORT=8188
  RUN_DB_MIGRATIONS=true
  START_COMFYUI=auto      # auto | true | false
  START_DASHBOARD=false   # true | false. Keep false while visitor-flow Streamlit is under development.
  BRANDMATE_SERVICE_LOG_DIR=outputs/brandmate_services
USAGE
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "[error] command not found: $command_name" >&2
    exit 1
  fi
}

is_ready() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

require_docker_compose() {
  require_command docker
  if ! docker compose version >/dev/null 2>&1; then
    echo "[error] docker compose plugin not available" >&2
    exit 1
  fi
}

wait_until_ready() {
  local name="$1"
  local url="$2"
  local timeout_seconds="${3:-120}"
  local started_at
  started_at="$(date +%s)"

  while true; do
    if is_ready "$url"; then
      echo "[ok] $name ready: $url"
      return 0
    fi

    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      echo "[error] $name not ready after ${timeout_seconds}s: $url" >&2
      echo "[hint] check log: $LOG_DIR/${name}.log" >&2
      return 1
    fi

    sleep 2
  done
}

start_process() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local work_dir="$4"
  shift 4

  if [[ -f "$pid_file" ]]; then
    local existing_pid
    existing_pid="$(cat "$pid_file")"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" >/dev/null 2>&1; then
      echo "[ok] $name already started by this script: pid=$existing_pid"
      return 0
    fi
  fi

  echo "[start] $name"
  (
    cd "$work_dir"
    # [Design Intent] Keep service logs durable outside the terminal session so
    # local and GCP smoke tests can be diagnosed after the shell is closed.
    # Start each managed service in its own process group so `conda run`
    # wrapper processes and their child Python servers can be stopped together.
    nohup setsid "$@" >"$log_file" 2>&1 &
    echo "$!" >"$pid_file"
  )
  echo "[log] $name: $log_file"
}

ensure_comfyui() {
  if [[ "$START_COMFYUI" == "false" ]]; then
    echo "[skip] ComfyUI disabled: START_COMFYUI=$START_COMFYUI"
    return 0
  fi

  if is_ready "$COMFYUI_URL/system_stats"; then
    echo "[ok] ComfyUI already running: $COMFYUI_URL"
    return 0
  fi

  if [[ ! -d "$COMFYUI_DIR" ]]; then
    if [[ "$START_COMFYUI" == "true" ]]; then
      echo "[error] ComfyUI directory not found: $COMFYUI_DIR" >&2
      echo "Set COMFYUI_DIR=/path/to/ComfyUI, or use START_COMFYUI=auto/false." >&2
      exit 1
    fi

    echo "[skip] ComfyUI not installed: $COMFYUI_DIR"
    echo "[info] FLUX image generation will be unavailable in this environment."
    return 0
  fi

  start_process \
    comfyui \
    "$PID_DIR/comfyui.pid" \
    "$LOG_DIR/comfyui.log" \
    "$COMFYUI_DIR" \
    "$CONDA_BIN" run -n "$COMFYUI_ENV" python main.py \
      --listen "$COMFYUI_HOST" \
      --port "$COMFYUI_PORT" \
      --lowvram

  wait_until_ready comfyui "$COMFYUI_URL/system_stats" 180
}

ensure_postgres() {
  require_docker_compose

  echo "[start] postgres container"
  docker compose -f "$API_COMPOSE_FILE" up -d brandmate-postgres

  local started_at
  started_at="$(date +%s)"
  while true; do
    if docker compose -f "$API_COMPOSE_FILE" exec -T brandmate-postgres \
      pg_isready -U brandmate -d brandmate >/dev/null 2>&1; then
      echo "[ok] postgres ready: 127.0.0.1:$POSTGRES_PORT"
      return 0
    fi

    if (( "$(date +%s)" - started_at >= 60 )); then
      echo "[error] postgres not ready after 60s" >&2
      echo "[hint] check: docker compose -f $API_COMPOSE_FILE logs brandmate-postgres" >&2
      return 1
    fi

    sleep 2
  done
}

run_db_migrations() {
  if [[ "$RUN_DB_MIGRATIONS" != "true" ]]; then
    echo "[skip] DB migrations disabled: RUN_DB_MIGRATIONS=$RUN_DB_MIGRATIONS"
    return 0
  fi

  echo "[run] DB migrations: alembic upgrade head"
  (
    cd "$API_DIR"
    # [Design Intent] Local startup should be deterministic: the API must see
    # the auth/session tables expected by the current code before it accepts
    # login requests. Alembic upgrade head is idempotent when the schema is
    # already current.
    "$CONDA_BIN" run -n "$API_ENV" alembic upgrade head
  )
}

ensure_api() {
  if is_ready "$API_URL/health"; then
    echo "[ok] FastAPI already running: $API_URL"
    return 0
  fi

  start_process \
    fastapi \
    "$PID_DIR/fastapi.pid" \
    "$LOG_DIR/fastapi.log" \
    "$API_DIR" \
    "$CONDA_BIN" run -n "$API_ENV" python -m uvicorn app.main:app \
      --host "$API_HOST" \
      --port "$API_PORT" \
      --log-level debug \
      --access-log

  wait_until_ready fastapi "$API_URL/health" 60
}

ensure_frontend() {
  if is_ready "$WEB_URL/"; then
    echo "[ok] Frontend already running: $WEB_URL"
    return 0
  fi

  start_process \
    frontend \
    "$PID_DIR/frontend.pid" \
    "$LOG_DIR/frontend.log" \
    "$WEB_DIR" \
    "$CONDA_BIN" run -n "$API_ENV" python -m http.server "$WEB_PORT" \
      --bind "$WEB_HOST"

  wait_until_ready frontend "$WEB_URL/" 30
}

ensure_dashboard() {
  if [[ "$START_DASHBOARD" == "false" ]]; then
    echo "[skip] Visitor-flow dashboard disabled: START_DASHBOARD=$START_DASHBOARD"
    return 0
  fi

  if is_ready "$DASHBOARD_URL/"; then
    echo "[ok] Visitor-flow dashboard already running: $DASHBOARD_URL"
    return 0
  fi

  if [[ ! -f "$DASHBOARD_DIR/app.py" ]]; then
    if [[ "$START_DASHBOARD" == "true" ]]; then
      echo "[error] Visitor-flow dashboard app not found: $DASHBOARD_DIR/app.py" >&2
      exit 1
    fi

    echo "[skip] Visitor-flow dashboard app not found: $DASHBOARD_DIR/app.py"
    return 0
  fi

  if ! "$CONDA_BIN" run -n "$API_ENV" python -c "import streamlit" >/dev/null 2>&1; then
    if [[ "$START_DASHBOARD" == "true" ]]; then
      echo "[error] Streamlit is not importable in conda env: $API_ENV" >&2
      echo "Install dashboard requirements, or omit START_DASHBOARD while the dashboard is under development." >&2
      exit 1
    fi

    echo "[skip] Streamlit is not available in conda env: $API_ENV"
    echo "[info] CCTV visitor-flow dashboard will be unavailable in this environment."
    return 0
  fi

  start_process \
    visitor_flow_dashboard \
    "$PID_DIR/visitor_flow_dashboard.pid" \
    "$LOG_DIR/visitor_flow_dashboard.log" \
    "$PROJECT_ROOT" \
    "$CONDA_BIN" run -n "$API_ENV" python -m streamlit run "$DASHBOARD_DIR/app.py" \
      --server.address "$DASHBOARD_HOST" \
      --server.port "$DASHBOARD_PORT"

  wait_until_ready visitor_flow_dashboard "$DASHBOARD_URL/" 60
}

check_frontend_api_url() {
  local active_api_line
  active_api_line="$(grep -E '^[[:space:]]*const API_BASE_URL' "$WEB_DIR/app.js" || true)"
  if [[ -z "$active_api_line" ]]; then
    echo "[warn] API_BASE_URL not found in $WEB_DIR/app.js"
    return 0
  fi
  echo "[info] frontend API config: $active_api_line"
}

serve() {
  require_command curl
  require_command "$CONDA_BIN"

  # [Design Intent] ComfyUI is kept private on localhost while FastAPI and the
  # static frontend bind externally for browser access through the GCP firewall.
  # Postgres and migrations run first because auth/session endpoints depend on
  # the latest DB schema.
  ensure_postgres
  run_db_migrations
  ensure_comfyui
  ensure_api
  ensure_frontend
  ensure_dashboard
  check_frontend_api_url

  echo
  echo "[ready] BrandMate stack is running"
  echo "  Frontend local: $WEB_URL"
  echo "  FastAPI health: $API_URL/health"
  if is_ready "$DASHBOARD_URL/"; then
    echo "  Visitor-flow dashboard: $DASHBOARD_URL"
  else
    echo "  Visitor-flow dashboard: skipped"
  fi
  if is_ready "$COMFYUI_URL/system_stats"; then
    echo "  ComfyUI internal: $COMFYUI_URL"
  else
    echo "  ComfyUI internal: skipped"
  fi
  echo "  Logs: $LOG_DIR"
}

stop_one() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "[skip] $name pid file not found"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "[skip] $name is not running"
    rm -f "$pid_file"
    return 0
  fi

  echo "[stop] $name pid=$pid"
  if kill -- "-$pid" >/dev/null 2>&1; then
    :
  else
    kill "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
}

stop_stack() {
  stop_one visitor_flow_dashboard "$PID_DIR/visitor_flow_dashboard.pid"
  stop_one frontend "$PID_DIR/frontend.pid"
  stop_one fastapi "$PID_DIR/fastapi.pid"
  stop_one comfyui "$PID_DIR/comfyui.pid"
  echo "[info] postgres container is left running to preserve local auth data"
  echo "[hint] stop DB manually if needed: docker compose -f $API_COMPOSE_FILE stop brandmate-postgres"
}

status_one() {
  local name="$1"
  local url="$2"
  if is_ready "$url"; then
    echo "[ok] $name: $url"
  else
    echo "[down] $name: $url"
  fi
}

status_stack() {
  status_one frontend "$WEB_URL/"
  status_one fastapi "$API_URL/health"
  status_one visitor_flow_dashboard "$DASHBOARD_URL/"
  status_one comfyui "$COMFYUI_URL/system_stats"
  if docker compose -f "$API_COMPOSE_FILE" exec -T brandmate-postgres \
    pg_isready -U brandmate -d brandmate >/dev/null 2>&1; then
    echo "[ok] postgres: 127.0.0.1:$POSTGRES_PORT"
  else
    echo "[down] postgres: 127.0.0.1:$POSTGRES_PORT"
  fi
}

tail_logs() {
  touch "$LOG_DIR/fastapi.log" "$LOG_DIR/frontend.log" "$LOG_DIR/comfyui.log" "$LOG_DIR/visitor_flow_dashboard.log"
  tail -f "$LOG_DIR/fastapi.log" "$LOG_DIR/frontend.log" "$LOG_DIR/comfyui.log" "$LOG_DIR/visitor_flow_dashboard.log"
}

run_qa() {
  serve
  echo
  echo "[run] vision evaluation wrapper"
  COMFYUI_DIR="$COMFYUI_DIR" \
  COMFYUI_URL="$COMFYUI_URL" \
  API_ENV="$API_ENV" \
  COMFYUI_ENV="$COMFYUI_ENV" \
    "$PROJECT_ROOT/scripts/run_local_vision_eval.sh" "$@"
}

action="${1:-serve}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

case "$action" in
  serve)
    serve
    ;;
  status)
    status_stack
    ;;
  logs)
    tail_logs
    ;;
  stop)
    stop_stack
    ;;
  restart)
    stop_stack
    sleep 2
    serve
    ;;
  qa)
    run_qa "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "[error] unknown action: $action" >&2
    usage
    exit 1
    ;;
esac
