#!/usr/bin/env bash
set -euo pipefail

BUCKET_URI="gs://ssakda"
PROJECT_PREFIX="projects/brandmate"
DVC_PREFIX="dvc/brandmate"
APPLY=0
SKIP_CHECK=0

usage() {
  cat <<'USAGE'
Usage:
  scripts/setup_gcs_layout.sh [--apply] [options]

Options:
  --apply                         Create GCS prefixes. Default is dry-run.
  --bucket gs://BUCKET_NAME        Target bucket. Default: gs://ssakda
  --project-prefix PREFIX          BrandMate project prefix. Default: projects/brandmate
  --dvc-prefix PREFIX              DVC remote prefix. Default: dvc/brandmate
  --skip-check                     Skip bucket access check.
  -h, --help                       Show this help.

Examples:
  scripts/setup_gcs_layout.sh
  scripts/setup_gcs_layout.sh --apply
  scripts/setup_gcs_layout.sh --apply --bucket gs://ssakda
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --bucket)
      BUCKET_URI="${2:?missing value for --bucket}"
      shift 2
      ;;
    --project-prefix)
      PROJECT_PREFIX="${2:?missing value for --project-prefix}"
      shift 2
      ;;
    --dvc-prefix)
      DVC_PREFIX="${2:?missing value for --dvc-prefix}"
      shift 2
      ;;
    --skip-check)
      SKIP_CHECK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[error] unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

BUCKET_URI="${BUCKET_URI%/}"
PROJECT_PREFIX="${PROJECT_PREFIX#/}"
PROJECT_PREFIX="${PROJECT_PREFIX%/}"
DVC_PREFIX="${DVC_PREFIX#/}"
DVC_PREFIX="${DVC_PREFIX%/}"

KEEP_FILE="$(mktemp)"
trap 'rm -f "$KEEP_FILE"' EXIT
printf "keep\n" > "$KEEP_FILE"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "[error] command not found: $command_name" >&2
    exit 1
  fi
}

gcs_cp_keep() {
  local target="$1"
  local uri="$BUCKET_URI/$target/.keep"

  if [[ "$APPLY" -eq 0 ]]; then
    echo "[dry-run] gcloud storage cp $KEEP_FILE $uri"
    return 0
  fi

  echo "[create] $uri"
  gcloud storage cp "$KEEP_FILE" "$uri" >/dev/null
}

project_path() {
  local suffix="$1"
  printf "%s/%s" "$PROJECT_PREFIX" "$suffix"
}

main() {
  require_command gcloud

  # [Design Intent] Default to dry-run so a teammate can review the exact GCS
  # prefixes before mutating the shared bucket.
  if [[ "$APPLY" -eq 0 ]]; then
    echo "[mode] dry-run. Re-run with --apply to create prefixes."
  else
    echo "[mode] apply. Creating prefixes in $BUCKET_URI"
  fi

  if [[ "$SKIP_CHECK" -eq 0 ]]; then
    echo "[check] bucket access: $BUCKET_URI"
    gcloud storage ls "$BUCKET_URI" >/dev/null
  fi

  # [Design Intent] Keep datasets isolated so license, quality, and
  # preprocessing issues can be traced back to the original dataset.
  gcs_cp_keep "$(project_path data/curated/aihub_food_image_text/v1)"
  gcs_cp_keep "$(project_path data/curated/sns/v1)"
  gcs_cp_keep "$(project_path data/curated/food_101/v1)"

  gcs_cp_keep "$(project_path data/processed/aihub_food_image_text/v1/food_description_data)"
  gcs_cp_keep "$(project_path data/processed/sns/v1)"
  gcs_cp_keep "$(project_path data/processed/food_101/v1)"
  gcs_cp_keep "$(project_path data/processed/merged/v1)"

  # [Design Intent] Evaluation splits are named by purpose: smoke catches broken
  # wiring fast, comparison supports model/prompt comparisons, final backs reports.
  gcs_cp_keep "$(project_path data/eval/smoke)"
  gcs_cp_keep "$(project_path data/eval/comparison)"
  gcs_cp_keep "$(project_path data/eval/final)"
  gcs_cp_keep "$(project_path data/eval/source_split/aihub_food_image_text)"
  gcs_cp_keep "$(project_path data/eval/source_split/sns)"
  gcs_cp_keep "$(project_path data/eval/source_split/food_101)"
  gcs_cp_keep "$(project_path data/manifests)"

  # [Design Intent] Model artifacts are managed separately from runtime enum
  # values; adding a model requires a manifest/config/workflow, not just code.
  gcs_cp_keep "$(project_path models/flux_schnell_gguf)"
  gcs_cp_keep "$(project_path models/sdxl)"

  # [Design Intent] Separate model evaluation artifacts from web-service user
  # generated outputs so experiments and product usage do not pollute each other.
  gcs_cp_keep "$(project_path outputs/evaluations/vision)"
  gcs_cp_keep "$(project_path outputs/web_service_generated)"

  # [Design Intent] Store compact success summaries and detailed failure logs in
  # different prefixes to control storage cost without losing debuggability.
  gcs_cp_keep "$(project_path logs/web_service/summary)"
  gcs_cp_keep "$(project_path logs/web_service/errors)"
  gcs_cp_keep "$(project_path logs/evaluations/summary)"
  gcs_cp_keep "$(project_path logs/evaluations/errors)"

  # [Design Intent] DVC owns this prefix as an object store. Humans should not
  # manually reorganize files under it.
  gcs_cp_keep "$DVC_PREFIX"

  echo "[done] layout command completed"
  echo "[verify] gcloud storage ls --recursive $BUCKET_URI/$PROJECT_PREFIX/"
  echo "[verify] gcloud storage ls $BUCKET_URI/$DVC_PREFIX/"
}

main
