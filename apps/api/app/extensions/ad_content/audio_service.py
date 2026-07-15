import base64
from time import perf_counter

import httpx

from app.core.config import settings
from app.extensions.ad_content.schemas import (
    AdAudioRequest,
    AdAudioResponse,
    AudioProviderStatus,
)


class AudioModelNotConfiguredError(RuntimeError):
    pass


class AudioModelProviderError(RuntimeError):
    pass


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
    except httpx.HTTPError as error:
        raise AudioModelProviderError(
            f"CosyVoice 서버에 연결하지 못했습니다: {type(error).__name__}"
        ) from error

    if not response.is_success:
        raise AudioModelProviderError(_provider_message(response, "CosyVoice"))
    if not response.content:
        raise AudioModelProviderError("CosyVoice가 빈 음성 파일을 반환했습니다.")

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
            "openai_api_key가 없습니다. API 서버의 .env를 설정해주세요."
        )

    models = _tts_models()
    if not models:
        raise AudioModelNotConfiguredError("OpenAI TTS 모델이 설정되지 않았습니다.")

    endpoint = f"{settings.openai_base_url.rstrip('/')}/audio/speech"
    response_format = settings.openai_tts_format.strip().lower() or "mp3"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    started_at = perf_counter()
    errors: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=settings.openai_tts_timeout_seconds) as client:
            for index, model in enumerate(models):
                payload: dict[str, object] = {
                    "model": model,
                    "input": request.input,
                    "voice": request.voice or settings.openai_tts_voice,
                    "response_format": response_format,
                    "speed": request.speed,
                }
                if request.instructions and not model.startswith("tts-1"):
                    payload["instructions"] = request.instructions

                response = await client.post(endpoint, headers=headers, json=payload)
                if response.is_success:
                    if not response.content:
                        raise AudioModelProviderError(
                            f"{model} 모델이 빈 음성 파일을 반환했습니다."
                        )
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

                message = _provider_message(response, "OpenAI Speech")
                errors.append(f"{model}: {message}")
                can_fallback = response.status_code in {400, 403, 404} and index < len(models) - 1
                if not can_fallback:
                    raise AudioModelProviderError(message)
    except AudioModelProviderError:
        raise
    except httpx.HTTPError as error:
        raise AudioModelProviderError(
            f"OpenAI Speech API에 연결하지 못했습니다: {type(error).__name__}"
        ) from error

    raise AudioModelProviderError("사용 가능한 TTS 모델이 없습니다. " + " | ".join(errors))


async def generate_ad_audio(request: AdAudioRequest) -> AdAudioResponse:
    provider = settings.voice_provider.strip().lower()
    if provider not in {"openai", "cosyvoice"}:
        raise AudioModelNotConfiguredError(
            f"지원하지 않는 voice_provider입니다: {settings.voice_provider}"
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
        except (AudioModelNotConfiguredError, AudioModelProviderError) as openai_error:
            raise AudioModelProviderError(
                f"CosyVoice 실패: {cosyvoice_error}; OpenAI 폴백 실패: {openai_error}"
            ) from openai_error


async def list_audio_provider_statuses() -> list[AudioProviderStatus]:
    cosyvoice_status = AudioProviderStatus(
        provider="cosyvoice",
        configured=bool(settings.cosyvoice_base_url.strip()),
        available=False,
        model=settings.cosyvoice_model,
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
            detail=(
                "OpenAI API 키가 설정되었습니다."
                if openai_configured
                else "OpenAI API 키가 없습니다."
            ),
        ),
    ]
