#!/usr/bin/env bash
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${BRANDMATE_COSYVOICE_HOME:-${HOME}/.local/share/brandmate-cosyvoice}"
RUNTIME_DIR="${INSTALL_ROOT}/runtime"
COSYVOICE_REPO="${RUNTIME_DIR}/CosyVoice"
VENV_DIR="${INSTALL_ROOT}/venv"
MODEL_DIR="${COSYVOICE_REPO}/pretrained_models/Fun-CosyVoice3-0.5B"

command -v python3.10 >/dev/null || {
  echo "python3.10 is required. Use Ubuntu 22.04 or a Python 3.10 environment."
  exit 1
}
command -v git >/dev/null || { echo "git is required."; exit 1; }
command -v sox >/dev/null || {
  echo "sox is required. Run: sudo apt update && sudo apt install -y sox libsox-dev"
  exit 1
}
python3.10 -c 'import venv' >/dev/null 2>&1 || {
  echo "python3.10-venv is required. Run: sudo apt install -y python3.10-venv"
  exit 1
}

mkdir -p "${RUNTIME_DIR}" "${SERVICE_DIR}/voices"
if [[ ! -d "${COSYVOICE_REPO}/.git" ]]; then
  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "${COSYVOICE_REPO}"
else
  git -C "${COSYVOICE_REPO}" submodule update --init --recursive
fi

python3.10 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${COSYVOICE_REPO}/requirements.txt"
"${VENV_DIR}/bin/pip" install -r "${SERVICE_DIR}/requirements-server.txt"
MODEL_DIR="${MODEL_DIR}" "${VENV_DIR}/bin/python" -c \
  'import os; from huggingface_hub import snapshot_download; snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512", local_dir=os.environ["MODEL_DIR"])'

echo "Installation complete."
echo "Add an authorized reference voice as ${SERVICE_DIR}/voices/default.wav."
echo "Then run: bash ${SERVICE_DIR}/start.sh"
