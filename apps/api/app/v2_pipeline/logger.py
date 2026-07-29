"""Structured run logger for the v2 pipeline.

Writes a JSONL (newline-delimited JSON) log file under:
    <output_dir>/logs/run_<timestamp>.jsonl

Each log entry is a JSON object on a single line.
API keys and authentication information are never logged.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunLogger:
    """Write structured log entries to a JSONL file and optionally stdout."""

    def __init__(self, log_dir: Path, batch_size: int, verbose: bool = True) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self._path = log_dir / f"run_{timestamp}.jsonl"
        self._batch_size = batch_size
        self._verbose = verbose
        self._fh = self._path.open("a", encoding="utf-8")

    @property
    def log_path(self) -> Path:
        return self._path

    def _write(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        self._fh.write(line + "\n")
        self._fh.flush()
        if self._verbose:
            print(line, file=sys.stdout)

    def log_run_start(self, input_dir: str, output_dir: str) -> None:
        self._write({
            "event": "run_start",
            "batch_size": self._batch_size,
            "input_dir": input_dir,
            "output_dir": output_dir,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_run_end(
        self,
        total: int,
        success: int,
        failed: int,
        skipped: int,
        duration_seconds: float,
    ) -> None:
        self._write({
            "event": "run_end",
            "batch_size": self._batch_size,
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "duration_seconds": duration_seconds,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_item_start(self, image_id: str, image_path: str, prompt_hash: str) -> None:
        self._write({
            "event": "item_start",
            "image_id": image_id,
            "image_path": image_path,
            "prompt_hash": prompt_hash,   # hash only, never the text
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_item_success(
        self,
        image_id: str,
        image_path: str,
        prompt_hash: str,
        attempts: int,
        result_path: str,
        latency_ms: int,
    ) -> None:
        self._write({
            "event": "item_success",
            "image_id": image_id,
            "image_path": image_path,
            "prompt_hash": prompt_hash,
            "attempts": attempts,
            "result_path": result_path,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_item_failed(
        self,
        image_id: str,
        image_path: str,
        prompt_hash: str,
        attempts: int,
        error: str,
    ) -> None:
        self._write({
            "event": "item_failed",
            "image_id": image_id,
            "image_path": image_path,
            "prompt_hash": prompt_hash,
            "attempts": attempts,
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_item_skipped(self, image_id: str, reason: str) -> None:
        self._write({
            "event": "item_skipped",
            "image_id": image_id,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_retry(self, image_id: str, attempt: int, error: str) -> None:
        self._write({
            "event": "item_retry",
            "image_id": image_id,
            "attempt": attempt,
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_validation(self, errors: int, warnings: int) -> None:
        self._write({
            "event": "validation_complete",
            "errors": errors,
            "warnings": warnings,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def log_dry_run_item(
        self,
        image_id: str,
        image_path: str,
        image_exists: bool,
        prompt_hash: str,
        expected_output: str,
    ) -> None:
        self._write({
            "event": "dry_run_item",
            "image_id": image_id,
            "image_path": image_path,
            "image_exists": image_exists,
            "prompt_hash": prompt_hash,
            "expected_output": expected_output,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def close(self) -> None:
        self._fh.close()
