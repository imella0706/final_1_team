from __future__ import annotations

from contextlib import contextmanager
import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from uuid import uuid4


class DataFileError(RuntimeError):
    """Raised when a data file is missing, malformed, or cannot be written."""


@contextmanager
def atomic_output_path(path: Path, *, overwrite: bool = True) -> Iterator[Path]:
    path = Path(path)
    if path.exists() and not overwrite:
        raise DataFileError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        yield temporary
        if path.exists() and not overwrite:
            raise DataFileError(f"output already exists: {path}")
        os.replace(temporary, path)
    except OSError as exc:
        raise DataFileError(f"cannot write output: {path}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[dict[str, Any]],
    *,
    overwrite: bool = True,
) -> None:
    with atomic_output_path(path, overwrite=overwrite) as temporary:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)


def atomic_write_json(path: Path, value: Any, *, overwrite: bool = True) -> None:
    with atomic_output_path(path, overwrite=overwrite) as temporary:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def read_csv_rows(
    path: Path,
    *,
    required_fields: Iterable[str] = (),
) -> tuple[list[str], list[dict[str, str]]]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            missing = [field for field in required_fields if field not in fields]
            if missing:
                raise DataFileError(
                    f"missing columns in {path}: {', '.join(sorted(missing))}"
                )
            return fields, [dict(row) for row in reader]
    except FileNotFoundError as exc:
        raise DataFileError(f"input does not exist: {path}") from exc
    except (OSError, csv.Error) as exc:
        raise DataFileError(f"cannot read CSV: {path}") from exc

