import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


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
    engine.inference_mode = "cross_lingual"
    engine.voice_dir = tmp_path
    (tmp_path / "default.wav").write_bytes(b"wav")
    engine._model = FakeModel()
    monkeypatch.setattr(
        engine, "_wav_bytes", lambda speech, sample_rate, gain=1.0: b"audio"
    )

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


def test_generate_uses_instruct_mode_with_separate_acting_direction(
    tmp_path, monkeypatch
) -> None:
    calls: list[tuple[str, str, str, bool, float]] = []

    class FakeModel:
        sample_rate = 24000

        def inference_instruct2(
            self,
            text: str,
            instruction: str,
            voice_path: str,
            stream: bool,
            speed: float,
        ):
            calls.append((text, instruction, voice_path, stream, speed))
            yield {"tts_speech": object()}

    engine = SERVER.CosyVoiceEngine()
    engine.inference_mode = "instruct"
    engine.voice_dir = tmp_path
    (tmp_path / "man_happy.wav").write_bytes(b"wav")
    engine._model = FakeModel()
    monkeypatch.setattr(
        engine, "_wav_bytes", lambda speech, sample_rate, gain=1.0: b"audio"
    )

    audio, voice = engine.generate(
        SERVER.TTSRequest(
            input="오늘 신메뉴를 만나보세요.",
            voice="man_happy",
            instructions="기쁜 목소리로 말하세요.",
            speed=1.05,
        )
    )

    assert audio == b"audio"
    assert voice == "man_happy"
    assert calls == [
        (
            "오늘 신메뉴를 만나보세요.",
            SERVER.CosyVoiceEngine._instruction("기쁜 목소리로 말하세요.", 1.05),
            str(tmp_path / "man_happy.wav"),
            False,
            1.05,
        )
    ]


def test_generate_cross_lingual_processes_every_narration_segment(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []

    class FakeModel:
        sample_rate = 24000

        def inference_cross_lingual(
            self, text: str, voice_path: str, stream: bool, speed: float
        ):
            calls.append(text)
            yield {"tts_speech": object()}

    engine = SERVER.CosyVoiceEngine()
    engine.inference_mode = "cross_lingual"
    engine.voice_dir = tmp_path
    (tmp_path / "woman_serious.wav").write_bytes(b"wav")
    engine._model = FakeModel()
    monkeypatch.setattr(
        SERVER,
        "split_tts_text",
        lambda text: ["첫 번째 구간입니다.", "두 번째 구간입니다."],
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cat=lambda chunks, dim: chunks),
    )
    monkeypatch.setattr(
        engine, "_wav_bytes", lambda speech, sample_rate, gain=1.0: b"audio"
    )

    audio, voice = engine.generate(
        SERVER.TTSRequest(
            input="긴 광고 대본",
            voice="woman_serious",
            instructions="이 지시는 사용하지 않습니다.",
        )
    )

    assert audio == b"audio"
    assert voice == "woman_serious"
    assert calls == [
        SERVER.CosyVoiceEngine._cross_lingual_text("첫 번째 구간입니다."),
        SERVER.CosyVoiceEngine._cross_lingual_text("두 번째 구간입니다."),
    ]


def test_cross_lingual_whisper_voice_uses_fixed_style_instruction(
    tmp_path, monkeypatch
) -> None:
    calls: list[tuple[str, str, str, bool, float]] = []

    class FakeModel:
        sample_rate = 24000

        def inference_instruct2(
            self,
            text: str,
            instruction: str,
            voice_path: str,
            stream: bool,
            speed: float,
        ):
            calls.append((text, instruction, voice_path, stream, speed))
            yield {"tts_speech": object()}

    engine = SERVER.CosyVoiceEngine()
    engine.inference_mode = "cross_lingual"
    engine.voice_dir = tmp_path
    (tmp_path / "woman_whisper.wav").write_bytes(b"wav")
    engine._model = FakeModel()
    output_gains: list[float] = []
    monkeypatch.setattr(
        engine,
        "_wav_bytes",
        lambda speech, sample_rate, gain=1.0: output_gains.append(gain) or b"audio",
    )

    audio, voice = engine.generate(
        SERVER.TTSRequest(
            input="조용히 특별한 혜택을 소개합니다.",
            voice="woman_whisper",
            instructions="이 사용자 지시는 모델에 전달하지 않습니다.",
        )
    )

    assert audio == b"audio"
    assert voice == "woman_whisper"
    assert calls == [
        (
            "조용히 특별한 혜택을 소개합니다.",
            SERVER.VOICE_STYLE_INSTRUCTIONS["woman_whisper"],
            str(tmp_path / "woman_whisper.wav"),
            False,
            1.0,
        )
    ]
    assert "사용자 지시" not in calls[0][1]
    assert output_gains == [SERVER.VOICE_OUTPUT_GAINS["woman_whisper"]]


def test_male_whisper_uses_clearer_instruction_and_lower_gain() -> None:
    male_instruction = SERVER.VOICE_STYLE_INSTRUCTIONS["man_whisper"]

    assert male_instruction != SERVER.VOICE_STYLE_INSTRUCTIONS["woman_whisper"]
    assert "不要沙哑" in male_instruction
    assert "不要使用过重的气声" in male_instruction
    assert (
        SERVER.VOICE_OUTPUT_GAINS["man_whisper"]
        < SERVER.VOICE_OUTPUT_GAINS["woman_whisper"]
    )


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


def test_split_tts_text_keeps_long_narration_in_order() -> None:
    sentences = [
        "첫 번째 상품을 소개합니다.",
        "두 번째 혜택을 자세히 안내합니다.",
        "마지막으로 방문을 권합니다.",
    ]

    chunks = SERVER.split_tts_text(" ".join(sentences), max_chars=35)

    assert len(chunks) >= 2
    assert " ".join(chunks) == " ".join(sentences)
    assert all(len(chunk) <= 35 for chunk in chunks)
