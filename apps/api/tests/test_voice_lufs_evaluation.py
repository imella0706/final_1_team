import csv
import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_FILE = (
    Path(__file__).resolve().parents[3] / "scripts" / "evaluate_voice_lufs.py"
)
SPEC = importlib.util.spec_from_file_location(
    "brandmate_voice_lufs_evaluation",
    SCRIPT_FILE,
)
assert SPEC and SPEC.loader
EVALUATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EVALUATION
SPEC.loader.exec_module(EVALUATION)


def test_resolve_audio_path_supports_legacy_and_generated_names(
    tmp_path: Path,
) -> None:
    plan = EVALUATION.VOICE_TEST.build_test_plan()
    legacy_case = plan[0]
    generated_case = plan[54]
    legacy_path = tmp_path / "T001_man_happy_short1.wav"
    generated_path = tmp_path / generated_case.filename
    legacy_path.write_bytes(b"legacy")
    generated_path.write_bytes(b"generated")

    assert EVALUATION.resolve_audio_path(tmp_path, legacy_case) == legacy_path
    assert (
        EVALUATION.resolve_audio_path(tmp_path, generated_case)
        == generated_path
    )


def test_select_cases_resumes_after_completed_rows() -> None:
    plan = EVALUATION.VOICE_TEST.build_test_plan()
    rows = [{"lufs_integrated": "-16.00"} for _ in range(3)]
    rows.extend({"lufs_integrated": ""} for _ in range(len(plan) - 3))

    selected = EVALUATION.select_cases(
        rows,
        plan,
        count=2,
        run_all=False,
        overwrite=False,
    )

    assert [case.num for _, case in selected] == [4, 5]


def test_build_command_uses_measurement_filter(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.wav"

    command = EVALUATION.build_ffmpeg_command("ffmpeg", audio_path)

    assert command[0] == "ffmpeg"
    assert command[4] == str(audio_path)
    audio_filter = command[command.index("-af") + 1]
    assert "dual_mono=true" in audio_filter
    assert "print_format=json" in audio_filter
    assert command[-3:] == ["-f", "null", "-"]


def test_parse_loudnorm_output_reads_input_metrics() -> None:
    stderr = """
    [Parsed_loudnorm_0]
    {
        "input_i" : "-18.42",
        "input_tp" : "-2.17",
        "input_lra" : "1.30",
        "input_thresh" : "-28.90"
    }
    """

    assert EVALUATION.parse_loudnorm_output(stderr) == (-18.42, -2.17)


def test_parse_loudnorm_output_rejects_missing_json() -> None:
    with pytest.raises(RuntimeError, match="loudnorm JSON"):
        EVALUATION.parse_loudnorm_output("ordinary ffmpeg output")


def test_update_rows_preserves_existing_results() -> None:
    case = EVALUATION.VOICE_TEST.build_test_plan()[0]
    rows = [
        {
            "num": "1",
            "total": "19",
            "cer": "0.000000",
            "nisqa_tts_naturalness": "3.847170",
        }
    ]

    EVALUATION.update_rows(
        rows,
        [(0, case)],
        {1: (-16.123, -1.456)},
        tool="ffmpeg version test",
    )

    assert rows[0]["total"] == "19"
    assert rows[0]["cer"] == "0.000000"
    assert rows[0]["nisqa_tts_naturalness"] == "3.847170"
    assert rows[0]["lufs_integrated"] == "-16.12"
    assert rows[0]["true_peak_dbtp"] == "-1.46"
    assert rows[0]["lufs_tool"] == "ffmpeg version test"


def test_atomic_csv_write_keeps_existing_and_lufs_columns(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "voice-test.csv"
    fieldnames = EVALUATION.result_fieldnames(["num", "total", "cer"])
    rows = [
        {
            "num": "1",
            "total": "20",
            "cer": "0.000000",
            "lufs_integrated": "-16.00",
            "true_peak_dbtp": "-1.50",
        }
    ]

    EVALUATION.write_csv_atomic(csv_path, fieldnames, rows)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        saved = list(csv.DictReader(csv_file))
    assert saved[0]["total"] == "20"
    assert saved[0]["cer"] == "0.000000"
    assert saved[0]["lufs_integrated"] == "-16.00"
    assert saved[0]["true_peak_dbtp"] == "-1.50"
