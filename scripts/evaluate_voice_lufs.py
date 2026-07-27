#!/usr/bin/env python3
"""Measure BrandMate WAV loudness with FFmpeg and append results to CSV."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT.parent
DEFAULT_CSV_PATH = TEST_ROOT / "voice test.csv"
DEFAULT_AUDIO_DIR = TEST_ROOT / "test voices"
RESULT_FIELDS = (
    "lufs_integrated",
    "true_peak_dbtp",
    "lufs_tool",
    "lufs_measured_at",
)
LOUDNORM_FILTER = (
    "loudnorm=I=-16:TP=-1.5:LRA=7:dual_mono=true:print_format=json"
)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VOICE_TEST = _load_module(
    "brandmate_voice_test_plan_for_lufs",
    REPO_ROOT / "scripts" / "run_cosyvoice_test.py",
)


def read_csv(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not csv_path.is_file():
        raise RuntimeError(f"CSV 파일을 찾을 수 없습니다: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = list(reader.fieldnames or ())
        rows = list(reader)
    required = {"num", "voice", "tone", "text_type"}
    missing = required.difference(fieldnames)
    if missing:
        raise RuntimeError(f"CSV 필수 컬럼이 없습니다: {sorted(missing)}")
    return fieldnames, rows


def validate_rows(
    rows: Iterable[dict[str, str]],
    plan: list[Any],
) -> list[dict[str, str]]:
    validated = list(rows)
    if len(validated) != len(plan):
        raise RuntimeError(
            f"CSV 행 수({len(validated)})와 테스트 계획({len(plan)})이 다릅니다."
        )
    for csv_line, (row, case) in enumerate(
        zip(validated, plan, strict=True),
        start=2,
    ):
        actual = (
            row.get("num", ""),
            row.get("voice", ""),
            row.get("tone", ""),
            row.get("text_type", ""),
        )
        expected = (
            str(case.num),
            case.voice,
            case.tone,
            case.text_type,
        )
        if actual != expected:
            raise RuntimeError(
                f"CSV {csv_line}행이 테스트 계획과 다릅니다. "
                f"현재={actual}, 예상={expected}"
            )
    return validated


def result_fieldnames(existing: Iterable[str]) -> list[str]:
    fields = list(existing)
    fields.extend(field for field in RESULT_FIELDS if field not in fields)
    return fields


def resolve_audio_path(audio_dir: Path, case: Any) -> Path:
    generated_path = audio_dir / case.filename
    if generated_path.is_file():
        return generated_path
    legacy_path = audio_dir / (
        f"T{case.num:03d}_{case.voice}_{case.tone}_{case.text_type}.wav"
    )
    if legacy_path.is_file():
        return legacy_path
    raise RuntimeError(
        "WAV 파일을 찾을 수 없습니다. 확인한 경로: "
        f"{generated_path}, {legacy_path}"
    )


def select_cases(
    rows: list[dict[str, str]],
    plan: list[Any],
    *,
    count: int,
    run_all: bool,
    overwrite: bool,
) -> list[tuple[int, Any]]:
    pending = [
        (index, case)
        for index, (row, case) in enumerate(zip(rows, plan, strict=True))
        if overwrite or not row.get("lufs_integrated", "").strip()
    ]
    return pending if run_all else pending[:count]


def resolve_ffmpeg(explicit: str | None) -> str:
    if explicit:
        resolved = shutil.which(explicit)
        if resolved:
            return resolved
        path = Path(explicit).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise RuntimeError(f"FFmpeg 실행 파일을 찾을 수 없습니다: {explicit}")

    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved

    try:
        import imageio_ffmpeg
    except ImportError as error:
        raise RuntimeError(
            "FFmpeg를 찾을 수 없습니다. FFmpeg를 설치하거나 "
            "`python -m pip install imageio-ffmpeg`를 실행하세요."
        ) from error
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg_version(ffmpeg: str) -> str:
    completed = subprocess.run(
        [ffmpeg, "-version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RuntimeError(f"FFmpeg 버전을 확인할 수 없습니다: {ffmpeg}")
    return completed.stdout.splitlines()[0].strip()


def build_ffmpeg_command(ffmpeg: str, audio_path: Path) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(audio_path),
        "-map",
        "0:a:0",
        "-af",
        LOUDNORM_FILTER,
        "-f",
        "null",
        "-",
    ]


def parse_loudnorm_output(stderr: str) -> tuple[float, float]:
    payloads = re.findall(r"\{\s*\"input_i\".*?\}", stderr, flags=re.DOTALL)
    if not payloads:
        raise RuntimeError("FFmpeg 출력에서 loudnorm JSON을 찾을 수 없습니다.")
    try:
        payload = json.loads(payloads[-1])
        integrated = float(payload["input_i"])
        true_peak = float(payload["input_tp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("FFmpeg loudnorm 측정값을 해석할 수 없습니다.") from error
    if not math.isfinite(integrated) or not math.isfinite(true_peak):
        raise RuntimeError(
            f"유효하지 않은 음량 측정값입니다: {integrated}, {true_peak}"
        )
    return integrated, true_peak


def measure_audio(ffmpeg: str, audio_path: Path) -> tuple[float, float]:
    completed = subprocess.run(
        build_ffmpeg_command(ffmpeg, audio_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()
        tail = "\n".join(detail[-8:])
        raise RuntimeError(f"FFmpeg 측정 실패: {audio_path}\n{tail}")
    return parse_loudnorm_output(completed.stderr)


def measure_selected(
    ffmpeg: str,
    selected_audio: list[tuple[int, Any, Path]],
    *,
    workers: int,
) -> dict[int, tuple[float, float]]:
    results: dict[int, tuple[float, float]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(measure_audio, ffmpeg, audio_path): case
            for _, case, audio_path in selected_audio
        }
        for future in as_completed(futures):
            case = futures[future]
            results[case.num] = future.result()
            integrated, true_peak = results[case.num]
            print(
                f"  #{case.num}: {integrated:.2f} LUFS-I, "
                f"{true_peak:.2f} dBTP"
            )
    return results


def ensure_csv_writable(csv_path: Path) -> None:
    try:
        with csv_path.open("r+", encoding="utf-8-sig", newline=""):
            pass
    except PermissionError as error:
        raise RuntimeError(
            f"CSV를 수정할 수 없습니다. Excel에서 파일을 닫아주세요: {csv_path}"
        ) from error


def backup_csv(csv_path: Path) -> Path:
    backup_path = csv_path.with_name(
        f"{csv_path.stem}.before-lufs{csv_path.suffix}"
    )
    if not backup_path.exists():
        shutil.copy2(csv_path, backup_path)
    return backup_path


def write_csv_atomic(
    csv_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    temporary_path = csv_path.with_name(
        f".{csv_path.name}.{uuid4().hex}.tmp"
    )
    try:
        with temporary_path.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, csv_path)
    except PermissionError as error:
        raise RuntimeError(
            f"CSV 저장에 실패했습니다. Excel에서 파일을 닫아주세요: {csv_path}"
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def update_rows(
    rows: list[dict[str, str]],
    selected: list[tuple[int, Any]],
    results: dict[int, tuple[float, float]],
    *,
    tool: str,
) -> None:
    measured_at = datetime.now(timezone.utc).isoformat()
    for row_index, case in selected:
        integrated, true_peak = results[case.num]
        rows[row_index].update(
            {
                "lufs_integrated": f"{integrated:.2f}",
                "true_peak_dbtp": f"{true_peak:.2f}",
                "lufs_tool": tool,
                "lufs_measured_at": measured_at,
            }
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure BrandMate WAV LUFS-I and True Peak with FFmpeg."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise RuntimeError("--count는 1 이상이어야 합니다.")
    if args.workers < 1:
        raise RuntimeError("--workers는 1 이상이어야 합니다.")

    plan = VOICE_TEST.build_test_plan()
    fieldnames, rows = read_csv(args.csv)
    rows = validate_rows(rows, plan)
    selected = select_cases(
        rows,
        plan,
        count=args.count,
        run_all=args.all,
        overwrite=args.overwrite,
    )
    selected_audio = [
        (row_index, case, resolve_audio_path(args.audio_dir, case))
        for row_index, case in selected
    ]
    completed_count = len(plan) - len(
        select_cases(
            rows,
            plan,
            count=len(plan),
            run_all=True,
            overwrite=False,
        )
    )

    print(f"CSV: {args.csv}")
    print(f"WAV 폴더: {args.audio_dir}")
    print(f"완료: {completed_count}/{len(plan)}")
    print(f"이번 실행: {len(selected_audio)}건")
    for _, case, audio_path in selected_audio:
        print(f"  #{case.num} {audio_path.name}")
    if args.dry_run or not selected_audio:
        return 0

    ensure_csv_writable(args.csv)
    ffmpeg = resolve_ffmpeg(args.ffmpeg)
    tool = ffmpeg_version(ffmpeg)
    print(f"FFmpeg: {ffmpeg}")
    print(f"버전: {tool}")
    backup_path = backup_csv(args.csv)
    print(f"원본 CSV 백업: {backup_path}")

    results = measure_selected(
        ffmpeg,
        selected_audio,
        workers=args.workers,
    )
    update_rows(rows, selected, results, tool=tool)
    ensure_csv_writable(args.csv)
    write_csv_atomic(args.csv, result_fieldnames(fieldnames), rows)

    integrated_values = [value[0] for value in results.values()]
    true_peak_values = [value[1] for value in results.values()]
    print(
        f"LUFS-I: 평균={sum(integrated_values) / len(integrated_values):.2f}, "
        f"최소={min(integrated_values):.2f}, 최대={max(integrated_values):.2f}"
    )
    print(
        f"True Peak: 최소={min(true_peak_values):.2f}, "
        f"최대={max(true_peak_values):.2f} dBTP"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
