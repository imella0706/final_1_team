import csv
import importlib.util
import io
import sys
import wave
from pathlib import Path


SCRIPT_FILE = (
    Path(__file__).resolve().parents[3] / "scripts" / "run_cosyvoice_test.py"
)
SPEC = importlib.util.spec_from_file_location(
    "brandmate_voice_test_automation", SCRIPT_FILE
)
assert SPEC and SPEC.loader
AUTOMATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUTOMATION
SPEC.loader.exec_module(AUTOMATION)


def test_plan_resumes_existing_csv_at_test_55() -> None:
    plan = AUTOMATION.build_test_plan()

    assert len(plan) == 225
    assert (
        plan[44].num,
        plan[44].cosyvoice_name,
        plan[44].text_type,
        plan[44].repeat,
    ) == (45, "woman_whisper", "short3", 3)
    assert (
        plan[54].num,
        plan[54].cosyvoice_name,
        plan[54].text_type,
        plan[54].repeat,
    ) == (55, "woman_serious", "med1", 1)


def test_validate_history_rejects_an_out_of_order_row() -> None:
    plan = AUTOMATION.build_test_plan()
    history = [
        {
            "num": "1",
            "voice": "woman",
            "tone": "happy",
            "voice_time(s)": "2",
            "create_time(s)": "3",
            "text_type": "short1",
        }
    ]

    try:
        AUTOMATION.validate_history(history, plan)
    except RuntimeError as error:
        assert "테스트 순서가 계획과 다릅니다" in str(error)
    else:
        raise AssertionError("Expected invalid history to be rejected")


def test_wav_duration_uses_frame_count_and_sample_rate() -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00" * 30000)

    assert AUTOMATION.wav_duration_seconds(output.getvalue()) == 1.25


def test_append_result_preserves_expected_csv_columns(tmp_path) -> None:
    csv_path = tmp_path / "voice-test.csv"
    case = AUTOMATION.build_test_plan()[54]

    AUTOMATION.append_result(csv_path, case, 6.125, 5.432)

    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows == [
        {
            "num": "55",
            "voice": "woman",
            "tone": "serious",
            "voice_time(s)": "6.125",
            "create_time(s)": "5.432",
            "text_type": "med1",
        }
    ]


def test_persist_result_removes_wav_when_csv_append_fails(
    tmp_path, monkeypatch
) -> None:
    output_path = tmp_path / "0055.wav"
    case = AUTOMATION.build_test_plan()[54]

    def fail_append(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(AUTOMATION, "append_result", fail_append)

    try:
        AUTOMATION.persist_result(
            output_path,
            b"audio",
            tmp_path / "locked.csv",
            case,
            6.125,
            5.432,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Expected CSV append failure")

    assert not output_path.exists()
