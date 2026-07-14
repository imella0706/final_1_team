# 로컬에서 비전 평가를 간편하게 실행하기 위해 만든 자동화 파일 
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$PROJECT_ROOT/apps/api"
LOG_DIR="${BRANDMATE_SERVICE_LOG_DIR:-$PROJECT_ROOT/outputs/brandmate_services}"
COMFYUI_DIR="${COMFYUI_DIR:-$HOME/personal/ComfyUI}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
API_ENV="${API_ENV:-ssakda}"
COMFYUI_ENV="${COMFYUI_ENV:-comfyui}"
VISION_EVAL_SKIP_CLIP="${VISION_EVAL_SKIP_CLIP:-1}"

mkdir -p "$LOG_DIR"

is_ready() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
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
      return 1
    fi

    sleep 2
  done
}

ensure_ollama() {
  if is_ready "$OLLAMA_URL/v1/models"; then
    echo "[ok] Ollama already running"
    return 0
  fi

  echo "[start] Ollama: $OLLAMA_URL"
  # [Design Intent] 로컬 평가 편의용 wrapper에서만 Ollama를 백그라운드로 띄운다.
  # 평가 runner 본체는 서버 생명주기를 관리하지 않고 preflight만 담당한다.
  nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
  wait_until_ready "Ollama" "$OLLAMA_URL/v1/models" 90
}

ensure_comfyui() {
  if is_ready "$COMFYUI_URL/system_stats"; then
    echo "[ok] ComfyUI already running"
    return 0
  fi

  if [[ ! -d "$COMFYUI_DIR" ]]; then
    echo "[error] ComfyUI directory not found: $COMFYUI_DIR" >&2
    echo "Set COMFYUI_DIR=/path/to/ComfyUI and retry." >&2
    return 1
  fi

  echo "[start] ComfyUI: $COMFYUI_URL"
  # [Design Intent] RTX 3060 12GB 로컬 실험에서는 FLUX가 VRAM을 많이 사용하므로
  # 기본적으로 --lowvram을 켜서 평가 중 OOM 가능성을 낮춘다.
  (
    cd "$COMFYUI_DIR"
    conda run -n "$COMFYUI_ENV" python main.py --listen 127.0.0.1 --port 8188 --lowvram
  ) >"$LOG_DIR/comfyui.log" 2>&1 &

  wait_until_ready "ComfyUI" "$COMFYUI_URL/system_stats" 180
}

run_eval() {
  local default_args=(
    --case-limit 1
    --repeats 1
    --concurrency 1
    --image-models black-forest-labs/FLUX.1-schnell
    --image-width 512
    --image-height 640
    --num-inference-steps 16
  )
  if [[ "$VISION_EVAL_SKIP_CLIP" == "1" ]]; then
    default_args+=(--skip-clip)
  fi

  cd "$API_DIR"

  if [[ "$#" -gt 0 ]]; then
    echo "[run] evaluate_vision_models.py ${default_args[*]} $*"
    conda run -n "$API_ENV" python -m scripts.evaluate_vision_models "${default_args[@]}" "$@"
  else
    echo "[run] evaluate_vision_models.py ${default_args[*]}"
    conda run -n "$API_ENV" python -m scripts.evaluate_vision_models "${default_args[@]}"
  fi
}

ensure_ollama
ensure_comfyui
run_eval "$@"
