import base64
import logging
from time import perf_counter

import httpx

from app.core.config import settings
from app.extensions.ad_content.schemas import (
    AdAudioRequest,
    AdAudioResponse,
    AudioProviderStatus,
)

logger = logging.getLogger("brandmate.ad_content.audio")


class AudioModelNotConfiguredError(RuntimeError):
    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class AudioModelProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        upstream_status: int | None = None,
        timed_out: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.upstream_status = upstream_status
        self.timed_out = timed_out


OPENAI_TTS_VOICES = {
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
}


def _secret_value(secret: object | None) -> str | None:
    if secret is None:
        return None
    get_secret_value = getattr(secret, "get_secret_value", None)
    return get_secret_value() if callable(get_secret_value) else str(secret)


def _tts_models() -> list[str]:
    candidates = [
        settings.openai_tts_model,
        *settings.openai_tts_fallback_models.split(","),
    ]
    return list(dict.fromkeys(model.strip() for model in candidates if model.strip()))


def _openai_voice(requested_voice: str | None) -> str:
    candidate = (requested_voice or settings.openai_tts_voice).strip().lower()
    if candidate in OPENAI_TTS_VOICES:
        return candidate
    configured = settings.openai_tts_voice.strip().lower()
    return configured if configured in OPENAI_TTS_VOICES else "coral"


def _media_type(response_format: str, response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    if content_type.startswith("audio/"):
        return content_type
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(response_format, "audio/mpeg")


def _provider_message(response: httpx.Response, provider: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"{provider} API error ({response.status_code})"
    if not isinstance(body, dict):
        return f"{provider} API error ({response.status_code})"
    error = body.get("error", {})
    detail = body.get("detail")
    message = error.get("message") if isinstance(error, dict) else None
    return str(message or detail or f"{provider} API error ({response.status_code})")


def _log_provider_failure(
    provider: str,
    *,
    status_code: int | None = None,
    error_type: str | None = None,
) -> None:
    # Do not log response bodies, request payloads, keys, or provider messages.
    logger.warning(
        "Audio provider failed provider=%s status=%s error_type=%s",
        provider,
        status_code if status_code is not None else "network",
        error_type or "HTTPError",
    )


def _can_try_fallback_model(status_code: int, index: int, model_count: int) -> bool:
    if index >= model_count - 1:
        return False
    return status_code in {400, 403, 404, 408, 409, 422, 429} or status_code >= 500


async def _generate_cosyvoice_audio(request: AdAudioRequest) -> AdAudioResponse:
    endpoint = f"{settings.cosyvoice_base_url.rstrip('/')}/v1/tts"
    started_at = perf_counter()
    payload = {
        "input": request.input,
        "voice": request.voice or settings.openai_tts_voice,
        "instructions": request.instructions,
        "speed": request.speed,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.cosyvoice_timeout_seconds) as client:
            response = await client.post(endpoint, json=payload)
    except httpx.TimeoutException as error:
        _log_provider_failure("cosyvoice", error_type=type(error).__name__)
        raise AudioModelProviderError(
            "CosyVoice 요청 시간이 제한을 초과했습니다.",
            provider="cosyvoice",
            timed_out=True,
        ) from error
    except httpx.HTTPError as error:
        _log_provider_failure("cosyvoice", error_type=type(error).__name__)
        raise AudioModelProviderError(
            f"CosyVoice 서버에 연결하지 못했습니다: {type(error).__name__}",
            provider="cosyvoice",
        ) from error

    if not response.is_success:
        _log_provider_failure("cosyvoice", status_code=response.status_code)
        raise AudioModelProviderError(
            _provider_message(response, "CosyVoice"),
            provider="cosyvoice",
            upstream_status=response.status_code,
        )
    if not response.content:
        _log_provider_failure("cosyvoice", error_type="EmptyAudioResponse")
        raise AudioModelProviderError(
            "CosyVoice가 빈 음성 파일을 반환했습니다.",
            provider="cosyvoice",
        )

    model = response.headers.get("x-brandmate-model", settings.cosyvoice_model)
    voice = response.headers.get("x-brandmate-voice", str(payload["voice"]))
    return AdAudioResponse(
        provider="cosyvoice",
        requested_provider="cosyvoice",
        model=model,
        requested_model=settings.cosyvoice_model,
        fallback_used=False,
        voice=voice,
        media_type=_media_type("wav", response),
        audio_base64=base64.b64encode(response.content).decode("ascii"),
        latency_ms=round((perf_counter() - started_at) * 1000),
    )


async def _generate_openai_audio(
    request: AdAudioRequest,
    *,
    requested_provider: str = "openai",
) -> AdAudioResponse:
    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        raise AudioModelNotConfiguredError(
            "openai_api_key가 없습니다. API 서버의 .env를 설정해주세요.",
            provider="openai",
        )

    models = _tts_models()
    if not models:
        raise AudioModelNotConfiguredError(
            "OpenAI TTS 모델이 설정되지 않았습니다.",
            provider="openai",
        )

    endpoint = f"{settings.openai_base_url.rstrip('/')}/audio/speech"
    response_format = settings.openai_tts_format.strip().lower() or "mp3"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    started_at = perf_counter()
    errors: list[str] = []
    failure_statuses: list[int] = []

    async with httpx.AsyncClient(timeout=settings.openai_tts_timeout_seconds) as client:
        for index, model in enumerate(models):
            payload: dict[str, object] = {
                "model": model,
                "input": request.input,
                "voice": _openai_voice(request.voice),
                "response_format": response_format,
                "speed": request.speed,
            }
            if request.instructions and not model.startswith("tts-1"):
                payload["instructions"] = request.instructions

            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except httpx.TimeoutException as error:
                _log_provider_failure("openai", error_type=type(error).__name__)
                raise AudioModelProviderError(
                    "OpenAI Speech 요청 시간이 제한을 초과했습니다.",
                    provider="openai",
                    timed_out=True,
                ) from error
            except httpx.HTTPError as error:
                _log_provider_failure("openai", error_type=type(error).__name__)
                raise AudioModelProviderError(
                    f"OpenAI Speech API에 연결하지 못했습니다: {type(error).__name__}",
                    provider="openai",
                ) from error

            if response.is_success:
                if response.content:
                    return AdAudioResponse(
                        provider="openai",
                        requested_provider=requested_provider,
                        model=model,
                        requested_model=models[0],
                        fallback_used=requested_provider != "openai" or index > 0,
                        voice=str(payload["voice"]),
                        media_type=_media_type(response_format, response),
                        audio_base64=base64.b64encode(response.content).decode("ascii"),
                        latency_ms=round((perf_counter() - started_at) * 1000),
                    )
                _log_provider_failure("openai", error_type="EmptyAudioResponse")
                message = f"{model} 모델이 빈 음성 파일을 반환했습니다."
                errors.append(message)
                if index < len(models) - 1:
                    continue
                raise AudioModelProviderError(message, provider="openai")

            _log_provider_failure("openai", status_code=response.status_code)
            message = _provider_message(response, "OpenAI Speech")
            errors.append(f"{model}: {message}")
            failure_statuses.append(response.status_code)
            if _can_try_fallback_model(response.status_code, index, len(models)):
                continue

            effective_status = (
                429 if 429 in failure_statuses else response.status_code
            )
            raise AudioModelProviderError(
                message,
                provider="openai",
                upstream_status=effective_status,
            )

    effective_status = 429 if 429 in failure_statuses else (
        failure_statuses[-1] if failure_statuses else None
    )
    raise AudioModelProviderError(
        "사용 가능한 TTS 모델이 없습니다. " + " | ".join(errors),
        provider="openai",
        upstream_status=effective_status,
    )


async def generate_ad_audio(request: AdAudioRequest) -> AdAudioResponse:
    provider = settings.voice_provider.strip().lower()
    if provider not in {"openai", "cosyvoice"}:
        raise AudioModelNotConfiguredError(
            f"지원하지 않는 voice_provider입니다: {settings.voice_provider}",
            provider=provider or None,
        )

    if provider == "openai":
        return await _generate_openai_audio(request)

    try:
        return await _generate_cosyvoice_audio(request)
    except AudioModelProviderError as cosyvoice_error:
        if not settings.cosyvoice_fallback_to_openai:
            raise
        try:
            return await _generate_openai_audio(request, requested_provider="cosyvoice")
        except AudioModelNotConfiguredError:
            # Preserve configuration errors so the API returns 503 rather than
            # misclassifying an unavailable fallback as an upstream 502.
            raise
        except AudioModelProviderError as openai_error:
            raise AudioModelProviderError(
                f"CosyVoice 실패: {cosyvoice_error}; OpenAI 폴백 실패: {openai_error}",
                provider="openai",
                upstream_status=openai_error.upstream_status,
                timed_out=openai_error.timed_out,
            ) from openai_error


async def list_audio_provider_statuses() -> list[AudioProviderStatus]:
    selected_provider = settings.voice_provider.strip().lower()
    cosyvoice_status = AudioProviderStatus(
        provider="cosyvoice",
        configured=bool(settings.cosyvoice_base_url.strip()),
        available=False,
        model=settings.cosyvoice_model,
        selected=selected_provider == "cosyvoice",
        fallback_enabled=settings.cosyvoice_fallback_to_openai,
        detail="CosyVoice 서버에 연결할 수 없습니다.",
    )
    if cosyvoice_status.configured:
        try:
            async with httpx.AsyncClient(
                timeout=settings.cosyvoice_health_timeout_seconds
            ) as client:
                response = await client.get(
                    f"{settings.cosyvoice_base_url.rstrip('/')}/health"
                )
            if response.is_success:
                body = response.json()
                ready = bool(body.get("ready", False)) if isinstance(body, dict) else False
                cosyvoice_status.available = ready
                if isinstance(body, dict) and isinstance(body.get("voices"), list):
                    cosyvoice_status.voices = [
                        str(voice) for voice in body["voices"] if str(voice).strip()
                    ]
                if isinstance(body, dict):
                    cosyvoice_status.instructions_supported = bool(
                        body.get("instructions_supported", False)
                    )
                cosyvoice_status.detail = (
                    "CosyVoice 모델이 준비되었습니다."
                    if ready
                    else str(body.get("detail", "모델 또는 참조 음성이 준비되지 않았습니다."))
                )
        except (httpx.HTTPError, ValueError):
            pass

    openai_configured = bool(_secret_value(settings.openai_api_key))
    return [
        cosyvoice_status,
        AudioProviderStatus(
            provider="openai",
            configured=openai_configured,
            available=openai_configured,
            model=settings.openai_tts_model,
            selected=selected_provider == "openai",
            detail=(
                "OpenAI API 키가 설정되었습니다."
                if openai_configured
                else "OpenAI API 키가 없습니다."
            ),
        ),
    ]
