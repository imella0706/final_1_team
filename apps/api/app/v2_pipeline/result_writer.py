"""Result writer for the v2 pipeline.

Saves per-image results to the batch output directory.
Original data files and images are never modified.

Output per image:
    <output_dir>/results/<image_id>.json

Manifest written at run end:
    <output_dir>/manifests/<run_timestamp>.json
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ResultWriter:
    """Write per-image result JSON files and the run manifest."""

    def __init__(self, output_dir: Path) -> None:
        self._results_dir = output_dir / "results"
        self._manifests_dir = output_dir / "manifests"
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir.mkdir(parents=True, exist_ok=True)

    @property
    def results_dir(self) -> Path:
        return self._results_dir

    def result_path(self, image_id: str) -> Path:
        return self._results_dir / f"{image_id}.json"

    def write_result(
        self,
        image_id: str,
        prompt_hash: str,
        image_path: str,
        prompt_keywords: str,
        status: str,
        attempts: int,
        error: str | None,
        model_response: dict[str, Any] | None,
    ) -> Path:
        """Write a single result JSON for one image.

        The prompt_keywords value is stored only as a SHA-256 hash in the
        result (not the full text) to avoid redundant storage.
        The full prompt text is never repeated here.
        """
        record: dict[str, Any] = {
            "image_id": image_id,
            "image_path": image_path,
            "prompt_hash": prompt_hash,    # integrity reference, not the text
            "status": status,
            "attempts": attempts,
            "error": error,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        if model_response is not None:
            # Strip image_base64 to keep results compact
            response_copy = dict(model_response)
            image_section = response_copy.get("image")
            if isinstance(image_section, dict) and "image_base64" in image_section:
                image_section = dict(image_section)
                image_section["image_base64"] = "[saved_separately]"
                response_copy["image"] = image_section
            record["model_response"] = response_copy

        out = self.result_path(image_id)
        out.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def write_manifest(
        self,
        batch_size: int,
        run_start: datetime,
        run_end: datetime,
        records_summary: list[dict[str, Any]],
    ) -> Path:
        """Write a run-level manifest JSON."""
        timestamp = run_start.strftime("%Y%m%d-%H%M%S")
        manifest: dict[str, Any] = {
            "batch_size": batch_size,
            "run_start": run_start.isoformat(),
            "run_end": run_end.isoformat(),
            "duration_seconds": round((run_end - run_start).total_seconds(), 2),
            "total": len(records_summary),
            "success": sum(1 for r in records_summary if r["status"] == "success"),
            "failed": sum(1 for r in records_summary if r["status"] == "failed"),
            "skipped": sum(1 for r in records_summary if r["status"] == "skipped"),
            "records": records_summary,
        }
        out = self._manifests_dir / f"run_{timestamp}.json"
        out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
