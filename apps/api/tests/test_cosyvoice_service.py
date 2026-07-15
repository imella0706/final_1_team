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


def test_voice_path_uses_default_voice(tmp_path) -> None:
    engine = SERVER.CosyVoiceEngine()
    engine.voice_dir = tmp_path
    default_voice = tmp_path / "default.wav"
    default_voice.write_bytes(b"wav")

    voice_name, voice_path = engine._voice_path("missing-voice")

    assert voice_name == "default"
    assert voice_path == default_voice
