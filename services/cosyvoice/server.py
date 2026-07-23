import asyncio
import io
import os
import re
import sys
import threading
import wave
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field


SERVICE_DIR = Path(__file__).resolve().parent
VOICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
TTS_SEGMENT_MAX_CHARS = 180
VOICE_OUTPUT_GAINS = {
    "man_whisper": 0.80,
    "woman_whisper": 0.63,
}
VOICE_REFERENCE_OVERRIDES = {
    "man_whisper": "man_whisper2",
}
INTERNAL_REFERENCE_VOICES = frozenset(VOICE_REFERENCE_OVERRIDES.values())
VOICE_STYLE_INSTRUCTIONS = {
    "woman_whisper": (
        "You are a helpful assistant. "
        "请用轻声耳语、贴近听众且自然的方式说这句话。<|endofprompt|>"
    ),
}
SINO_DIGITS = ("영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구")
NATIVE_ONES = ("", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")
NATIVE_TENS = {
    1: "열",
    2: "스물",
    3: "서른",
    4: "마흔",
    5: "쉰",
    6: "예순",
    7: "일흔",
    8: "여든",
    9: "아흔",
}


def _sino_korean_under_10000(value: int) -> str:
    parts: list[str] = []
    for divisor, unit in ((1000, "천"), (100, "백"), (10, "십")):
        digit, value = divmod(value, divisor)
        if digit:
            parts.append(("" if digit == 1 else SINO_DIGITS[digit]) + unit)
    if value:
        parts.append(SINO_DIGITS[value])
    return "".join(parts)


def _sino_korean_integer(value: int) -> str:
    if value == 0:
        return SINO_DIGITS[0]
    if value < 0:
        return "마이너스 " + _sino_korean_integer(-value)
    parts: list[str] = []
    groups: list[int] = []
    while value:
        value, group = divmod(value, 10000)
        groups.append(group)
    large_units = ("", "만", "억", "조")
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group:
            parts.append(_sino_korean_under_10000(group) + large_units[index])
    return "".join(parts)


def _native_korean_integer(value: int) -> str:
    if not 1 <= value <= 99:
        return _sino_korean_integer(value)
    if value == 20:
        return "스무"
    tens, ones = divmod(value, 10)
    return (NATIVE_TENS.get(tens, "") + NATIVE_ONES[ones]).strip()


def _decimal_korean(raw_value: str) -> str:
    integer, dot, decimal = raw_value.replace(",", "").partition(".")
    spoken = _sino_korean_integer(int(integer))
    if dot:
        spoken += " 점 " + " ".join(SINO_DIGITS[int(digit)] for digit in decimal)
    return spoken


def normalize_korean_tts_text(text: str) -> str:
    normalized = re.sub(r"(?<!\d)1\s*\+\s*1(?!\d)", "원 플러스 원", text)
    normalized = re.sub(
        r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)",
        lambda match: (
            f"{_native_korean_integer(int(match.group(1)))} 시 "
            f"{_sino_korean_integer(int(match.group(2)))} 분"
        ),
        normalized,
    )
    normalized = re.sub(
        r"(?<!\d)(\d{1,2})\s*시",
        lambda match: f"{_native_korean_integer(int(match.group(1)))} 시",
        normalized,
    )
    normalized = re.sub(
        r"(?<!\d)(\d{1,2})\s*분",
        lambda match: f"{_sino_korean_integer(int(match.group(1)))} 분",
        normalized,
    )
    normalized = re.sub(
        r"(?<![\d.])([\d,]+(?:\.\d+)?)\s*%",
        lambda match: f"{_decimal_korean(match.group(1))} 퍼센트",
        normalized,
    )
    normalized = re.sub(
        r"(?<!\d)([\d,]+)\s*원",
        lambda match: f"{_sino_korean_integer(int(match.group(1).replace(',', '')))} 원",
        normalized,
    )
    normalized = re.sub(
        r"(?<!\d)(\d+)\s*(개|명|잔|병|번|가지|세트)",
        lambda match: f"{_native_korean_integer(int(match.group(1)))} {match.group(2)}",
        normalized,
    )
    normalized = re.sub(
        r"(?<!\d)(\d+)\s*(년|월|일|초)",
        lambda match: f"{_sino_korean_integer(int(match.group(1)))} {match.group(2)}",
        normalized,
    )
    return normalized


def split_tts_text(text: str, max_chars: int = TTS_SEGMENT_MAX_CHARS) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", text.strip())
        if sentence.strip()
    ]
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        remaining = sentence
        while len(remaining) > max_chars:
            split_at = remaining.rfind(" ", 0, max_chars + 1)
            if split_at < max_chars // 2:
                split_at = max_chars
            prefix = remaining[:split_at].strip()
            if current:
                chunks.append(current)
                current = ""
            if prefix:
                chunks.append(prefix)
            remaining = remaining[split_at:].strip()

        if not remaining:
            continue
        candidate = f"{current} {remaining}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = remaining
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks or [text.strip()]


class TTSRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4096)
    voice: str = Field(default="default", min_length=1, max_length=80)
    instructions: str | None = Field(default=None, max_length=1000)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


class CosyVoiceEngine:
    def __init__(self) -> None:
        self.repo_dir = Path(
            os.getenv("COSYVOICE_REPO_DIR", SERVICE_DIR / ".runtime" / "CosyVoice")
        ).expanduser()
        configured_model = Path(
            os.getenv("COSYVOICE_MODEL_DIR", "pretrained_models/Fun-CosyVoice3-0.5B")
        ).expanduser()
        self.model_dir = (
            configured_model
            if configured_model.is_absolute()
            else self.repo_dir / configured_model
        )
        self.voice_dir = Path(
            os.getenv("COSYVOICE_VOICE_DIR", SERVICE_DIR / "voices")
        ).expanduser()
        self.model_name = os.getenv(
            "COSYVOICE_MODEL_NAME", "Fun-CosyVoice3-0.5B-2512"
        )
        configured_mode = os.getenv(
            "COSYVOICE_INFERENCE_MODE", "cross_lingual"
        ).strip().lower()
        self.inference_mode = (
            configured_mode
            if configured_mode in {"cross_lingual", "instruct"}
            else "cross_lingual"
        )
        self._model: Any | None = None
        self._load_error = ""
        self._load_lock = threading.Lock()
        self._generation_lock = threading.Lock()

    def _voice_path(self, voice: str) -> tuple[str, Path]:
        safe_voice = voice if VOICE_NAME_PATTERN.fullmatch(voice) else "default"
        candidate = self.voice_dir / f"{safe_voice}.wav"
        if candidate.is_file():
            return safe_voice, candidate
        default_voice = self.voice_dir / "default.wav"
        if default_voice.is_file():
            return "default", default_voice
        raise RuntimeError(
            f"참조 음성이 없습니다. {self.voice_dir / 'default.wav'} 파일을 추가해주세요."
        )

    def _reference_voice_path(self, voice: str, selected_path: Path) -> Path:
        reference_voice = VOICE_REFERENCE_OVERRIDES.get(voice)
        if not reference_voice:
            return selected_path
        candidate = self.voice_dir / f"{reference_voice}.wav"
        return candidate if candidate.is_file() else selected_path

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            if not self.repo_dir.is_dir():
                raise RuntimeError(f"CosyVoice 저장소를 찾을 수 없습니다: {self.repo_dir}")
            if not self.model_dir.is_dir():
                raise RuntimeError(f"CosyVoice 모델을 찾을 수 없습니다: {self.model_dir}")

            matcha_dir = self.repo_dir / "third_party" / "Matcha-TTS"
            for import_path in (self.repo_dir, matcha_dir):
                import_value = str(import_path)
                if import_value not in sys.path:
                    sys.path.insert(0, import_value)

            try:
                from cosyvoice.cli.cosyvoice import AutoModel

                self._model = AutoModel(model_dir=str(self.model_dir))
                self._load_error = ""
            except Exception as error:
                self._load_error = f"{type(error).__name__}: {error}"
                raise RuntimeError(f"CosyVoice 모델 로딩 실패: {self._load_error}") from error
        return self._model

    @staticmethod
    def _instruction(instructions: str | None, speed: float) -> str:
        parts = [
            "You are a helpful assistant.",
            instructions or "한국어 광고 성우처럼 밝고 자연스럽게 말하세요.",
            "숫자, 시간, 가격과 단위를 영어로 바꾸지 말고 한국어로 읽으세요.",
        ]
        if speed > 1.05:
            parts.append(f"기본보다 약 {round((speed - 1) * 100)}% 빠르게 말하세요.")
        elif speed < 0.95:
            parts.append(f"기본보다 약 {round((1 - speed) * 100)}% 천천히 말하세요.")
        return " ".join(parts).strip() + "<|endofprompt|>"

    @staticmethod
    def _cross_lingual_text(tts_text: str) -> str:
        return f"You are a helpful assistant.<|endofprompt|>{tts_text}"

    @staticmethod
    def _wav_bytes(speech: Any, sample_rate: int, gain: float = 1.0) -> bytes:
        import torch

        samples = (speech.detach().float().cpu().squeeze() * gain).clamp(-1, 1)
        pcm = (samples * 32767).to(torch.int16).numpy().tobytes()
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()

    def generate(self, request: TTSRequest) -> tuple[bytes, str]:
        model = self._ensure_model()
        resolved_voice, voice_path = self._voice_path(request.voice)
        tts_text = normalize_korean_tts_text(request.input)
        tts_segments = split_tts_text(tts_text)
        preset_instruction = VOICE_STYLE_INSTRUCTIONS.get(resolved_voice)

        with self._generation_lock:
            voice_path = self._reference_voice_path(resolved_voice, voice_path)
            try:
                chunks = []
                for segment in tts_segments:
                    if self.inference_mode == "instruct" or preset_instruction:
                        generator = model.inference_instruct2(
                            segment,
                            preset_instruction
                            or self._instruction(request.instructions, request.speed),
                            str(voice_path),
                            stream=False,
                            speed=request.speed,
                        )
                    else:
                        generator = model.inference_cross_lingual(
                            self._cross_lingual_text(segment),
                            str(voice_path),
                            stream=False,
                            speed=request.speed,
                        )
                    chunks.extend(result["tts_speech"] for result in generator)
            except Exception as error:
                raise RuntimeError(
                    f"CosyVoice 음성 생성 실패: {type(error).__name__}: {error}"
                ) from error

        if not chunks:
            raise RuntimeError("CosyVoice가 빈 음성을 반환했습니다.")

        if len(chunks) > 1:
            import torch

            speech = torch.cat(chunks, dim=-1)
        else:
            speech = chunks[0]
        output_gain = VOICE_OUTPUT_GAINS.get(resolved_voice, 1.0)
        return self._wav_bytes(speech, model.sample_rate, output_gain), resolved_voice

    def health(self) -> dict[str, object]:
        model_present = self.model_dir.is_dir()
        voice_present = (self.voice_dir / "default.wav").is_file() or any(
            self.voice_dir.glob("*.wav")
        )
        ready = self.repo_dir.is_dir() and model_present and voice_present and not self._load_error
        missing: list[str] = []
        if not self.repo_dir.is_dir():
            missing.append("CosyVoice 저장소")
        if not model_present:
            missing.append("모델")
        if not voice_present:
            missing.append("참조 음성")
        detail = "준비됨" if ready else f"준비 필요: {', '.join(missing) or self._load_error}"
        return {
            "status": "ok",
            "ready": ready,
            "model_loaded": self._model is not None,
            "model": self.model_name,
            "inference_mode": self.inference_mode,
            "instructions_supported": self.inference_mode == "instruct",
            "voices": sorted(
                path.stem
                for path in self.voice_dir.glob("*.wav")
                if path.stem not in INTERNAL_REFERENCE_VOICES
            ),
            "detail": detail,
        }


engine = CosyVoiceEngine()
generation_semaphore = asyncio.Semaphore(1)
app = FastAPI(title="BrandMate CosyVoice Service")


@app.get("/health")
async def health() -> dict[str, object]:
    return engine.health()


@app.post("/v1/tts")
async def generate_tts(request: TTSRequest) -> Response:
    started_at = perf_counter()
    try:
        async with generation_semaphore:
            audio_bytes, resolved_voice = await asyncio.to_thread(engine.generate, request)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "X-BrandMate-Model": engine.model_name,
            "X-BrandMate-Voice": resolved_voice,
            "X-BrandMate-Inference-Mode": engine.inference_mode,
            "X-Generation-Latency-Ms": str(round((perf_counter() - started_at) * 1000)),
        },
    )
