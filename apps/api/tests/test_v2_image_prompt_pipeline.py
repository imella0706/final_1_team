"""Tests for the v2 image-prompt batch pipeline.

Covers:
  1.  batch_size=10 selects exactly 10 records
  2.  batch_size=50 selects exactly 50 records
  3.  batch_size=100 selects exactly 100 records
  4.  batch_size=20 is rejected by the CLI
  5.  missing --batch-size is rejected by the CLI
  6.  --all / --limit / --batch-size all options do not exist
  7.  insufficient data (<10) raises ValueError
  8.  insufficient data (<50) raises ValueError
  9.  insufficient data (<100) raises ValueError
 10.  same input + same batch_size → same selection
 11.  output paths are batch-specific (batch_10 / batch_50 / batch_100)
 12.  state files are batch-specific
 13.  resume skips already-succeeded items
 14.  prompt SHA-256: original text and delivered hash are identical
 15.  original CSV file mtime is unchanged after load
 16.  single-item failure does not abort the batch
 17.  retry exhaustion records failed status in manifest
 18.  dry-run makes no model calls
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Ensure api root is importable
# ---------------------------------------------------------------------------
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.v2_pipeline.loader import DataRecord, load_records, select_batch
from app.v2_pipeline.matcher import (
    MatchError,
    _compute_sha256,
    build_copy_request_payload,
    match_record,
)
from app.v2_pipeline.state_manager import StateManager
from app.v2_pipeline.validator import validate_batch
from app.v2_pipeline.runner import run_batch
from app.extensions.ad_content.schemas import ImageModel
from app.modules.ad_copy.schemas import AdModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_csv_row(
    idx: int,
    food_name: str = "테스트음식",
    business: str = "bakery",
    ad_use: str = "bakery_product_promotion",
) -> dict[str, str]:
    return {
        "final_image_id": f"DIV_IMG_{idx:06d}",
        "final_db_row_index": str(idx),
        "final_image_path": f"images/DIV_IMG_{idx:06d}.jpg",
        "original_food_name": food_name,
        "product_name": food_name,
        "food_code": "FC10S01",
        "business_category": business,
        "product_group": "bread",
        "view_type": "front",
        "caption": f"a photo of {food_name}",
        "prompt_keywords": f"bakery, bread, {food_name}, FC10S01",
        "caption_lighting": "natural_light",
        "caption_composition": "single_food_centered",
        "caption_camera_angle": "front_or_45_degree",
        "ad_use_case": ad_use,
        "visual_style_hint": f"bakery_{food_name}",
        "bbox_ratio": "0.4",
        "bbox_40_70_match": "True",
        "center_score": "0.95",
        "blur_score": "200.0",
        "resolution_score": "0.57",
        "representative_score": "0.72",
    }


def _make_prompt_metadata_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _setup_dataset(tmp_path: Path, n: int) -> Path:
    """Create a minimal v2 dataset structure with n valid JPEG images."""
    v2_dir = tmp_path / "v2"
    food_dir = v2_dir / "food_description_data"
    images_dir = food_dir / "images"
    images_dir.mkdir(parents=True)

    rows = [_make_csv_row(i) for i in range(n)]
    (food_dir / "prompt_metadata.csv").write_text(
        _make_prompt_metadata_csv(rows), encoding="utf-8"
    )

    # Small valid JPEG files; matcher decodes images before creating model input.
    for i in range(n):
        img = images_dir / f"DIV_IMG_{i:06d}.jpg"
        Image.new("RGB", (32, 32), "white").save(img, format="JPEG")

    return v2_dir


def _run(coro):
    """Run a coroutine synchronously — no pytest-asyncio dependency needed."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. batch_size=10 selects exactly 10 records
# ---------------------------------------------------------------------------
def test_batch_size_10_selects_exactly_10(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 100)
    records = load_records(v2_dir)
    batch = select_batch(records, 10)
    assert len(batch) == 10


# ---------------------------------------------------------------------------
# 2. batch_size=50 selects exactly 50 records
# ---------------------------------------------------------------------------
def test_batch_size_50_selects_exactly_50(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 100)
    records = load_records(v2_dir)
    batch = select_batch(records, 50)
    assert len(batch) == 50


# ---------------------------------------------------------------------------
# 3. batch_size=100 selects exactly 100 records
# ---------------------------------------------------------------------------
def test_batch_size_100_selects_exactly_100(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 100)
    records = load_records(v2_dir)
    batch = select_batch(records, 100)
    assert len(batch) == 100


# ---------------------------------------------------------------------------
# 4. batch_size=20 is rejected by the CLI argument parser
# ---------------------------------------------------------------------------
def test_invalid_batch_size_20_rejected():
    from scripts.run_v2_image_prompt_pipeline import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "--input-dir",
                ".",
                "--output-dir",
                ".",
                "--batch-size",
                "20",
            ]
        )
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 5. Missing --batch-size is rejected
# ---------------------------------------------------------------------------
def test_missing_batch_size_rejected():
    from scripts.run_v2_image_prompt_pipeline import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "--input-dir",
                ".",
                "--output-dir",
                ".",
            ]
        )
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 6. --all, --limit, --batch-size all options do not exist
# ---------------------------------------------------------------------------
def test_no_all_option_exists():
    from scripts.run_v2_image_prompt_pipeline import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--input-dir", ".", "--output-dir", ".", "--all"])


def test_no_limit_option_exists():
    from scripts.run_v2_image_prompt_pipeline import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--input-dir", ".", "--output-dir", ".", "--limit", "0"])


def test_batch_size_all_is_rejected():
    from scripts.run_v2_image_prompt_pipeline import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--input-dir", ".", "--output-dir", ".", "--batch-size", "all"]
        )


# ---------------------------------------------------------------------------
# 7-9. Insufficient data raises ValueError with clear message
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "batch_size,available",
    [
        (10, 9),
        (50, 49),
        (100, 99),
    ],
)
def test_insufficient_data_raises(tmp_path, batch_size, available):
    v2_dir = _setup_dataset(tmp_path, available)
    records = load_records(v2_dir)
    with pytest.raises(ValueError, match="Insufficient data"):
        select_batch(records, batch_size)


# ---------------------------------------------------------------------------
# 10. Deterministic selection: same input → same IDs selected
# ---------------------------------------------------------------------------
def test_deterministic_selection(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 50)
    ids_first = [r.final_image_id for r in select_batch(load_records(v2_dir), 10)]
    ids_second = [r.final_image_id for r in select_batch(load_records(v2_dir), 10)]
    assert ids_first == ids_second


# ---------------------------------------------------------------------------
# 11. Output paths are batch-specific
# ---------------------------------------------------------------------------
def test_batch_output_paths_are_separated(tmp_path):
    from scripts.run_v2_image_prompt_pipeline import _resolve_batch_output_dir

    out10 = _resolve_batch_output_dir(tmp_path, 10)
    out50 = _resolve_batch_output_dir(tmp_path, 50)
    out100 = _resolve_batch_output_dir(tmp_path, 100)
    assert out10 != out50
    assert out50 != out100
    assert "batch_10" in str(out10)
    assert "batch_50" in str(out50)
    assert "batch_100" in str(out100)


# ---------------------------------------------------------------------------
# 12. State files are batch-specific and independent
# ---------------------------------------------------------------------------
def test_state_files_are_batch_specific(tmp_path):
    state10 = StateManager(tmp_path / "batch_10" / "state.json")
    state50 = StateManager(tmp_path / "batch_50" / "state.json")

    state10.mark_success("IMG_000", "abc123", "result/IMG_000.json", 1)

    # batch_50 state must not see batch_10 entry
    assert not state50.is_done("IMG_000")

    # Reload batch_10 state from disk — entry must persist
    state10_reloaded = StateManager(tmp_path / "batch_10" / "state.json")
    assert state10_reloaded.is_done("IMG_000")


# ---------------------------------------------------------------------------
# 13. Resume skips already-succeeded items
# ---------------------------------------------------------------------------
def test_resume_skips_successful_items(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 10)
    records = load_records(v2_dir)
    batch = select_batch(records, 10)

    batch_out = tmp_path / "batch_10"
    state_path = batch_out / "state.json"
    state = StateManager(state_path)

    # Pre-mark first 5 as success
    for rec in batch[:5]:
        ph = _compute_sha256(rec.prompt_keywords)
        state.mark_success(rec.final_image_id, ph, "fake_path.json", 1)

    call_count = 0

    async def _fake_process(record, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"image_id": record.final_image_id, "status": "success"}

    with patch("app.v2_pipeline.runner._process_one", side_effect=_fake_process):
        _run(
            run_batch(
                records=batch,
                batch_size=10,
                output_dir_root=batch_out,
                max_retries=0,
                resume=True,
                dry_run=False,
                image_model=MagicMock(),
                verbose=False,
            )
        )

    # Only the 5 not-yet-succeeded items should have triggered _process_one
    assert call_count == 5


# ---------------------------------------------------------------------------
# 14. prompt SHA-256: original and delivered hash are identical
# ---------------------------------------------------------------------------
def test_prompt_sha256_matches_original(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 5)
    records = load_records(v2_dir)
    for rec in records:
        expected = hashlib.sha256(rec.prompt_keywords.encode("utf-8")).hexdigest()
        computed = _compute_sha256(rec.prompt_keywords)
        assert computed == expected, (
            f"Hash mismatch for {rec.final_image_id}: "
            f"expected {expected}, got {computed}"
        )


def test_build_payload_delivers_verbatim_prompt(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 1)
    records = load_records(v2_dir)
    matched = match_record(records[0])

    original_prompt = matched.record.prompt_keywords
    payload = build_copy_request_payload(matched)

    delivered = payload["features"][0]
    assert (
        delivered == original_prompt
    ), "prompt_keywords was modified before delivery to build_copy_request_payload"
    # Hash must also match
    assert _compute_sha256(delivered) == _compute_sha256(original_prompt)


def test_build_payload_selects_llm_without_changing_prompt(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 1)
    matched = match_record(load_records(v2_dir)[0])
    original_prompt = matched.record.prompt_keywords

    payload = build_copy_request_payload(
        matched,
        llm_model="meta-llama/Llama-3.1-8B-Instruct",
    )

    assert payload["model"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert payload["features"][0] == original_prompt
    assert _compute_sha256(payload["features"][0]) == _compute_sha256(original_prompt)


def test_matcher_normalizes_model_image_to_single_rgb_jpeg(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 1)
    image_path = v2_dir / "food_description_data" / "images" / "DIV_IMG_000000.jpg"
    Image.new("RGBA", (64, 64), (255, 0, 0, 128)).save(image_path, format="PNG")

    matched = match_record(load_records(v2_dir)[0])

    header, encoded = matched.image_data_url.split(",", 1)
    assert header == "data:image/jpeg;base64"
    assert len(matched.image_data_url) <= 3_800_000
    from io import BytesIO
    import base64
    with Image.open(BytesIO(base64.b64decode(encoded))) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"


def test_cli_accepts_all_model_matrix_flags():
    from scripts.run_v2_image_prompt_pipeline import build_parser

    args = build_parser().parse_args(
        [
            "--input-dir", ".", "--output-dir", ".", "--batch-size", "10",
            "--all-llm-models", "--all-image-models",
        ]
    )
    assert args.all_llm_models is True
    assert args.all_image_models is True


# ---------------------------------------------------------------------------
# 15. Original CSV file mtime is unchanged after load_records
# ---------------------------------------------------------------------------
def test_original_csv_not_modified(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 10)
    csv_path = v2_dir / "food_description_data" / "prompt_metadata.csv"
    mtime_before = csv_path.stat().st_mtime

    load_records(v2_dir)

    mtime_after = csv_path.stat().st_mtime
    assert (
        mtime_before == mtime_after
    ), "prompt_metadata.csv was modified during load_records — source files must not be touched"


def test_original_images_not_modified(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 3)
    records = load_records(v2_dir)
    mtimes_before = {
        r.final_image_id: r.abs_image_path.stat().st_mtime for r in records
    }

    # Running match_record reads but must not write
    for rec in records:
        match_record(rec)

    for rec in records:
        assert (
            rec.abs_image_path.stat().st_mtime == mtimes_before[rec.final_image_id]
        ), f"Image file {rec.abs_image_path} was modified"


# ---------------------------------------------------------------------------
# 16. Single-item failure does not abort the batch
# ---------------------------------------------------------------------------
def test_single_failure_does_not_abort_batch(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 3)
    records = load_records(v2_dir)
    batch_out = tmp_path / "batch_3"

    results_iter = iter(
        [
            {"image_id": records[0].final_image_id, "status": "success"},
            {
                "image_id": records[1].final_image_id,
                "status": "failed",
                "error": "boom",
            },
            {"image_id": records[2].final_image_id, "status": "success"},
        ]
    )

    async def _fake_process(record, **kwargs):
        return next(results_iter)

    with patch("app.v2_pipeline.runner._process_one", side_effect=_fake_process):
        exit_code = _run(
            run_batch(
                records=records,
                batch_size=3,
                output_dir_root=batch_out,
                max_retries=0,
                resume=False,
                dry_run=False,
                image_model=MagicMock(),
                verbose=False,
            )
        )

    # Exit code 1 because of the failed item, but all 3 were processed
    assert exit_code == 1

    manifests = list((batch_out / "manifests").glob("*.json"))
    assert manifests, "Manifest file was not written"
    data = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert data["total"] == 3
    assert data["success"] == 2
    assert data["failed"] == 1


# ---------------------------------------------------------------------------
# 17. Retry exhaustion → failed status in manifest
# ---------------------------------------------------------------------------
def test_retry_exhausted_records_failed(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 1)
    records = load_records(v2_dir)
    batch_out = tmp_path / "batch_1"

    async def _always_fail(record, **kwargs):
        return {
            "image_id": record.final_image_id,
            "status": "failed",
            "error": "provider error",
        }

    with patch("app.v2_pipeline.runner._process_one", side_effect=_always_fail):
        exit_code = _run(
            run_batch(
                records=records,
                batch_size=1,
                output_dir_root=batch_out,
                max_retries=2,
                resume=False,
                dry_run=False,
                image_model=MagicMock(),
                verbose=False,
            )
        )

    assert exit_code == 1
    manifests = list((batch_out / "manifests").glob("*.json"))
    assert manifests
    data = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert data["failed"] == 1
    assert data["success"] == 0


# ---------------------------------------------------------------------------
# 18. Dry-run makes no model calls
# ---------------------------------------------------------------------------
def test_dry_run_makes_no_model_calls(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 10)
    records = load_records(v2_dir)
    batch_out = tmp_path / "batch_10"

    with patch("app.v2_pipeline.runner.generate_content") as mock_generate:

        exit_code = _run(
            run_batch(
                records=records,
                batch_size=10,
                output_dir_root=batch_out,
                max_retries=0,
                resume=False,
                dry_run=True,
                image_model=MagicMock(),
                verbose=False,
            )
        )

    mock_generate.assert_not_called()
    assert exit_code == 0


@pytest.mark.parametrize("channel", ["instagram", "naver_blog"])
def test_real_run_delegates_to_existing_generate_content_flow(tmp_path, channel):
    """v2 constructs a channel request but does not reimplement prompt stages."""
    v2_dir = _setup_dataset(tmp_path, 1)
    record = load_records(v2_dir)[0]
    batch_out = tmp_path / channel

    generated_copy = {"channel_recommendation": {"publish_title": "generated"}}
    response = MagicMock()
    response.copy_result.model_dump.return_value = generated_copy
    response.image.image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    response.image.media_type = "image/png"
    response.image.model = "test-image"
    response.image.latency_ms = 1
    response.image_prompt = "existing-prompt-output"
    response.negative_prompt = "existing-negative-output"
    response.validation = None
    response.artifacts = {"existing": "artifact"}

    with (
        patch("app.v2_pipeline.runner.generate_content", new=AsyncMock(return_value=response)) as generate,
        patch("app.v2_pipeline.runner.save_channel_artifacts", return_value={"v2": "artifact"}),
    ):
        exit_code = _run(
            run_batch(
                records=[record],
                batch_size=1,
                output_dir_root=batch_out,
                max_retries=0,
                resume=False,
                dry_run=False,
                image_model=ImageModel.FLUX_SCHNELL,
                llm_model=AdModel.QWEN_2_5_7B,
                channel=channel,
                verbose=False,
            )
        )

    assert exit_code == 0
    request = generate.await_args.args[0]
    assert request.copy.model == AdModel.QWEN_2_5_7B
    assert request.copy.features[0] == record.prompt_keywords
    assert request.image_model == ImageModel.FLUX_SCHNELL
    assert bool(request.blog_images) is (channel == "naver_blog")


# ---------------------------------------------------------------------------
# Validator: missing image → error
# ---------------------------------------------------------------------------
def test_validate_batch_detects_missing_image(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 3)
    records = load_records(v2_dir)
    # Delete the second image
    records[1].abs_image_path.unlink()

    report = validate_batch(records, tmp_path / "results")
    assert not report.is_valid
    error_ids = [e.image_id for e in report.errors]
    assert records[1].final_image_id in error_ids


# ---------------------------------------------------------------------------
# Validator: duplicate IDs → error
# ---------------------------------------------------------------------------
def test_validate_batch_detects_duplicate_ids(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 3)
    records = load_records(v2_dir)
    # Inject duplicate
    duped = [records[0], records[0], records[2]]
    report = validate_batch(duped, tmp_path / "results")
    assert not report.is_valid
    assert any("Duplicate" in e.message for e in report.errors)


# ---------------------------------------------------------------------------
# Matcher: missing image raises MatchError
# ---------------------------------------------------------------------------
def test_match_record_fails_on_missing_image(tmp_path):
    v2_dir = _setup_dataset(tmp_path, 1)
    records = load_records(v2_dir)
    records[0].abs_image_path.unlink()
    with pytest.raises(MatchError, match="not found"):
        match_record(records[0])
