from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
PROJECT_ROOT = WEB_ROOT.parents[1]
CADDY_CONFIGS = (
    PROJECT_ROOT / "deploy" / "caddy" / "Caddyfile",
    PROJECT_ROOT / "deploy" / "caddy" / "Caddyfile.tunnel",
)


def test_web_keeps_tokens_out_of_browser_storage_and_coordinates_refresh() -> None:
    # [Design Intent] This static guard catches the highest-risk frontend auth
    # regressions without requiring a browser runtime in the Python test image.
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert 'navigator.locks.request("brandmate-auth-refresh"' in script
    assert 'credentials: "include"' in script


def test_web_exposes_public_mvp_recovery_and_security_controls() -> None:
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    for element_id in (
        'id="forgot-password-form"',
        'id="reset-password-form"',
        'id="security-dialog"',
        'id="session-list"',
        'id="change-password-form"',
    ):
        assert element_id in markup


def test_web_allows_and_uses_blob_urls_for_generated_audio() -> None:
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert markup.count('http-equiv="Content-Security-Policy"') == 1
    assert markup.count('content="default-src') == 1
    assert "media-src 'self' data: blob:" in markup
    for config_path in CADDY_CONFIGS:
        proxy_config = config_path.read_text(encoding="utf-8")
        assert "media-src 'self' data: blob:" in proxy_config
    assert "URL.createObjectURL(audioBlob)" in script
    assert "voicePlayer.src = generatedVoiceObjectUrl" in script
    assert "voicePlayer.load()" in script


def test_web_omits_acting_instruction_input_and_payload() -> None:
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="voice-instructions"' not in markup
    assert "연기 지시" not in markup
    assert "voiceInstructions" not in script


def test_web_labels_local_gender_and_emotion_voice_presets() -> None:
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for voice, label in (
        ("man_happy", "남성 · 기쁨"),
        ("man_serious", "남성 · 진지함"),
        ("woman_happy", "여성 · 기쁨"),
        ("woman_serious", "여성 · 진지함"),
        ("woman_whisper", "여성 · 속삭임"),
    ):
        assert f'["{voice}", "{label}"]' in script
    assert '["man_whisper", "남성 · 속삭임"]' not in script
    assert 'new Set(["man_whisper", "man_whisper2"])' in script
