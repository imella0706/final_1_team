from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import math
from pathlib import Path
import platform
import re
from typing import Iterable

from .csv_io import atomic_output_path, atomic_write_csv, read_csv_rows
from .keywords import KEYWORD_SCHEMA_VERSION, canonicalize_keyword


HISTORY_FILE_PATTERN = re.compile(r"^keywords_(\d{4}-\d{2}-\d{2})\.csv$")
COMPARISON_FIELDS = [
    "keyword",
    "old_count",
    "new_count",
    "change",
    "canonical_keyword",
    "old_prevalence",
    "new_prevalence",
    "prevalence_change",
    "delta_pp",
    "growth_rate",
    "current_support",
    "confidence",
    "trend_status",
    "comparison_mode",
    "old_date",
    "new_date",
    "region",
    "old_sample_size",
    "new_sample_size",
    "tokenizer_version",
    "normalizer_version",
    "alias_version",
    "stopword_version",
    "analysis_signature",
]


class TrendDataError(RuntimeError):
    """Raised when history files cannot be compared safely."""


@dataclass(frozen=True)
class Snapshot:
    path: Path
    schema_version: int
    snapshot_date: date
    region: str
    counts: dict[str, float]
    display_names: dict[str, str]
    prevalence: dict[str, float]
    sample_size: int | None
    tokenizer_version: str
    normalizer_version: str
    alias_version: str
    stopword_version: str
    analysis_signature: str


def _date_from_path(path: Path) -> date:
    match = HISTORY_FILE_PATTERN.fullmatch(path.name)
    if not match:
        raise TrendDataError(f"invalid history filename: {path.name}")
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise TrendDataError(f"invalid date in history filename: {path.name}") from exc


def find_history_files(history_dir: Path) -> list[Path]:
    directory = Path(history_dir)
    if not directory.exists():
        raise TrendDataError(f"history directory does not exist: {directory}")
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and HISTORY_FILE_PATTERN.fullmatch(path.name)
    ]
    return sorted(files, key=_date_from_path)


def _finite_nonnegative(value: object, *, field: str, path: Path) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise TrendDataError(f"{field} must be numeric in {path}") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise TrendDataError(f"{field} must be finite and nonnegative in {path}")
    return parsed


def _load_legacy_snapshot(path: Path, rows: list[dict[str, str]]) -> Snapshot:
    if not rows:
        raise TrendDataError(f"legacy history snapshot is empty: {path}")
    counts: dict[str, float] = {}
    display_names: dict[str, str] = {}
    for row in rows:
        display = str(row.get("keyword") or "").strip()
        canonical = canonicalize_keyword(display)
        if not canonical:
            raise TrendDataError(f"keyword must not be blank in {path}")
        counts[canonical] = counts.get(canonical, 0.0) + _finite_nonnegative(
            row.get("count"), field="count", path=path
        )
        display_names.setdefault(canonical, display)
    return Snapshot(
        path=path,
        schema_version=1,
        snapshot_date=_date_from_path(path),
        region="",
        counts=counts,
        display_names=display_names,
        prevalence={},
        sample_size=None,
        tokenizer_version="legacy",
        normalizer_version="legacy-canonicalized-on-read",
        alias_version="none",
        stopword_version="unknown",
        analysis_signature="legacy-v1-canonicalized",
    )


def _load_v2_snapshot(path: Path, rows: list[dict[str, str]]) -> Snapshot:
    if not rows:
        raise TrendDataError(f"history snapshot is empty: {path}")
    counts: dict[str, float] = {}
    display_names: dict[str, str] = {}
    prevalence: dict[str, float] = {}
    dates: set[str] = set()
    regions: set[str] = set()
    sample_sizes: set[int] = set()
    tokenizer_versions: set[str] = set()
    normalizer_versions: set[str] = set()
    alias_versions: set[str] = set()
    stopword_versions: set[str] = set()
    analysis_signatures: set[str] = set()

    for row in rows:
        if str(row.get("schema_version") or "") != str(KEYWORD_SCHEMA_VERSION):
            raise TrendDataError(f"mixed schema versions in {path}")
        canonical = canonicalize_keyword(row.get("canonical_keyword"))
        if not canonical or canonical in counts:
            raise TrendDataError(f"duplicate or blank canonical_keyword in {path}")
        display_keyword = str(row.get("display_keyword") or "").strip()
        if canonicalize_keyword(display_keyword) != canonical:
            raise TrendDataError(
                f"display_keyword does not match canonical_keyword in {path}"
            )
        count = _finite_nonnegative(row.get("video_count"), field="video_count", path=path)
        sample_value = _finite_nonnegative(
            row.get("sample_size"), field="sample_size", path=path
        )
        if not sample_value.is_integer() or sample_value <= 0:
            raise TrendDataError(f"sample_size must be a positive integer in {path}")
        sample_size = int(sample_value)
        if count > sample_size or not count.is_integer():
            raise TrendDataError(f"video_count is invalid in {path}")
        expected_prevalence = count / sample_size
        provided_prevalence = _finite_nonnegative(
            row.get("prevalence"), field="prevalence", path=path
        )
        if not math.isclose(provided_prevalence, expected_prevalence, abs_tol=1e-7):
            raise TrendDataError(f"prevalence does not match video_count in {path}")

        counts[canonical] = count
        display_names[canonical] = display_keyword
        prevalence[canonical] = expected_prevalence
        dates.add(str(row.get("date") or ""))
        regions.add(str(row.get("region") or "").upper())
        sample_sizes.add(sample_size)
        tokenizer_versions.add(str(row.get("tokenizer_version") or ""))
        normalizer_versions.add(str(row.get("normalizer_version") or ""))
        alias_versions.add(str(row.get("alias_version") or ""))
        stopword_versions.add(str(row.get("stopword_version") or ""))
        analysis_signatures.add(str(row.get("analysis_signature") or ""))

    metadata_sets = (
        dates,
        regions,
        sample_sizes,
        tokenizer_versions,
        normalizer_versions,
        alias_versions,
        stopword_versions,
        analysis_signatures,
    )
    if any(len(values) != 1 for values in metadata_sets):
        raise TrendDataError(f"snapshot metadata is inconsistent in {path}")
    if any(not next(iter(values)) for values in metadata_sets if values is not sample_sizes):
        raise TrendDataError(f"snapshot analysis metadata is blank in {path}")
    row_date = next(iter(dates))
    if row_date != _date_from_path(path).isoformat():
        raise TrendDataError(f"snapshot date does not match filename in {path}")
    region = next(iter(regions))
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise TrendDataError(f"snapshot region is invalid in {path}")
    tokenizer_version = next(iter(tokenizer_versions))
    normalizer_version = next(iter(normalizer_versions))
    alias_version = next(iter(alias_versions))
    stopword_version = next(iter(stopword_versions))
    analysis_signature = next(iter(analysis_signatures))
    expected_signature = "|".join(
        (
            tokenizer_version,
            normalizer_version,
            alias_version,
            stopword_version,
        )
    )
    if analysis_signature != expected_signature:
        raise TrendDataError(f"analysis_signature is invalid in {path}")
    return Snapshot(
        path=path,
        schema_version=KEYWORD_SCHEMA_VERSION,
        snapshot_date=date.fromisoformat(row_date),
        region=region,
        counts=counts,
        display_names=display_names,
        prevalence=prevalence,
        sample_size=next(iter(sample_sizes)),
        tokenizer_version=tokenizer_version,
        normalizer_version=normalizer_version,
        alias_version=alias_version,
        stopword_version=stopword_version,
        analysis_signature=analysis_signature,
    )


def load_snapshot(path: Path) -> Snapshot:
    fields, rows = read_csv_rows(path)
    if {"keyword", "count"}.issubset(fields) and "schema_version" not in fields:
        return _load_legacy_snapshot(Path(path), rows)
    required = {
        "schema_version",
        "date",
        "region",
        "canonical_keyword",
        "display_keyword",
        "video_count",
        "sample_size",
        "prevalence",
        "tokenizer_version",
        "normalizer_version",
        "alias_version",
        "stopword_version",
        "analysis_signature",
    }
    missing = required.difference(fields)
    if missing:
        raise TrendDataError(
            f"missing columns in {path}: {', '.join(sorted(missing))}"
        )
    return _load_v2_snapshot(Path(path), rows)


def select_default_pair(history_dir: Path) -> tuple[Snapshot, Snapshot]:
    snapshots = [load_snapshot(path) for path in find_history_files(history_dir)]
    if not snapshots:
        raise TrendDataError("no history snapshots were found")
    newest = snapshots[-1]
    compatible = [
        snapshot
        for snapshot in snapshots
        if snapshot.schema_version == newest.schema_version
        and snapshot.region == newest.region
        and snapshot.analysis_signature == newest.analysis_signature
    ]
    if len(compatible) < 2:
        raise TrendDataError(
            f"newest snapshot {newest.path.name} has no compatible predecessor"
        )
    return compatible[-2], compatible[-1]


def _trend_status(old_value: float, new_value: float) -> str:
    if old_value == 0 and new_value > 0:
        return "new"
    if new_value > old_value:
        return "rising"
    if new_value < old_value:
        return "falling"
    return "stable"


def compare_snapshots(
    old: Snapshot,
    new: Snapshot,
    *,
    min_support: int = 2,
) -> list[dict[str, object]]:
    if old.schema_version != new.schema_version:
        raise TrendDataError("legacy and v2 snapshots cannot be compared")
    if old.region != new.region:
        raise TrendDataError("snapshots from different regions cannot be compared")
    if old.analysis_signature != new.analysis_signature:
        raise TrendDataError("snapshots use different analysis configurations")
    if old.snapshot_date >= new.snapshot_date:
        raise TrendDataError("old snapshot must be earlier than new snapshot")
    if min_support < 1:
        raise TrendDataError("min_support must be at least 1")

    mode = "prevalence_v2" if new.schema_version == KEYWORD_SCHEMA_VERSION else "legacy_raw_count"
    keys = set(old.counts) | set(new.counts)
    rows: list[dict[str, object]] = []
    for canonical in keys:
        old_count = old.counts.get(canonical, 0.0)
        new_count = new.counts.get(canonical, 0.0)
        change = new_count - old_count
        display = new.display_names.get(canonical) or old.display_names.get(canonical) or canonical
        if mode == "prevalence_v2":
            old_prevalence = old.prevalence.get(canonical, 0.0)
            new_prevalence = new.prevalence.get(canonical, 0.0)
            prevalence_change = new_prevalence - old_prevalence
            old_smoothed = (old_count + 0.5) / (int(old.sample_size or 0) + 1)
            new_smoothed = (new_count + 0.5) / (int(new.sample_size or 0) + 1)
            growth_rate: object = new_smoothed / old_smoothed - 1
            confidence = "supported" if new_count >= min_support else "low_support"
            delta_pp: object = prevalence_change * 100
            current_support: object = int(new_count)
            trend_status = _trend_status(old_prevalence, new_prevalence)
        else:
            old_prevalence = ""
            new_prevalence = ""
            prevalence_change = ""
            delta_pp = ""
            growth_rate = ""
            current_support = int(new_count) if new_count.is_integer() else new_count
            confidence = "legacy_unknown"
            trend_status = _trend_status(old_count, new_count)
        rows.append(
            {
                "keyword": display,
                "old_count": int(old_count) if old_count.is_integer() else old_count,
                "new_count": int(new_count) if new_count.is_integer() else new_count,
                "change": int(change) if change.is_integer() else change,
                "canonical_keyword": canonical,
                "old_prevalence": old_prevalence,
                "new_prevalence": new_prevalence,
                "prevalence_change": prevalence_change,
                "delta_pp": delta_pp,
                "growth_rate": growth_rate,
                "current_support": current_support,
                "confidence": confidence,
                "trend_status": trend_status,
                "comparison_mode": mode,
                "old_date": old.snapshot_date.isoformat(),
                "new_date": new.snapshot_date.isoformat(),
                "region": new.region,
                "old_sample_size": old.sample_size if old.sample_size is not None else "",
                "new_sample_size": new.sample_size if new.sample_size is not None else "",
                "tokenizer_version": new.tokenizer_version,
                "normalizer_version": new.normalizer_version,
                "alias_version": new.alias_version,
                "stopword_version": new.stopword_version,
                "analysis_signature": new.analysis_signature,
            }
        )

    if mode == "prevalence_v2":
        rows.sort(
            key=lambda row: (
                -float(row["delta_pp"]),
                row["confidence"] != "supported",
                -float(row["new_count"]),
                canonicalize_keyword(row["keyword"]),
            )
        )
    else:
        rows.sort(
            key=lambda row: (
                -float(row["change"]),
                canonicalize_keyword(row["keyword"]),
            )
        )
    return rows


def write_comparison_csv(
    path: Path,
    rows: Iterable[dict[str, object]],
    *,
    overwrite: bool = True,
) -> None:
    atomic_write_csv(path, COMPARISON_FIELDS, rows, overwrite=overwrite)


def _font_candidates() -> tuple[str, ...]:
    system = platform.system()
    if system == "Windows":
        return ("Malgun Gothic", "Noto Sans CJK KR", "NanumGothic")
    if system == "Darwin":
        return ("AppleGothic", "Noto Sans CJK KR", "NanumGothic")
    return ("Noto Sans CJK KR", "NanumGothic")


def render_comparison_chart(
    path: Path,
    rows: list[dict[str, object]],
    *,
    old_date: date,
    new_date: date,
    top_n: int,
    overwrite: bool = True,
    font_family: str | None = None,
) -> None:
    if top_n < 1:
        raise TrendDataError("top_n must be at least 1")
    if not rows:
        raise TrendDataError("comparison has no rows to plot")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError as exc:
        raise TrendDataError("matplotlib is required to create a chart") from exc

    mode = str(rows[0]["comparison_mode"])
    metric = "delta_pp" if mode == "prevalence_v2" else "change"
    xlabel = "Prevalence change (percentage points)" if mode == "prevalence_v2" else "Count change"
    rising = [row for row in rows if float(row[metric]) > 0]
    plotted = (rising or rows)[:top_n]
    labels = [str(row["keyword"]) for row in plotted][::-1]
    values = [float(row[metric]) for row in plotted][::-1]

    selected_font = font_family
    if selected_font is None:
        for candidate in _font_candidates():
            try:
                font_manager.findfont(candidate, fallback_to_default=False)
            except ValueError:
                continue
            selected_font = candidate
            break
    if selected_font is None:
        selected_font = "DejaVu Sans"
        logging.warning(
            "no Korean-capable chart font was found; use --font-family after installing one"
        )

    with plt.rc_context(
        {"font.family": selected_font, "axes.unicode_minus": False}
    ):
        fig, axis = plt.subplots(figsize=(10, 6))
        try:
            axis.barh(labels, values, color="#E07A2D")
            title_kind = "rising keywords" if rising else "keyword changes"
            axis.set_title(f"Top {top_n} {title_kind} ({old_date} to {new_date})")
            axis.set_xlabel(xlabel)
            fig.tight_layout()
            with atomic_output_path(path, overwrite=overwrite) as temporary:
                fig.savefig(temporary, format="png", dpi=150)
        finally:
            plt.close(fig)
