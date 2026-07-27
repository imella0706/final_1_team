#!/usr/bin/env bash

set -euo pipefail

# [Design Intent] Stop containers and the project network while preserving the
# metadata DB and log volumes for run-history continuity.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

airflow_require_env
airflow_compose down
