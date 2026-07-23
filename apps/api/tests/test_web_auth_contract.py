from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


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

    assert "media-src 'self' data: blob:" in markup
    assert "URL.createObjectURL(audioBlob)" in script
    assert "voicePlayer.src = generatedVoiceObjectUrl" in script
    assert "voicePlayer.load()" in script
