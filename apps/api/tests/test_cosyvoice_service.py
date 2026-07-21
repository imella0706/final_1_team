import importlib.util
from pathlib import Path


SERVICE_FILE = (
    Path(__file__).resolve().parents[3] / "services" / "cosyvoice" / "server.py"
)
SPEC = importlib.util.spec_from_file_location("brandmate_cosyvoice_server", SERVICE_FILE)
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def test_instruction_adds_speed_and_end_marker() -> None:
    instruction = SERVER.CosyVoiceEngine._instruction("활기차게 말하세요.", 1.2)

    assert "활기차게" in instruction
    assert "20% 빠르게" in instruction
    assert instruction.endswith("<|endofprompt|>")


def test_cross_lingual_text_contains_only_system_marker_and_script() -> None:
    script = "오늘 준비한 신메뉴를 만나보세요."

    tts_text = SERVER.CosyVoiceEngine._cross_lingual_text(script)

    assert tts_text == f"You are a helpful assistant.<|endofprompt|>{script}"
    assert "광고 성우" not in tts_text


def test_generate_uses_cross_lingual_mode_without_instructions(
    tmp_path, monkeypatch
) -> None:
    calls: list[tuple[str, str, bool, float]] = []

    class FakeModel:
        sample_rate = 24000

        def inference_cross_lingual(
            self, text: str, voice_path: str, stream: bool, speed: float
        ):
            calls.append((text, voice_path, stream, speed))
            yield {"tts_speech": object()}

    engine = SERVER.CosyVoiceEngine()
    engine.voice_dir = tmp_path
    (tmp_path / "default.wav").write_bytes(b"wav")
    engine._model = FakeModel()
    monkeypatch.setattr(engine, "_wav_bytes", lambda speech, sample_rate: b"audio")

    audio, voice = engine.generate(
        SERVER.TTSRequest(
            input="Sale starts now.",
            instructions="Read this instruction aloud.",
            speed=1.1,
        )
    )

    assert audio == b"audio"
    assert voice == "default"
    assert calls == [
        (
            "You are a helpful assistant.<|endofprompt|>Sale starts now.",
            str(tmp_path / "default.wav"),
            False,
            1.1,
        )
    ]


def test_voice_path_uses_default_voice(tmp_path) -> None:
    engine = SERVER.CosyVoiceEngine()
    engine.voice_dir = tmp_path
    default_voice = tmp_path / "default.wav"
    default_voice.write_bytes(b"wav")

    voice_name, voice_path = engine._voice_path("missing-voice")

    assert voice_name == "default"
    assert voice_path == default_voice


def test_normalize_korean_tts_text_handles_advertising_numbers() -> None:
    text = "평일 오전 11시부터 오후 2시까지 6,500원 메뉴를 10% 할인합니다."

    normalized = SERVER.normalize_korean_tts_text(text)

    assert normalized == (
        "평일 오전 열한 시부터 오후 두 시까지 육천오백 원 메뉴를 십 퍼센트 할인합니다."
    )


def test_normalize_korean_tts_text_handles_time_and_counters() -> None:
    text = "오전 11:30에 음료 2잔과 디저트 3개를 준비합니다."

    normalized = SERVER.normalize_korean_tts_text(text)

    assert normalized == "오전 열한 시 삼십 분에 음료 두 잔과 디저트 세 개를 준비합니다."
