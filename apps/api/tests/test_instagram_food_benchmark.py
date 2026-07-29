import argparse
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.extensions.ad_content.schemas import ImageModel, VisionModel
from app.modules.ad_copy.schemas import AdModel
from scripts.run_instagram_food_benchmark import (
    MAX_DATA_URL_LENGTH,
    aggregate,
    build_plan,
    copy_existing_run_source_images,
    model_combinations,
    normalized_image_data_url,
    render_existing_run_overlays,
    render_text_overlay,
    select_cases,
)


def _metadata_row(image_id: str, category: str, group: str, product: str) -> dict[str, str]:
    return {
        "final_image_id": image_id,
        "product_name": product,
        "original_food_name": product,
        "business_category": category,
        "product_group": group,
        "caption": f"a photo of {product}",
        "prompt_keywords": f"{category}, {group}, {product}",
        "ad_use_case": "instagram",
        "visual_style_hint": "commercial food photo",
    }


def test_select_cases_matches_photos_and_builds_instagram_prompts(tmp_path: Path) -> None:
    rows = []
    index = 0
    for category, count in {"bakery": 2, "cafe": 2, "pub": 2, "restaurant": 4}.items():
        for category_index in range(count):
            image_id = f"DIV_IMG_{index:06d}"
            (tmp_path / f"{image_id}.jpg").write_bytes(b"not-read-during-selection")
            rows.append(
                _metadata_row(
                    image_id,
                    category,
                    f"group-{category_index}",
                    f"food-{index}",
                )
            )
            index += 1

    cases = select_cases(rows, tmp_path)

    assert len(cases) == 10
    assert {case["food"]["business_category"] for case in cases} == {
        "bakery",
        "cafe",
        "pub",
        "restaurant",
    }
    assert all(case["instagram_request"]["channel"] == "instagram" for case in cases)
    assert all(
        case["food"]["product_name"] in case["instagram_request"]["required_terms"]
        for case in cases
    )
    assert all(
        case["food"]["product_group"] not in case["instagram_request"]["interests"]
        for case in cases
    )
    assert all(
        "사진 설명:" not in " ".join(case["instagram_request"]["features"])
        and "시각 키워드:" not in " ".join(case["instagram_request"]["features"])
        for case in cases
    )


def test_model_combinations_support_full_and_one_factor() -> None:
    values = {
        "llm_model": [AdModel.LOCAL_QWEN_2_5_7B.value, AdModel.OPENAI_GPT_5_4.value],
        "vision_model": [
            VisionModel.LOCAL_QWEN_3_VL_4B.value,
            VisionModel.OPENAI_GPT_5_4_MINI.value,
        ],
        "image_model": [ImageModel.SDXL_BASE.value, ImageModel.OPENAI_GPT_IMAGE_1_MINI.value],
    }
    full = model_combinations(argparse.Namespace(**values, matrix_mode="full"))
    one_factor = model_combinations(argparse.Namespace(**values, matrix_mode="one-factor"))

    assert len(full) == 8
    assert len(one_factor) == 4


def test_build_plan_crosses_every_food_with_every_combination() -> None:
    cases = [
        {
            "id": "case-1",
            "image_id": "IMG_1",
            "image_path": "data/images/IMG_1.jpg",
            "food": {"product_name": "food-1"},
        },
        {
            "id": "case-2",
            "image_id": "IMG_2",
            "image_path": "data/images/IMG_2.jpg",
            "food": {"product_name": "food-2"},
        },
    ]
    combinations = [
        {
            "llm_model": AdModel.LOCAL_QWEN_2_5_7B,
            "vision_model": VisionModel.LOCAL_QWEN_3_VL_4B,
            "image_model": ImageModel.SDXL_BASE,
        },
        {
            "llm_model": AdModel.OPENAI_GPT_5_4,
            "vision_model": VisionModel.OPENAI_GPT_5_4_MINI,
            "image_model": ImageModel.OPENAI_GPT_IMAGE_1_MINI,
        },
    ]

    assert len(build_plan(cases, combinations)) == 4
    assert len(build_plan(cases, combinations, max_runs=3)) == 3


def test_build_plan_creates_paired_meme_arms() -> None:
    cases = [
        {
            "id": "case-1",
            "image_id": "IMG_1",
            "image_path": "data/images/IMG_1.jpg",
            "food": {"product_name": "food-1"},
        }
    ]
    combinations = [
        {
            "llm_model": AdModel.LOCAL_QWEN_2_5_7B,
            "vision_model": VisionModel.LOCAL_QWEN_3_VL_4B,
            "image_model": ImageModel.SDXL_BASE,
        }
    ]

    plan = build_plan(
        cases,
        combinations,
        compare_meme=True,
        trend_card_id="test:trend-card",
    )

    assert [item["meme_arm"] for item in plan] == ["without_meme", "with_meme"]
    assert plan[0]["use_trend_card"] is False
    assert plan[0]["trend_card_id"] is None
    assert plan[1]["use_trend_card"] is True
    assert plan[1]["trend_card_id"] == "test:trend-card"
    assert "without_meme" in plan[0]["trial_id"]
    assert "with_meme" in plan[1]["trial_id"]


def test_image_normalization_converts_mislabeled_png_to_rgb_jpeg(tmp_path: Path) -> None:
    path = tmp_path / "actually-png.jpg"
    buffer = BytesIO()
    Image.new("RGBA", (1600, 1200), (255, 0, 0, 128)).save(buffer, format="PNG")
    original = buffer.getvalue()
    path.write_bytes(original)

    data_url, metadata = normalized_image_data_url(path)
    decoded = base64.b64decode(data_url.split(",", 1)[1])

    assert data_url.startswith("data:image/jpeg;base64,")
    assert decoded.startswith(b"\xff\xd8\xff")
    assert len(data_url) <= MAX_DATA_URL_LENGTH
    assert metadata["source_format"] == "PNG"
    assert max(metadata["model_input_size"]) <= 1024
    assert path.read_bytes() == original


def test_aggregate_distinguishes_pipeline_success_from_fallback_copy() -> None:
    records = [
        {
            "llm_model": "model-a",
            "success": True,
            "fallback_copy_used": False,
            "copy_attempts": 1,
            "wall_latency_ms": 100,
            "context_adherence_score": 1,
            "hashtag_compliance_rate": 1,
            "headline_diversity_score": 0.5,
            "validation": {"image_valid": True},
        },
        {
            "llm_model": "model-a",
            "success": True,
            "fallback_copy_used": True,
            "copy_attempts": 3,
            "wall_latency_ms": 200,
            "context_adherence_score": 1,
            "hashtag_compliance_rate": 1,
            "headline_diversity_score": 0,
            "validation": {"image_valid": True},
        },
    ]

    summary = aggregate(records, "llm_model")[0]

    assert summary["success_rate_percent"] == 100
    assert summary["native_copy_success_rate_percent"] == 50
    assert summary["fallback_copy_rate_percent"] == 50
    assert summary["mean_copy_attempts"] == 2


def test_render_text_overlay_preserves_source_and_saves_png(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    output = tmp_path / "generated-with-copy.png"
    Image.new("RGB", (768, 1024), (180, 120, 80)).save(source, format="JPEG")
    original = source.read_bytes()

    render_text_overlay(source, output, "가리비초밥의 오늘", "가리비초밥")

    assert source.read_bytes() == original
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(output) as rendered:
        assert rendered.size == (768, 1024)


def test_render_existing_run_overlays_uses_saved_instagram_headline(tmp_path: Path) -> None:
    trial_dir = tmp_path / "trials" / "food-01"
    trial_dir.mkdir(parents=True)
    Image.new("RGB", (512, 640), (100, 140, 90)).save(
        trial_dir / "generated.jpg", format="JPEG"
    )
    (trial_dir / "result.json").write_text(
        json.dumps(
            {
                "input": {"product_names": ["마늘빵"]},
                "channel_recommendation": {"overlay_headline": "마늘빵의 오늘"},
                "copy": {"headlines": ["마늘빵 신메뉴"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = render_existing_run_overlays(tmp_path)

    assert len(records) == 1
    assert records[0]["headline"] == "마늘빵의 오늘"
    assert records[0]["subtitle"] == ""
    assert (trial_dir / "generated-with-copy.png").is_file()
    assert (tmp_path / "text-overlay-manifest.json").is_file()


def test_copy_existing_run_source_images_preserves_exact_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"exact-source-image-bytes")
    run_dir = tmp_path / "run"
    trial_dir = run_dir / "trials" / "food-01"
    trial_dir.mkdir(parents=True)
    (run_dir / "plan.json").write_text(
        json.dumps(
            [
                {
                    "trial_id": "food-01",
                    "image_id": "DIV_IMG_000001",
                    "source_image": str(source),
                }
            ]
        ),
        encoding="utf-8",
    )

    records = copy_existing_run_source_images(run_dir)

    copied = trial_dir / "source-original-source.jpg"
    assert len(records) == 1
    assert copied.read_bytes() == source.read_bytes()
    assert records[0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (run_dir / "source-image-manifest.json").is_file()
