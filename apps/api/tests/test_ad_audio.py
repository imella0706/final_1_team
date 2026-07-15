import asyncio

import httpx
from pydantic import SecretStr

from app.core.config import settings
from app.extensions.ad_content.audio_service import generate_ad_audio
from app.extensions.ad_content.main import app
from app.extensions.ad_content.schemas import AdAudioRequest
from tests.api_client import post


def test_audio_generation_uses_configured_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["client_options"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(
                200,
                content=b"sample-mp3",
                headers={"content-type": "audio/mpeg"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(settings, "voice_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_model", "gpt-4o-mini-tts")
    monkeypatch.setattr(settings, "openai_tts_fallback_models", "tts-1-hd,tts-1")
    monkeypatch.setattr(
        "app.extensions.ad_content.audio_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = asyncio.run(
        generate_ad_audio(
            AdAudioRequest(
                input="오늘의 신메뉴를 만나보세요.",
                voice="coral",
                instructions="밝고 자연스럽게 말하세요.",
                speed=1.1,
            )
        )
    )

    assert result.model == "gpt-4o-mini-tts"
    assert result.fallback_used is False
    assert result.audio_base64 == "c2FtcGxlLW1wMw=="
    assert captured["url"].endswith("/audio/speech")
    assert captured["json"] == {
        "model": "gpt-4o-mini-tts",
        "input": "오늘의 신메뉴를 만나보세요.",
        "voice": "coral",
        "response_format": "mp3",
        "speed": 1.1,
        "instructions": "밝고 자연스럽게 말하세요.",
    }


def test_audio_generation_falls_back_for_unavailable_model(monkeypatch) -> None:
    payloads: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, json):
            del headers
            payloads.append(json)
            if len(payloads) == 1:
                return httpx.Response(
                    404,
                    json={"error": {"message": "model_not_found"}},
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(
                200,
                content=b"fallback-mp3",
                headers={"content-type": "audio/mpeg"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(settings, "voice_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_model", "gpt-4o-mini-tts")
    monkeypatch.setattr(settings, "openai_tts_fallback_models", "tts-1-hd,tts-1")
    monkeypatch.setattr(
        "app.extensions.ad_content.audio_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = asyncio.run(
        generate_ad_audio(
            AdAudioRequest(
                input="대체 모델 테스트",
                voice="nova",
                instructions="활기차게 말하세요.",
            )
        )
    )

    assert result.model == "tts-1-hd"
    assert result.requested_model == "gpt-4o-mini-tts"
    assert result.fallback_used is True
    assert [payload["model"] for payload in payloads] == ["gpt-4o-mini-tts", "tts-1-hd"]
    assert "instructions" not in payloads[1]


def test_audio_endpoint_reports_missing_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "voice_provider", "openai")

    response = post(
        app,
        "/api/v1/ad-content/audio/generate",
        json={"input": "음성 광고 테스트", "voice": "coral"},
    )

    assert response.status_code == 503
    assert "openai_api_key" in response.json()["detail"]


def test_cosyvoice_generation_returns_local_wav(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, json, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return httpx.Response(
                200,
                content=b"local-wav",
                headers={
                    "content-type": "audio/wav",
                    "x-brandmate-model": "Fun-CosyVoice3-0.5B-2512",
                    "x-brandmate-voice": "default",
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(settings, "voice_provider", "cosyvoice")
    monkeypatch.setattr(settings, "cosyvoice_base_url", "http://cosyvoice.test:50000")
    monkeypatch.setattr(
        "app.extensions.ad_content.audio_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = asyncio.run(
        generate_ad_audio(
            AdAudioRequest(input="로컬 음성 테스트", voice="coral", speed=0.9)
        )
    )

    assert result.provider == "cosyvoice"
    assert result.requested_provider == "cosyvoice"
    assert result.fallback_used is False
    assert result.media_type == "audio/wav"
    assert result.voice == "default"
    assert captured["url"] == "http://cosyvoice.test:50000/v1/tts"
    assert captured["json"]["speed"] == 0.9


def test_cosyvoice_failure_falls_back_to_openai(monkeypatch) -> None:
    requested_urls: list[str] = []
    requested_payloads: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, json, headers=None):
            del headers
            requested_urls.append(url)
            requested_payloads.append(json)
            if "cosyvoice.test" in url:
                return httpx.Response(
                    503,
                    json={"detail": "모델 준비 중"},
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(
                200,
                content=b"openai-mp3",
                headers={"content-type": "audio/mpeg"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(settings, "voice_provider", "cosyvoice")
    monkeypatch.setattr(settings, "cosyvoice_base_url", "http://cosyvoice.test:50000")
    monkeypatch.setattr(settings, "cosyvoice_fallback_to_openai", True)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(settings, "openai_tts_model", "gpt-4o-mini-tts")
    monkeypatch.setattr(settings, "openai_tts_fallback_models", "tts-1-hd,tts-1")
    monkeypatch.setattr(
        "app.extensions.ad_content.audio_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    result = asyncio.run(
        generate_ad_audio(AdAudioRequest(input="폴백 테스트", voice="default"))
    )

    assert result.provider == "openai"
    assert result.requested_provider == "cosyvoice"
    assert result.fallback_used is True
    assert requested_urls == [
        "http://cosyvoice.test:50000/v1/tts",
        "https://api.openai.com/v1/audio/speech",
    ]
    assert requested_payloads[0]["voice"] == "default"
    assert requested_payloads[1]["voice"] == "coral"
    assert result.voice == "coral"
