import csv
import importlib.util
import sys
from pathlib import Path


SCRIPT_FILE = (
    Path(__file__).resolve().parents[3] / "scripts" / "evaluate_voice_cer.py"
)
SPEC = importlib.util.spec_from_file_location(
    "brandmate_voice_cer_evaluation",
    SCRIPT_FILE,
)
assert SPEC and SPEC.loader
EVALUATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EVALUATION
SPEC.loader.exec_module(EVALUATION)


def test_normalize_for_cer_uses_same_korean_number_readings_as_tts() -> None:
    reference = "오후 2시, 세트는 9,900원이며 10퍼센트 할인합니다."
    transcript = "오후 두 시 세트는 구천구백 원이며 십 퍼센트 할인합니다"

    assert EVALUATION.normalize_for_cer(reference) == EVALUATION.normalize_for_cer(
        transcript
    )


def test_calculate_cer_counts_character_edits() -> None:
    result = EVALUATION.calculate_cer("가나다라", "가나마")

    assert result.reference == "가나다라"
    assert result.hypothesis == "가나마"
    assert result.edits == 2
    assert result.reference_chars == 4
    assert result.rate == 0.5


def test_validate_rows_preserves_human_evaluation_columns() -> None:
    plan = EVALUATION.VOICE_TEST.build_test_plan()
    rows = [
        {
            "num": str(case.num),
            "voice": case.voice,
            "tone": case.tone,
            "text_type": case.text_type,
            "total": "20",
            "comment": "좋음",
        }
        for case in plan
    ]

    validated = EVALUATION.validate_rows(rows, plan)

    assert len(validated) == 225
    assert validated[0]["total"] == "20"
    assert validated[0]["comment"] == "좋음"


def test_update_row_adds_auditable_cer_fields() -> None:
    row = {"num": "1", "total": "20"}
    transcript = EVALUATION.TranscriptionResult(
        text="오늘 커피",
        input_tokens=100,
        output_tokens=3,
        total_tokens=103,
        latency_seconds=1.2345,
    )
    cer = EVALUATION.calculate_cer("오늘 커피", transcript.text)

    EVALUATION.update_row(
        row,
        model="gpt-4o-transcribe",
        transcript=transcript,
        cer=cer,
    )

    assert row["total"] == "20"
    assert row["asr_model"] == "gpt-4o-transcribe"
    assert row["cer"] == "0.000000"
    assert row["cer_percent"] == "0.00"
    assert row["asr_total_tokens"] == "103"
    assert row["asr_latency(s)"] == "1.234"


def test_cache_requires_matching_model_and_audio_hash(tmp_path: Path) -> None:
    cache_path = tmp_path / "sample.json"
    transcript = EVALUATION.TranscriptionResult(
        text="테스트 전사",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        latency_seconds=0.5,
    )
    EVALUATION.write_cache(
        cache_path,
        model="gpt-4o-transcribe",
        audio_sha256="abc",
        result=transcript,
    )

    assert (
        EVALUATION.read_cache(
            cache_path,
            model="gpt-4o-transcribe",
            audio_sha256="abc",
        )
        == transcript
    )
    assert (
        EVALUATION.read_cache(
            cache_path,
            model="gpt-4o-transcribe",
            audio_sha256="different",
        )
        is None
    )


def test_atomic_csv_write_keeps_original_and_result_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "voice-test.csv"
    fieldnames = EVALUATION.result_fieldnames(["num", "total", "comment"])
    rows = [
        {
            "num": "1",
            "total": "20",
            "comment": "좋음",
            "cer": "0.000000",
        }
    ]

    EVALUATION.write_csv_atomic(csv_path, fieldnames, rows)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        saved = list(csv.DictReader(csv_file))
    assert saved[0]["total"] == "20"
    assert saved[0]["comment"] == "좋음"
    assert saved[0]["cer"] == "0.000000"


def test_select_cases_resumes_after_completed_rows() -> None:
    plan = EVALUATION.VOICE_TEST.build_test_plan()
    rows = [{"cer": "0.000000"} for _ in range(3)]
    rows.extend({"cer": ""} for _ in range(len(plan) - 3))

    selected = EVALUATION.select_cases(
        rows,
        plan,
        count=2,
        run_all=False,
        overwrite=False,
    )

    assert [case.num for _, case in selected] == [4, 5]


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
