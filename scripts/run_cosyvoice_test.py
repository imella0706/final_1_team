#!/usr/bin/env python3
"""Generate the next CosyVoice benchmark cases and append their timings to CSV."""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT.parent
DEFAULT_CSV_PATH = TEST_ROOT / "voice test.csv"
DEFAULT_OUTPUT_DIR = TEST_ROOT / "test voices"
DEFAULT_BASE_URL = "http://127.0.0.1:50000"
CSV_FIELDS = (
    "num",
    "voice",
    "tone",
    "voice_time(s)",
    "create_time(s)",
    "text_type",
)

VOICE_PRESETS = (
    ("man", "happy"),
    ("man", "serious"),
    ("woman", "happy"),
    ("woman", "serious"),
    ("woman", "whisper"),
)

TEXT_CASES = (
    ("short1", "오늘 커피는 딸기 라떼로 달콤하게."),
    ("short2", "따뜻한 점심, 정성 가득 한 그릇."),
    ("short3", "갓 구운 빵 향기로 하루를 시작하세요."),
    (
        "med1",
        "봄날커피의 신메뉴, 딸기 크림 라떼를 만나보세요. "
        "달콤한 하루가 시작됩니다.",
    ),
    (
        "med2",
        "오늘 점심은 따뜻한 김치찌개 한 상 어떠세요? "
        "정성껏 끓인 한 그릇을 준비했습니다.",
    ),
    (
        "med3",
        "갓 구운 크루아상 고소한 아메리카노, "
        "오늘 아침을 더 든든하게 채워보세요.",
    ),
    (
        "long1",
        "생딸기의 산뜻함과 부드러운 크림을 한 잔에 담았습니다. "
        "봄날커피의 딸기 크림 라떼로 오늘을 조금 더 달콤하게 시작해보세요.",
    ),
    (
        "long2",
        "바쁜 점심시간, 든든한 한 끼가 필요하다면 정성껏 준비한 "
        "제육덮밥을 만나보세요. 따뜻한 밥과 매콤한 양념이 기분 좋은 "
        "포만감을 전해드립니다.",
    ),
    (
        "vlong1",
        "오늘 하루를 조금 더 특별하게 보내고 싶다면 봄날커피의 딸기 크림 "
        "라떼를 만나보세요. 생딸기의 산뜻한 향과 부드러운 크림, 은은한 "
        "커피의 조화가 바쁜 일상 속 작은 휴식을 선물합니다. 가까운 "
        "봄날커피 매장에서 지금 바로 즐겨보세요.",
    ),
    (
        "vlong2",
        "오늘 하루, 바쁘게 달려온 당신에게 가장 필요한 것은 무엇인가요. "
        "복잡한 도시의 소음을 잠시 뒤로하고, 향긋한 원두 향이 가득한 "
        "나만의 작은 아지트로 빠져보세요.\n\n"
        "카페 루미에르에서 정성껏 준비한 신메뉴, 시그니처 크림 라떼를 "
        "소개합니다. 고소한 최상급 원두의 깊은 풍미와 매일 아침 직송되는 "
        "부드러운 수제 크림이 만나, 한 입 머무는 순간 완벽한 조화를 "
        "선사합니다.\n\n"
        "지금 루미에르 멤버십 앱을 설치하시면, 신메뉴 수제 크림 라떼 "
        "오십 퍼센트 할인 쿠폰을 즉시 발급해 드립니다.\n\n"
        "오직 당신만을 위해 준비한 달콤한 휴식. 한 잔의 커피가 전하는 "
        "따뜻한 위로와 함께, 오늘 하루를 더욱 특별하게 채워보세요. "
        "당신이 머무는 모든 순간이 빛날 수 있도록, 카페 루미에르가 "
        "언제나 함께합니다.",
    ),
    (
        "num",
        "오늘 오후 2시부터 5시까지, 아메리카노 두 잔 구매 시 한 잔을 "
        "추가로 드립니다.",
    ),
    (
        "price",
        "이번 주 신메뉴 세트는 9,900원입니다. "
        "따뜻한 커피와 디저트를 함께 즐겨보세요.",
    ),
    (
        "sale",
        "포장 주문 고객에게는 전 메뉴 10퍼센트 할인 혜택을 드립니다.",
    ),
    (
        "eng",
        "부드러운 크림이 올라간 바닐라 라떼와 갓 구운 크루아상을 "
        "함께 즐겨보세요.",
    ),
    (
        "sign",
        "오늘만 준비한 달콤한 혜택! "
        "딸기 크림 라떼와 조각 케이크를 함께 만나보세요.",
    ),
)


@dataclass(frozen=True)
class TestCase:
    num: int
    voice: str
    tone: str
    text_type: str
    text: str
    repeat: int

    @property
    def cosyvoice_name(self) -> str:
        return f"{self.voice}_{self.tone}"

    @property
    def filename(self) -> str:
        return (
            f"{self.num:04d}_{self.voice}_{self.tone}_"
            f"{self.text_type}_r{self.repeat}.wav"
        )


def build_test_plan(repeats: int = 3) -> list[TestCase]:
    plan: list[TestCase] = []
    for text_type, text in TEXT_CASES:
        for voice, tone in VOICE_PRESETS:
            for repeat in range(1, repeats + 1):
                plan.append(
                    TestCase(
                        num=len(plan) + 1,
                        voice=voice,
                        tone=tone,
                        text_type=text_type,
                        text=text,
                        repeat=repeat,
                    )
                )
    return plan


def read_history(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.is_file():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise RuntimeError(
                f"CSV 컬럼이 예상과 다릅니다: {reader.fieldnames}; "
                f"예상 컬럼: {list(CSV_FIELDS)}"
            )
        return list(reader)


def validate_history(
    history: Iterable[dict[str, str]], plan: list[TestCase]
) -> list[dict[str, str]]:
    rows = list(history)
    if len(rows) > len(plan):
        raise RuntimeError(
            f"CSV 행 수({len(rows)})가 전체 테스트 계획({len(plan)})보다 많습니다."
        )
    for index, row in enumerate(rows):
        expected = plan[index]
        actual = (
            row.get("num", ""),
            row.get("voice", ""),
            row.get("tone", ""),
            row.get("text_type", ""),
        )
        wanted = (
            str(expected.num),
            expected.voice,
            expected.tone,
            expected.text_type,
        )
        if actual != wanted:
            raise RuntimeError(
                f"CSV {index + 2}행의 테스트 순서가 계획과 다릅니다. "
                f"현재={actual}, 예상={wanted}"
            )
    return rows


def wav_duration_seconds(audio_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()
    except (EOFError, wave.Error, ZeroDivisionError) as error:
        raise RuntimeError(f"응답 WAV 길이를 읽지 못했습니다: {error}") from error


def check_service(base_url: str, required_voice: str, timeout: float) -> None:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/health")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise RuntimeError(f"CosyVoice 상태를 확인하지 못했습니다: {error}") from error
    if not payload.get("ready"):
        raise RuntimeError(f"CosyVoice가 준비되지 않았습니다: {payload}")
    voices = payload.get("voices", [])
    if required_voice not in voices:
        raise RuntimeError(
            f"필요한 기준 음성 '{required_voice}'이 없습니다. 현재 음성: {voices}"
        )


def generate_audio(
    base_url: str,
    case: TestCase,
    speed: float,
    timeout: float,
) -> tuple[bytes, float]:
    body = json.dumps(
        {
            "input": case.text,
            "voice": case.cosyvoice_name,
            "speed": speed,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/tts",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            audio_bytes = response.read()
            resolved_voice = response.headers.get("X-BrandMate-Voice")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"CosyVoice 요청 실패 ({error.code}): {detail}"
        ) from error
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"CosyVoice 요청 실패: {error}") from error
    create_time = time.perf_counter() - started_at
    if not audio_bytes:
        raise RuntimeError("CosyVoice가 빈 음성 파일을 반환했습니다.")
    if resolved_voice and resolved_voice != case.cosyvoice_name:
        raise RuntimeError(
            f"요청 음성({case.cosyvoice_name})과 응답 음성({resolved_voice})이 다릅니다."
        )
    return audio_bytes, create_time


def append_result(
    csv_path: Path,
    case: TestCase,
    voice_time: float,
    create_time: float,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_path.is_file() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(
            {
                "num": case.num,
                "voice": case.voice,
                "tone": case.tone,
                "voice_time(s)": f"{voice_time:.3f}",
                "create_time(s)": f"{create_time:.3f}",
                "text_type": case.text_type,
            }
        )


def ensure_csv_writable(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with csv_path.open("a", encoding="utf-8", newline=""):
            pass
    except PermissionError as error:
        raise RuntimeError(
            f"CSV에 쓸 수 없습니다. Excel 등에서 파일을 닫아주세요: {csv_path}"
        ) from error


def persist_result(
    output_path: Path,
    audio_bytes: bytes,
    csv_path: Path,
    case: TestCase,
    voice_time: float,
    create_time: float,
) -> None:
    output_path.write_bytes(audio_bytes)
    try:
        append_result(csv_path, case, voice_time, create_time)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resume the BrandMate CosyVoice benchmark from its CSV."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise RuntimeError("--count는 1 이상이어야 합니다.")
    plan = build_test_plan()
    history = validate_history(read_history(args.csv), plan)
    remaining = plan[len(history) :]
    selected = remaining if args.all else remaining[: args.count]
    if not selected:
        print("모든 테스트가 이미 완료되었습니다.")
        return 0

    print(f"CSV: {args.csv}")
    print(f"WAV 저장 폴더: {args.output_dir}")
    print(f"완료: {len(history)}/{len(plan)}, 이번 실행: {len(selected)}건")
    for case in selected:
        print(
            f"  #{case.num} {case.cosyvoice_name} "
            f"{case.text_type} 반복 {case.repeat}"
        )
    if args.dry_run:
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ensure_csv_writable(args.csv)
    for case in selected:
        output_path = args.output_dir / case.filename
        if output_path.exists():
            raise RuntimeError(f"기존 WAV를 덮어쓰지 않습니다: {output_path}")
        check_service(args.base_url, case.cosyvoice_name, args.timeout)
        print(f"생성 중: #{case.num} {case.filename}")
        audio_bytes, create_time = generate_audio(
            args.base_url,
            case,
            args.speed,
            args.timeout,
        )
        voice_time = wav_duration_seconds(audio_bytes)
        persist_result(
            output_path,
            audio_bytes,
            args.csv,
            case,
            voice_time,
            create_time,
        )
        print(
            f"완료: 음성 {voice_time:.3f}초, 생성 {create_time:.3f}초, "
            f"저장 {output_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
