#!/usr/bin/env bash
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${BRANDMATE_COSYVOICE_HOME:-${HOME}/.local/share/brandmate-cosyvoice}"
export COSYVOICE_REPO_DIR="${COSYVOICE_REPO_DIR:-${INSTALL_ROOT}/runtime/CosyVoice}"
export COSYVOICE_MODEL_DIR="${COSYVOICE_MODEL_DIR:-pretrained_models/Fun-CosyVoice3-0.5B}"
export COSYVOICE_MODEL_NAME="${COSYVOICE_MODEL_NAME:-Fun-CosyVoice3-0.5B-2512}"
export COSYVOICE_VOICE_DIR="${COSYVOICE_VOICE_DIR:-${SERVICE_DIR}/voices}"
export COSYVOICE_INFERENCE_MODE="${COSYVOICE_INFERENCE_MODE:-cross_lingual}"

if [[ ! -x "${INSTALL_ROOT}/venv/bin/uvicorn" ]]; then
  echo "CosyVoice is not installed. Run: bash ${SERVICE_DIR}/setup.sh"
  exit 1
fi

cd "${SERVICE_DIR}"
exec "${INSTALL_ROOT}/venv/bin/uvicorn" server:app --host 0.0.0.0 --port 50000
