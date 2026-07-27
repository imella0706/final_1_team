#!/usr/bin/env python3
"""Run NISQA-TTS over BrandMate WAV benchmarks and append results to CSV."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT.parent
DEFAULT_CSV_PATH = TEST_ROOT / "voice test.csv"
DEFAULT_AUDIO_DIR = TEST_ROOT / "test voices"
DEFAULT_NISQA_HOME = Path.home() / ".local" / "share" / "brandmate-nisqa"
DEFAULT_NISQA_ROOT = DEFAULT_NISQA_HOME / "NISQA"
DEFAULT_MODEL_PATH = DEFAULT_NISQA_ROOT / "weights" / "nisqa_tts.tar"
DEFAULT_RUNS_DIR = DEFAULT_NISQA_HOME / "runs"
DEFAULT_MAX_SEGMENTS = 10_000
EXPECTED_MODEL = "NISQA_TTS_v1"
RESULT_FIELDS = (
    "nisqa_tts_naturalness",
    "nisqa_model",
    "nisqa_source_commit",
    "nisqa_evaluated_at",
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
    "brandmate_voice_test_plan_for_nisqa",
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
        if overwrite or not row.get("nisqa_tts_naturalness", "").strip()
    ]
    return pending if run_all else pending[:count]


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
        f"{csv_path.stem}.before-nisqa{csv_path.suffix}"
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


def write_manifest(
    manifest_path: Path,
    selected_audio: list[tuple[int, Any, Path]],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=("num", "deg"))
        writer.writeheader()
        for _, case, audio_path in selected_audio:
            writer.writerow(
                {
                    "num": case.num,
                    "deg": str(audio_path.resolve()),
                }
            )


def build_nisqa_command(
    *,
    nisqa_root: Path,
    model_path: Path,
    manifest_path: Path,
    output_dir: Path,
    batch_size: int,
    num_workers: int,
    max_segments: int,
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).with_name("run_nisqa_predict.py")),
        "--nisqa-root",
        str(nisqa_root),
        "--pretrained-model",
        str(model_path),
        "--csv-file",
        str(manifest_path),
        "--csv-deg",
        "deg",
        "--num-workers",
        str(num_workers),
        "--batch-size",
        str(batch_size),
        "--max-segments",
        str(max_segments),
        "--output-dir",
        str(output_dir),
    ]


def run_nisqa(
    *,
    nisqa_root: Path,
    model_path: Path,
    manifest_path: Path,
    output_dir: Path,
    batch_size: int,
    num_workers: int,
    max_segments: int,
) -> tuple[Path, float]:
    if not (nisqa_root / "run_predict.py").is_file():
        raise RuntimeError(f"NISQA 소스를 찾을 수 없습니다: {nisqa_root}")
    if not model_path.is_file():
        raise RuntimeError(f"NISQA-TTS 가중치를 찾을 수 없습니다: {model_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    command = build_nisqa_command(
        nisqa_root=nisqa_root,
        model_path=model_path,
        manifest_path=manifest_path,
        output_dir=output_dir,
        batch_size=batch_size,
        num_workers=num_workers,
        max_segments=max_segments,
    )
    started_at = time.perf_counter()
    completed = subprocess.run(command, cwd=nisqa_root, check=False)
    latency = time.perf_counter() - started_at
    if completed.returncode:
        raise RuntimeError(
            f"NISQA-TTS 배치 평가에 실패했습니다: exit {completed.returncode}"
        )
    results_path = output_dir / "NISQA_results.csv"
    if not results_path.is_file():
        raise RuntimeError(f"NISQA 결과 CSV가 생성되지 않았습니다: {results_path}")
    return results_path, latency


def read_nisqa_results(
    results_path: Path,
    expected_cases: list[Any],
) -> dict[int, tuple[float, str]]:
    with results_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        result_rows = list(csv.DictReader(csv_file))
    if len(result_rows) != len(expected_cases):
        raise RuntimeError(
            f"NISQA 결과 수({len(result_rows)})와 요청 수 "
            f"({len(expected_cases)})가 다릅니다."
        )

    results: dict[int, tuple[float, str]] = {}
    for position, (result_row, case) in enumerate(
        zip(result_rows, expected_cases, strict=True),
        start=1,
    ):
        raw_num = result_row.get("num", "").strip()
        actual_num = int(raw_num) if raw_num.isdigit() else case.num
        if actual_num != case.num:
            raise RuntimeError(
                f"NISQA 결과 {position}행 순서가 다릅니다. "
                f"현재={actual_num}, 예상={case.num}"
            )
        try:
            score = float(result_row.get("mos_pred", ""))
        except ValueError as error:
            raise RuntimeError(
                f"NISQA 결과 {position}행의 mos_pred가 숫자가 아닙니다."
            ) from error
        if not math.isfinite(score):
            raise RuntimeError(
                f"NISQA 결과 {position}행의 mos_pred가 유효하지 않습니다: {score}"
            )
        model = result_row.get("model", "").strip()
        if model != EXPECTED_MODEL:
            raise RuntimeError(
                f"NISQA 결과 모델이 다릅니다: {model or '(없음)'}"
            )
        if case.num in results:
            raise RuntimeError(f"NISQA 결과가 중복됐습니다: #{case.num}")
        results[case.num] = (score, model)
    return results


def source_commit(nisqa_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(nisqa_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        return ""
    return completed.stdout.strip()


def update_rows(
    rows: list[dict[str, str]],
    selected: list[tuple[int, Any]],
    results: dict[int, tuple[float, str]],
    *,
    commit: str,
) -> None:
    evaluated_at = datetime.now(timezone.utc).isoformat()
    for row_index, case in selected:
        score, model = results[case.num]
        rows[row_index].update(
            {
                "nisqa_tts_naturalness": f"{score:.6f}",
                "nisqa_model": model,
                "nisqa_source_commit": commit,
                "nisqa_evaluated_at": evaluated_at,
            }
        )


def default_run_dir(runs_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return runs_dir / f"voice-test-{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run NISQA-TTS over BrandMate WAVs and append scores to CSV."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--nisqa-root", type=Path, default=DEFAULT_NISQA_ROOT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--results-csv", type=Path)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument(
        "--max-segments",
        type=int,
        default=DEFAULT_MAX_SEGMENTS,
        help="Maximum NISQA spectrogram windows per WAV.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise RuntimeError("--count는 1 이상이어야 합니다.")
    if args.batch_size < 1:
        raise RuntimeError("--batch-size는 1 이상이어야 합니다.")
    if args.num_workers < 0:
        raise RuntimeError("--num-workers는 0 이상이어야 합니다.")
    if args.max_segments < 1:
        raise RuntimeError("--max-segments must be at least 1")

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
    print(f"NISQA 가중치: {args.model_path}")
    print(f"완료: {completed_count}/{len(plan)}")
    print(f"이번 실행: {len(selected_audio)}건")
    for _, case, audio_path in selected_audio:
        print(f"  #{case.num} {audio_path.name}")
    if args.dry_run or not selected_audio:
        return 0

    ensure_csv_writable(args.csv)
    backup_path = backup_csv(args.csv)
    print(f"원본 CSV 백업: {backup_path}")

    if args.results_csv:
        results_path = args.results_csv
        latency = 0.0
        run_dir = results_path.parent
    else:
        run_dir = args.run_dir or default_run_dir(args.runs_dir)
        if run_dir.exists():
            raise RuntimeError(f"기존 run 폴더를 덮어쓰지 않습니다: {run_dir}")
        manifest_path = run_dir / "manifest.csv"
        write_manifest(manifest_path, selected_audio)
        results_path, latency = run_nisqa(
            nisqa_root=args.nisqa_root,
            model_path=args.model_path,
            manifest_path=manifest_path,
            output_dir=run_dir,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            max_segments=args.max_segments,
        )

    results = read_nisqa_results(
        results_path,
        [case for _, case in selected],
    )
    update_rows(
        rows,
        selected,
        results,
        commit=source_commit(args.nisqa_root),
    )
    ensure_csv_writable(args.csv)
    write_csv_atomic(args.csv, result_fieldnames(fieldnames), rows)
    scores = [score for score, _ in results.values()]
    print(f"NISQA 결과: {results_path}")
    print(f"평가 시간: {latency:.3f}초")
    print(
        f"Naturalness: 평균={sum(scores) / len(scores):.4f}, "
        f"최소={min(scores):.4f}, 최대={max(scores):.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
