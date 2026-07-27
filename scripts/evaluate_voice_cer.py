#!/usr/bin/env python3
"""Transcribe BrandMate voice benchmarks and append reproducible CER results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT.parent
DEFAULT_CSV_PATH = TEST_ROOT / "voice test.csv"
DEFAULT_AUDIO_DIR = TEST_ROOT / "test voices"
DEFAULT_ENV_PATH = REPO_ROOT / "apps" / "api" / ".env.voice-eval"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-transcribe"
RESULT_FIELDS = (
    "asr_model",
    "asr_transcript",
    "cer_reference",
    "cer_hypothesis",
    "cer_edits",
    "cer_reference_chars",
    "cer",
    "cer_percent",
    "asr_input_tokens",
    "asr_output_tokens",
    "asr_total_tokens",
    "asr_latency(s)",
    "cer_evaluated_at",
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
    "brandmate_voice_test_plan",
    REPO_ROOT / "scripts" / "run_cosyvoice_test.py",
)
COSYVOICE_SERVER = _load_module(
    "brandmate_cosyvoice_server_for_cer",
    REPO_ROOT / "services" / "cosyvoice" / "server.py",
)


@dataclass(frozen=True)
class CerResult:
    reference: str
    hypothesis: str
    edits: int
    reference_chars: int

    @property
    def rate(self) -> float:
        if self.reference_chars:
            return self.edits / self.reference_chars
        return 0.0 if not self.hypothesis else 1.0


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_seconds: float


def load_env_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"환경변수 파일을 찾을 수 없습니다: {path}")
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def normalize_for_cer(text: str) -> str:
    spoken = COSYVOICE_SERVER.normalize_korean_tts_text(text)
    normalized = unicodedata.normalize("NFKC", spoken).casefold()
    return "".join(character for character in normalized if character.isalnum())


def levenshtein_distance(reference: str, hypothesis: str) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row_index, reference_char in enumerate(reference, start=1):
        current = [row_index]
        for column_index, hypothesis_char in enumerate(hypothesis, start=1):
            substitution = previous[column_index - 1] + (
                reference_char != hypothesis_char
            )
            current.append(
                min(
                    previous[column_index] + 1,
                    current[column_index - 1] + 1,
                    substitution,
                )
            )
        previous = current
    return previous[-1]


def calculate_cer(reference_text: str, hypothesis_text: str) -> CerResult:
    reference = normalize_for_cer(reference_text)
    hypothesis = normalize_for_cer(hypothesis_text)
    return CerResult(
        reference=reference,
        hypothesis=hypothesis,
        edits=levenshtein_distance(reference, hypothesis),
        reference_chars=len(reference),
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
    for index, (row, case) in enumerate(zip(validated, plan, strict=True), start=2):
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
                f"CSV {index}행이 테스트 계획과 다릅니다. "
                f"현재={actual}, 예상={expected}"
            )
    return validated


def result_fieldnames(existing: Iterable[str]) -> list[str]:
    fields = list(existing)
    fields.extend(field for field in RESULT_FIELDS if field not in fields)
    return fields


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
        f"{csv_path.stem}.before-cer{csv_path.suffix}"
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


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_cache(
    cache_path: Path,
    *,
    model: str,
    audio_sha256: str,
) -> TranscriptionResult | None:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("model") != model or payload.get("audio_sha256") != audio_sha256:
        return None
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return TranscriptionResult(
        text=text.strip(),
        input_tokens=_optional_int(payload.get("input_tokens")),
        output_tokens=_optional_int(payload.get("output_tokens")),
        total_tokens=_optional_int(payload.get("total_tokens")),
        latency_seconds=float(payload.get("latency_seconds", 0.0)),
    )


def write_cache(
    cache_path: Path,
    *,
    model: str,
    audio_sha256: str,
    result: TranscriptionResult,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "audio_sha256": audio_sha256,
        "text": result.text,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "latency_seconds": result.latency_seconds,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary_path = cache_path.with_suffix(
        f"{cache_path.suffix}.{uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, cache_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def transcribe_audio(
    client: httpx.Client,
    *,
    endpoint: str,
    model: str,
    audio_path: Path,
    audio_bytes: bytes,
    max_retries: int,
) -> TranscriptionResult:
    for attempt in range(max_retries + 1):
        started_at = time.perf_counter()
        try:
            response = client.post(
                endpoint,
                data={
                    "model": model,
                    "language": "ko",
                    "response_format": "json",
                    "temperature": "0",
                },
                files={
                    "file": (
                        audio_path.name,
                        audio_bytes,
                        "audio/wav",
                    )
                },
            )
        except httpx.HTTPError as error:
            if attempt >= max_retries:
                raise RuntimeError(
                    f"OpenAI 전사 요청 실패: {type(error).__name__}"
                ) from error
            time.sleep(min(2**attempt, 30))
            continue

        latency = time.perf_counter() - started_at
        if response.is_success:
            try:
                payload = response.json()
            except ValueError as error:
                raise RuntimeError("OpenAI 전사 응답이 JSON이 아닙니다.") from error
            transcript = payload.get("text")
            if not isinstance(transcript, str) or not transcript.strip():
                raise RuntimeError("OpenAI 전사 응답에 text가 없습니다.")
            usage = payload.get("usage")
            if not isinstance(usage, dict):
                usage = {}
            return TranscriptionResult(
                text=transcript.strip(),
                input_tokens=_optional_int(usage.get("input_tokens")),
                output_tokens=_optional_int(usage.get("output_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                latency_seconds=latency,
            )

        retryable = response.status_code == 429 or response.status_code >= 500
        if retryable and attempt < max_retries:
            retry_after = response.headers.get("retry-after", "")
            delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2**attempt
            time.sleep(min(delay, 60))
            continue
        detail = response.text.strip().replace("\n", " ")[:500]
        raise RuntimeError(
            f"OpenAI 전사 요청 실패 ({response.status_code}): {detail}"
        )
    raise AssertionError("unreachable")


def update_row(
    row: dict[str, str],
    *,
    model: str,
    transcript: TranscriptionResult,
    cer: CerResult,
) -> None:
    row.update(
        {
            "asr_model": model,
            "asr_transcript": transcript.text,
            "cer_reference": cer.reference,
            "cer_hypothesis": cer.hypothesis,
            "cer_edits": str(cer.edits),
            "cer_reference_chars": str(cer.reference_chars),
            "cer": f"{cer.rate:.6f}",
            "cer_percent": f"{cer.rate * 100:.2f}",
            "asr_input_tokens": _csv_value(transcript.input_tokens),
            "asr_output_tokens": _csv_value(transcript.output_tokens),
            "asr_total_tokens": _csv_value(transcript.total_tokens),
            "asr_latency(s)": f"{transcript.latency_seconds:.3f}",
            "cer_evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _csv_value(value: object) -> str:
    return "" if value is None else str(value)


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
        if overwrite or not row.get("cer", "").strip()
    ]
    return pending if run_all else pending[:count]


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe BrandMate WAV benchmarks and append CER to CSV."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise RuntimeError("--count는 1 이상이어야 합니다.")
    if args.max_retries < 0:
        raise RuntimeError("--max-retries는 0 이상이어야 합니다.")
    if args.delay_seconds < 0:
        raise RuntimeError("--delay-seconds는 0 이상이어야 합니다.")

    load_env_file(args.env_file)
    model = args.model or os.getenv("VOICE_EVAL_ASR_MODEL") or DEFAULT_MODEL
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
    cache_dir = args.cache_dir or args.audio_dir / ".asr-cache"
    selected_audio = [
        (row_index, case, resolve_audio_path(args.audio_dir, case))
        for row_index, case in selected
    ]

    print(f"CSV: {args.csv}")
    print(f"WAV 폴더: {args.audio_dir}")
    print(f"ASR 모델: {model}")
    print(f"완료: {len(plan) - len(select_cases(rows, plan, count=len(plan), run_all=True, overwrite=False))}/{len(plan)}")
    print(f"이번 실행: {len(selected)}건")
    for _, case, audio_path in selected_audio:
        print(f"  #{case.num} {audio_path.name}")
    if args.dry_run or not selected:
        return 0

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            f"OPENAI_API_KEY가 비어 있습니다. 값을 입력해주세요: {args.env_file}"
        )

    ensure_csv_writable(args.csv)
    backup_path = backup_csv(args.csv)
    print(f"원본 CSV 백업: {backup_path}")
    endpoint = f"{args.base_url.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    final_fieldnames = result_fieldnames(fieldnames)

    with httpx.Client(headers=headers, timeout=args.timeout) as client:
        for position, (row_index, case, audio_path) in enumerate(
            selected_audio,
            start=1,
        ):
            ensure_csv_writable(args.csv)
            audio_bytes = audio_path.read_bytes()
            audio_hash = sha256_bytes(audio_bytes)
            cache_path = cache_dir / f"{audio_path.stem}.{model}.json"
            transcript = read_cache(
                cache_path,
                model=model,
                audio_sha256=audio_hash,
            )
            source = "cache"
            if transcript is None:
                source = "api"
                transcript = transcribe_audio(
                    client,
                    endpoint=endpoint,
                    model=model,
                    audio_path=audio_path,
                    audio_bytes=audio_bytes,
                    max_retries=args.max_retries,
                )
                write_cache(
                    cache_path,
                    model=model,
                    audio_sha256=audio_hash,
                    result=transcript,
                )

            cer = calculate_cer(case.text, transcript.text)
            update_row(
                rows[row_index],
                model=model,
                transcript=transcript,
                cer=cer,
            )
            write_csv_atomic(args.csv, final_fieldnames, rows)
            print(
                f"[{position}/{len(selected)}] #{case.num} "
                f"CER={cer.rate:.4f} ({cer.rate * 100:.2f}%) "
                f"source={source}"
            )
            if source == "api" and position < len(selected):
                time.sleep(args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
