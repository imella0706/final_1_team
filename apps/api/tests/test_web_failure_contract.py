from pathlib import Path


WEB_SCRIPT = Path(__file__).resolve().parents[2] / "web" / "app.js"


def read_script() -> str:
    return WEB_SCRIPT.read_text(encoding="utf-8")


def test_web_accepts_structured_and_legacy_api_error_details() -> None:
    script = read_script()

    assert "const structuredDetail = isRecord(detail) ? detail : {};" in script
    assert 'typeof detail === "string" ? detail : ""' in script
    assert "this.stage = normalizeApiStage(stage);" in script
    assert "this.retryable = Boolean(retryable);" in script
    assert "this.detail = detail;" in script


def test_web_marks_the_reported_or_active_pipeline_stage() -> None:
    script = read_script()

    assert 'vision: "bridge"' in script
    assert "const activeIndex = pipelineItems.findIndex" in script
    assert "const failedStage = markPipelineFailure(error?.stage);" in script
    assert 'setStage(3, "error", "실패")' not in script
    assert "clearGeneratedState();" in script


def test_audio_failures_stay_local_and_require_an_available_provider() -> None:
    script = read_script()
    voice_handler = script.split(
        'generateVoiceButton?.addEventListener("click", async () => {',
        maxsplit=1,
    )[1].split(
        'downloadVoiceButton?.addEventListener("click", () => {',
        maxsplit=1,
    )[0]

    assert "cosyvoice?.configured && cosyvoice?.available" in script
    assert "openai?.configured && openai?.available" in script
    assert "provider.selected === true" in script
    assert 'selectedProvider.provider === "cosyvoice"' in script
    assert "cosyvoice?.fallback_enabled === true" in script
    assert 'userFacingErrorMessage(error, "audio")' in voice_handler
    assert "showError(" not in voice_handler
    assert "generateVoiceButton.disabled = !audioGenerationAvailable;" in voice_handler


def test_unverified_fallback_models_cannot_start_generation() -> None:
    script = read_script()

    assert "models.map((model) => ({ ...model, enabled: false, recommended: false }))" in script
    assert 'generateButton.firstElementChild.textContent = "모델 설정 확인 필요";' in script
    assert 'apiState.textContent = "API 모델 목록 확인 필요";' in script
