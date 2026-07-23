"""Per-batch state manager for resume support.

Each batch size (10 / 50 / 100) has its own state.json file under:
    <output_dir>/batch_<N>/state.json

State is stored as a JSON object keyed by final_image_id:
    {
      "<image_id>": {
        "status": "success" | "failed" | "skipped",
        "prompt_hash": "<sha256>",
        "result_path": "<relative path>",
        "attempts": <int>,
        "error": "<str or null>",
        "processed_at": "<ISO timestamp>"
      },
      ...
    }

Rules:
- Only "success" entries are skipped on resume.
- "failed" entries are retried on the next run.
- State file is never shared between batch sizes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StateManager:
    """Read/write the state.json file for a single batch."""

    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._state: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_done(self, image_id: str) -> bool:
        """Return True if this image_id already completed successfully."""
        entry = self._state.get(image_id, {})
        return entry.get("status") == self.STATUS_SUCCESS

    def mark_success(
        self,
        image_id: str,
        prompt_hash: str,
        result_path: str,
        attempts: int,
    ) -> None:
        self._state[image_id] = {
            "status": self.STATUS_SUCCESS,
            "prompt_hash": prompt_hash,
            "result_path": result_path,
            "attempts": attempts,
            "error": None,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        self._save()

    def mark_failed(
        self,
        image_id: str,
        prompt_hash: str,
        attempts: int,
        error: str,
    ) -> None:
        self._state[image_id] = {
            "status": self.STATUS_FAILED,
            "prompt_hash": prompt_hash,
            "result_path": None,
            "attempts": attempts,
            "error": error,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        self._save()

    def mark_skipped(self, image_id: str, reason: str) -> None:
        self._state[image_id] = {
            "status": self.STATUS_SKIPPED,
            "prompt_hash": None,
            "result_path": None,
            "attempts": 0,
            "error": reason,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        self._save()

    def get_entry(self, image_id: str) -> dict[str, Any] | None:
        return self._state.get(image_id)

    def all_entries(self) -> dict[str, dict[str, Any]]:
        return dict(self._state)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {
            self.STATUS_SUCCESS: 0,
            self.STATUS_FAILED: 0,
            self.STATUS_SKIPPED: 0,
        }
        for entry in self._state.values():
            status = entry.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        return counts
