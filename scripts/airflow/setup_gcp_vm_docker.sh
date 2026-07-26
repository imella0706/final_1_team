#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] Prepare a GCP VM for Docker Compose based Airflow smoke tests
# with a repeatable command instead of manual SSH package installation.

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This bootstrap script supports Linux VMs only." >&2
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required to install Docker packages." >&2
  exit 1
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
else
  echo "/etc/os-release not found; cannot detect OS." >&2
  exit 1
fi

case "${ID:-}" in
  ubuntu|debian)
    ;;
  *)
    echo "Unsupported OS for this bootstrap script: ${ID:-unknown}" >&2
    echo "Install Docker Engine and docker compose plugin manually, then rerun Airflow scripts." >&2
    exit 1
    ;;
esac

install_docker=false
if ! command -v docker >/dev/null 2>&1; then
  install_docker=true
elif ! docker compose version >/dev/null 2>&1; then
  install_docker=true
fi

if [[ "${install_docker}" == "true" ]]; then
  echo "[install] docker.io and docker-compose-plugin"
  sudo apt-get update
  sudo apt-get install -y docker.io docker-compose-plugin
else
  echo "[ok] Docker and docker compose plugin already installed"
fi

echo "[enable] docker service"
sudo systemctl enable --now docker

if ! getent group docker >/dev/null; then
  echo "[create] docker group"
  sudo groupadd docker
fi

if id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  echo "[ok] user already in docker group: ${USER}"
else
  echo "[grant] add user to docker group: ${USER}"
  sudo usermod -aG docker "$USER"
  echo
  echo "Docker group membership was updated."
  echo "Log out and reconnect to this VM before running Docker without sudo."
fi

echo
echo "[version]"
docker --version || true
docker compose version || true

echo
echo "[next]"
echo "After reconnecting if group membership changed:"
echo "  cd ~/final_1_team"
echo "  ./scripts/airflow/up.sh"
echo "  ./scripts/airflow/trigger_sns_trend_gcs_validation.sh"
