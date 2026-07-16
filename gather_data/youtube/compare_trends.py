#!/usr/bin/env python
"""Compare two compatible YouTube keyword history snapshots."""

from __future__ import annotations

import argparse
from datetime import date
import logging
import os
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from youtube_trends.config import (
    DEFAULT_MIN_SUPPORT,
    DEFAULT_TOP_N,
    HISTORY_V2_DIR,
    REPORT_DIR,
    configure_console,
    configure_logging,
)
from youtube_trends.csv_io import DataFileError
from youtube_trends.trends import (
    TrendDataError,
    compare_snapshots,
    find_history_files,
    load_snapshot,
    render_comparison_chart,
    select_default_pair,
    write_comparison_csv,
)


HISTORY_DIR = HISTORY_V2_DIR
TOP_N = DEFAULT_TOP_N


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare the latest compatible YouTube keyword snapshots."
    )
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--old", type=Path, help="explicit old snapshot")
    parser.add_argument("--new", type=Path, help="explicit new snapshot")
    parser.add_argument("--top-n", type=int, default=TOP_N)
    parser.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=REPORT_DIR / "keyword_trend_comparison.csv",
    )
    parser.add_argument(
        "--output-plot",
        type=Path,
        default=REPORT_DIR / "keyword_trend_comparison.png",
    )
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--font-family")
    parser.add_argument(
        "--fail-if-exists",
        action="store_true",
        help="do not replace existing outputs",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def load_history() -> list[str]:
    """Compatibility wrapper returning all valid history paths."""
    return [str(path) for path in find_history_files(HISTORY_DIR)]


def compare(old_file: str | Path, new_file: str | Path) -> list[dict[str, object]]:
    """Compatibility wrapper that writes the historical default outputs."""
    old = load_snapshot(Path(old_file))
    new = load_snapshot(Path(new_file))
    rows = compare_snapshots(old, new)
    output_csv = REPORT_DIR / "keyword_trend_comparison.csv"
    output_plot = REPORT_DIR / "keyword_trend_comparison.png"
    _validate_paths(
        old.path,
        new.path,
        output_csv,
        output_plot,
        fail_if_exists=False,
    )
    _write_outputs(
        output_csv=output_csv,
        output_plot=output_plot,
        rows=rows,
        old_date=old.snapshot_date,
        new_date=new.snapshot_date,
        top_n=TOP_N,
        font_family=None,
    )
    return rows


def _print_top(rows: list[dict[str, object]], top_n: int) -> None:
    metric = "delta_pp" if rows[0]["comparison_mode"] == "prevalence_v2" else "change"
    rising = [row for row in rows if float(row[metric]) > 0]
    displayed = (rising or rows)[:top_n]
    print("keyword\told\tnew\tchange\tdelta_pp\tconfidence")
    for row in displayed:
        delta = row["delta_pp"]
        delta_text = f"{float(delta):.3f}" if delta != "" else "-"
        print(
            f"{row['keyword']}\t{row['old_count']}\t{row['new_count']}\t"
            f"{row['change']}\t{delta_text}\t{row['confidence']}"
        )


def _resolved(path: Path) -> Path:
    return path.resolve(strict=False)


def _validate_paths(
    old_path: Path,
    new_path: Path,
    output_csv: Path,
    output_plot: Path | None,
    *,
    fail_if_exists: bool,
) -> None:
    inputs = {_resolved(old_path), _resolved(new_path)}
    outputs = [_resolved(output_csv)]
    if output_plot is not None:
        outputs.append(_resolved(output_plot))
    if len(outputs) != len(set(outputs)):
        raise TrendDataError("comparison outputs must use different paths")
    if any(output in inputs for output in outputs):
        raise TrendDataError("comparison output must not replace a history input")
    if fail_if_exists:
        existing = [path for path in outputs if path.exists()]
        if existing:
            raise DataFileError(f"output already exists: {existing[0]}")


def _commit_staged_outputs(pairs: list[tuple[Path, Path]]) -> None:
    backups: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        for _staged, target in pairs:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = target.with_name(f".{target.name}.{uuid4().hex}.backup")
                os.replace(target, backup)
                backups.append((backup, target))
        for staged, target in pairs:
            os.replace(staged, target)
            committed.append(target)
    except BaseException as exc:
        for target in committed:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        for backup, target in reversed(backups):
            try:
                os.replace(backup, target)
            except OSError:
                pass
        if isinstance(exc, OSError):
            raise DataFileError("cannot commit comparison outputs") from exc
        raise
    else:
        for backup, _target in backups:
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                pass


def _write_outputs(
    *,
    output_csv: Path,
    output_plot: Path | None,
    rows: list[dict[str, object]],
    old_date: date,
    new_date: date,
    top_n: int,
    font_family: str | None,
) -> None:
    staged_csv = output_csv.with_name(f".{output_csv.name}.{uuid4().hex}.stage")
    staged_plot = (
        output_plot.with_name(f".{output_plot.name}.{uuid4().hex}.stage")
        if output_plot is not None
        else None
    )
    staged_files = [staged_csv] + ([staged_plot] if staged_plot is not None else [])
    try:
        write_comparison_csv(staged_csv, rows, overwrite=True)
        if staged_plot is not None:
            render_comparison_chart(
                staged_plot,
                rows,
                old_date=old_date,
                new_date=new_date,
                top_n=top_n,
                overwrite=True,
                font_family=font_family,
            )
        pairs = [(staged_csv, output_csv)]
        if staged_plot is not None and output_plot is not None:
            pairs.append((staged_plot, output_plot))
        _commit_staged_outputs(pairs)
    finally:
        for staged in staged_files:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    if bool(args.old) != bool(args.new):
        parser.error("--old and --new must be supplied together")
    if args.top_n < 1 or args.min_support < 1:
        parser.error("--top-n and --min-support must be at least 1")

    try:
        if args.old and args.new:
            old = load_snapshot(args.old)
            new = load_snapshot(args.new)
        else:
            old, new = select_default_pair(args.history_dir)
        output_plot = None if args.no_plot else args.output_plot
        _validate_paths(
            old.path,
            new.path,
            args.output_csv,
            output_plot,
            fail_if_exists=args.fail_if_exists,
        )
        rows = compare_snapshots(old, new, min_support=args.min_support)
        _write_outputs(
            output_csv=args.output_csv,
            output_plot=output_plot,
            rows=rows,
            old_date=old.snapshot_date,
            new_date=new.snapshot_date,
            top_n=args.top_n,
            font_family=args.font_family,
        )
    except (TrendDataError, DataFileError, OSError) as exc:
        logging.error("comparison failed: %s", exc)
        return 1

    print(
        f"comparison mode: {rows[0]['comparison_mode']} "
        f"({old.snapshot_date} -> {new.snapshot_date})"
    )
    _print_top(rows, args.top_n)
    print(f"saved comparison CSV to {args.output_csv}")
    if not args.no_plot:
        print(f"saved comparison plot to {args.output_plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
