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
        ]
        if speed > 1.05:
            parts.append(f"기본보다 약 {round((speed - 1) * 100)}% 빠르게 말하세요.")
        elif speed < 0.95:
            parts.append(f"기본보다 약 {round((1 - speed) * 100)}% 천천히 말하세요.")
        return " ".join(parts).strip() + "<|endofprompt|>"

    @staticmethod
    def _wav_bytes(speech: Any, sample_rate: int) -> bytes:
        import torch

        samples = speech.detach().float().cpu().squeeze().clamp(-1, 1)
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
        instruction = self._instruction(request.instructions, request.speed)

        with self._generation_lock:
            try:
                chunks = [
                    result["tts_speech"]
                    for result in model.inference_instruct2(
                        request.input,
                        instruction,
                        str(voice_path),
                        stream=False,
                    )
                ]
            except Exception as error:
                raise RuntimeError(
                    f"CosyVoice 음성 생성 실패: {type(error).__name__}: {error}"
                ) from error

        if not chunks:
            raise RuntimeError("CosyVoice가 빈 음성을 반환했습니다.")

        import torch

        speech = torch.cat(chunks, dim=-1) if len(chunks) > 1 else chunks[0]
        return self._wav_bytes(speech, model.sample_rate), resolved_voice

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
            "voices": sorted(path.stem for path in self.voice_dir.glob("*.wav")),
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
            "X-Generation-Latency-Ms": str(round((perf_counter() - started_at) * 1000)),
        },
    )
