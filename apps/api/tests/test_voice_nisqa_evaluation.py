import csv
import importlib.util
import sys
from pathlib import Path


SCRIPT_FILE = (
    Path(__file__).resolve().parents[3] / "scripts" / "evaluate_voice_nisqa.py"
)
SPEC = importlib.util.spec_from_file_location(
    "brandmate_voice_nisqa_evaluation",
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
    rows = [{"nisqa_tts_naturalness": "3.5"} for _ in range(3)]
    rows.extend(
        {"nisqa_tts_naturalness": ""}
        for _ in range(len(plan) - 3)
    )

    selected = EVALUATION.select_cases(
        rows,
        plan,
        count=2,
        run_all=False,
        overwrite=False,
    )

    assert [case.num for _, case in selected] == [4, 5]


def test_manifest_contains_absolute_paths_and_test_ids(tmp_path: Path) -> None:
    case = EVALUATION.VOICE_TEST.build_test_plan()[0]
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"audio")
    manifest_path = tmp_path / "run" / "manifest.csv"

    EVALUATION.write_manifest(
        manifest_path,
        [(0, case, audio_path)],
    )

    with manifest_path.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows == [{"num": "1", "deg": str(audio_path.resolve())}]


def test_read_nisqa_results_validates_and_maps_scores(tmp_path: Path) -> None:
    cases = EVALUATION.VOICE_TEST.build_test_plan()[:2]
    results_path = tmp_path / "NISQA_results.csv"
    with results_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=("num", "deg", "mos_pred", "model"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "num": 1,
                "deg": "one.wav",
                "mos_pred": "3.84717",
                "model": "NISQA_TTS_v1",
            }
        )
        writer.writerow(
            {
                "num": 2,
                "deg": "two.wav",
                "mos_pred": "4.125",
                "model": "NISQA_TTS_v1",
            }
        )

    results = EVALUATION.read_nisqa_results(results_path, cases)

    assert results == {
        1: (3.84717, "NISQA_TTS_v1"),
        2: (4.125, "NISQA_TTS_v1"),
    }


def test_update_rows_preserves_existing_human_and_cer_fields() -> None:
    case = EVALUATION.VOICE_TEST.build_test_plan()[0]
    rows = [{"num": "1", "total": "19", "cer": "0.000000"}]

    EVALUATION.update_rows(
        rows,
        [(0, case)],
        {1: (3.84717, "NISQA_TTS_v1")},
        commit="abc123",
    )

    assert rows[0]["total"] == "19"
    assert rows[0]["cer"] == "0.000000"
    assert rows[0]["nisqa_tts_naturalness"] == "3.847170"
    assert rows[0]["nisqa_model"] == "NISQA_TTS_v1"
    assert rows[0]["nisqa_source_commit"] == "abc123"


def test_atomic_csv_write_keeps_existing_and_nisqa_columns(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "voice-test.csv"
    fieldnames = EVALUATION.result_fieldnames(["num", "total", "cer"])
    rows = [
        {
            "num": "1",
            "total": "20",
            "cer": "0.000000",
            "nisqa_tts_naturalness": "3.500000",
        }
    ]

    EVALUATION.write_csv_atomic(csv_path, fieldnames, rows)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        saved = list(csv.DictReader(csv_file))
    assert saved[0]["total"] == "20"
    assert saved[0]["cer"] == "0.000000"
    assert saved[0]["nisqa_tts_naturalness"] == "3.500000"


def test_build_command_uses_current_environment_python(tmp_path: Path) -> None:
    command = EVALUATION.build_nisqa_command(
        nisqa_root=tmp_path / "NISQA",
        model_path=tmp_path / "nisqa_tts.tar",
        manifest_path=tmp_path / "manifest.csv",
        output_dir=tmp_path / "output",
        batch_size=10,
        num_workers=0,
        max_segments=10000,
    )

    assert command[0] == sys.executable
    assert command[1].endswith("run_nisqa_predict.py")
    assert command[2:4] == ["--nisqa-root", str(tmp_path / "NISQA")]
    assert command[-4:] == [
        "--max-segments",
        "10000",
        "--output-dir",
        str(tmp_path / "output"),
    ]
