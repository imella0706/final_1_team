"""Generate reviewable Naver Blog posts and title posters from food photos."""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.extensions.ad_content.schemas import (
    AdContentRequest,
    BlogImageInput,
    ImageModel,
    VisionModel,
)
from app.modules.ad_copy.schemas import AdChannel, AdModel
from scripts.run_instagram_food_benchmark import (
    DEFAULT_IMAGES_DIR,
    DEFAULT_MANIFEST,
    PROJECT_ROOT,
    _extension,
    find_metadata_csv,
    load_metadata,
    normalized_image_data_url,
    render_text_overlay,
    resolve_project_path,
    select_cases,
)


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "naver-blog-food-benchmark"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--metadata-csv", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case-limit", type=int, default=7)
    parser.add_argument(
        "--exclude-run",
        type=Path,
        help="Exclude image ids already listed in another benchmark run's plan.json.",
    )
    parser.add_argument(
        "--llm-model",
        choices=[model.value for model in AdModel],
        default=AdModel.OPENAI_GPT_5_4_MINI.value,
    )
    parser.add_argument(
        "--vision-model",
        choices=[model.value for model in VisionModel],
        default=VisionModel.OPENAI_GPT_5_4_MINI.value,
    )
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--disable-vision-analysis",
        action="store_true",
        help="Create posts from metadata only without sending the photo to Vision.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Call the configured models. Without this flag only the plan is saved.",
    )
    parser.add_argument(
        "--render-posters-from-run",
        type=Path,
        help="Re-render concise title posters for an existing successful run.",
    )
    return parser.parse_args()


def build_naver_request(case: dict[str, Any], llm_model: str) -> dict[str, Any]:
    original_product_name = case["food"]["product_name"]
    # Parenthesized menu options such as "(뼈)" are useful metadata but invalid
    # inside a hashtag. Keep the original name in the plan while using a clean,
    # customer-facing base name for SEO fields and generated copy.
    product_name = re.sub(r"\s*\([^)]*\)", "", original_product_name).strip()
    request = {
        **case["instagram_request"],
        "model": llm_model,
        "channel": AdChannel.NAVER_BLOG.value,
        "business_name": f"{product_name} 테스트 가게",
        "tone": "warm",
        "target_audiences": ["office_workers", "families"],
        "product_names": [product_name],
        "features": [f"업로드 사진에서 확인되는 {product_name}의 실제 형태와 색감"],
        "required_terms": [product_name],
        "interests": ["맛집", product_name],
        "blog_purpose": "메뉴 소개",
        "blog_emphasis": [
            "업로드 사진에서 실제로 확인되는 음식의 형태와 색감",
            "메뉴명과 방문을 고려할 수 있는 자연스러운 소개",
        ],
        "blog_style": "사진 중심의 자연스러운 정보형 포스팅",
        "seo_keywords": [product_name, f"{product_name} 메뉴"],
        "blog_length": "중간 길이",
        "additional_request": (
            "네이버 블로그에 바로 붙여넣을 수 있도록 제목과 짧은 문단으로 작성하세요. "
            "사진에서 확인할 수 없는 맛, 재료, 효능, 가격은 추측하지 마세요. "
            "내부 작업 지시문이나 JSON 필드 이름은 고객용 글에 노출하지 마세요."
        ),
    }
    return request


def build_plan(
    cases: list[dict[str, Any]],
    *,
    llm_model: str,
    vision_model: str,
) -> list[dict[str, Any]]:
    return [
        {
            "trial_id": f"{case['id']}__{llm_model.replace('/', '_')}__{vision_model.replace('/', '_').replace(':', '_')}",
            "case_id": case["id"],
            "image_id": case["image_id"],
            "product_name": case["food"]["product_name"],
            "business_category": case["food"]["business_category"],
            "product_group": case["food"]["product_group"],
            "source_image": case["image_path"],
            "llm_model": llm_model,
            "vision_model": vision_model,
        }
        for case in cases
    ]


def save_plan(
    run_dir: Path,
    plan: list[dict[str, Any]],
    metadata_path: Path,
) -> None:
    payload = {
        "version": 1,
        "channel": AdChannel.NAVER_BLOG.value,
        "selection": {
            "method": "diverse business categories and distinct product groups",
            "case_count": len(plan),
            "metadata": str(metadata_path.resolve()),
        },
        "cases": plan,
    }
    (run_dir / "plan.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def customer_product_name(value: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", value).strip()


def concise_poster_title(product_name: str) -> str:
    return f"{customer_product_name(product_name)}, 사진으로 먼저 만나보세요"


def save_blog_markdown(
    path: Path,
    *,
    title: str,
    body: str,
    model: str,
    vision_model: str,
    wall_latency_ms: float,
) -> None:
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                body,
                "",
                "---",
                "",
                f"- 문구 모델: `{model}`",
                f"- 사진 분석 모델: `{vision_model}`",
                f"- 총 소요 시간: `{wall_latency_ms / 1000:.1f}초`",
            ]
        ),
        encoding="utf-8",
    )


async def execute_case(
    case: dict[str, Any],
    plan_item: dict[str, Any],
    args: argparse.Namespace,
    run_dir: Path,
    jsonl_path: Path,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        started = perf_counter()
        record: dict[str, Any] = {**plan_item, "success": False}
        try:
            source_path = resolve_project_path(case["image_path"]).resolve()
            data_url, preprocessing = normalized_image_data_url(source_path)
            request = AdContentRequest(
                copy=build_naver_request(case, plan_item["llm_model"]),
                use_vision_analysis=not args.disable_vision_analysis,
                vision_model=VisionModel(plan_item["vision_model"]),
                # Naver Blog returns the uploaded/enhanced image and skips the
                # selected image-generation model.
                image_model=ImageModel.OPENAI_GPT_IMAGE_1_MINI,
                reference_image_data_url=data_url,
                blog_images=[
                    BlogImageInput(
                        id=case["image_id"],
                        name=case["food"]["product_name"],
                        data_url=data_url,
                    )
                ],
            )

            from app.extensions.ad_content.router import generate_content

            response = await generate_content(request)
            wall_latency_ms = round((perf_counter() - started) * 1000, 2)
            trial_dir = run_dir / "trials" / plan_item["trial_id"]
            trial_dir.mkdir(parents=True, exist_ok=True)

            saved_source = trial_dir / f"source-original-{source_path.name}"
            shutil.copy2(source_path, saved_source)
            blog_image = trial_dir / f"blog-image.{_extension(response.image.media_type)}"
            blog_image.write_bytes(base64.b64decode(response.image.image_base64))

            copy_result = response.copy_result
            recommendation = copy_result.channel_recommendation
            blog_title = (
                recommendation.publish_title
                or recommendation.blog_title
                or copy_result.headlines[0]
            )
            publish_body = recommendation.publish_body
            poster_title = concise_poster_title(case["food"]["product_name"])
            poster_path = render_text_overlay(
                blog_image,
                trial_dir / "blog-title-poster.png",
                poster_title,
                case["food"]["product_name"],
            )
            markdown_path = trial_dir / "naver-blog.md"
            save_blog_markdown(
                markdown_path,
                title=blog_title,
                body=publish_body,
                model=copy_result.routed_model,
                vision_model=plan_item["vision_model"],
                wall_latency_ms=wall_latency_ms,
            )

            response_payload = response.model_dump(mode="json", by_alias=True)
            response_payload["image"]["image_base64"] = "[saved_to_blog_image]"
            result_path = trial_dir / "result.json"
            result_path.write_text(
                json.dumps(response_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            record.update(
                success=True,
                preprocessing=preprocessing,
                copy_model_routed=copy_result.routed_model,
                copy_latency_ms=copy_result.latency_ms,
                image_model_actual=response.image.model,
                image_latency_ms=response.image.latency_ms,
                blog_title=blog_title,
                poster_title=poster_title,
                publish_body=publish_body,
                saved_source_image=str(saved_source.resolve()),
                blog_image=str(blog_image.resolve()),
                blog_title_poster=str(poster_path.resolve()),
                naver_blog_markdown=str(markdown_path.resolve()),
                result_json=str(result_path.resolve()),
                validation=response.validation,
            )
        except Exception as error:  # noqa: BLE001 - continue the review batch
            record.update(error_type=type(error).__name__, error=str(error))
            wall_latency_ms = round((perf_counter() - started) * 1000, 2)
        record["wall_latency_ms"] = wall_latency_ms
        append_jsonl(jsonl_path, record)
        status = "OK" if record["success"] else "FAIL"
        print(f"[{status}] {record['trial_id']} - {wall_latency_ms}ms", flush=True)
        return record


def write_manual_review(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "trial_id",
        "product_name",
        "success",
        "llm_model",
        "vision_model",
        "copy_model_routed",
        "wall_latency_ms",
        "blog_title",
        "poster_title",
        "saved_source_image",
        "blog_image",
        "blog_title_poster",
        "naver_blog_markdown",
        "result_json",
        "error",
        "review_status",
        "review_notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({**record, "review_status": "", "review_notes": ""})


def render_existing_posters(run_dir: Path) -> int:
    run_dir = run_dir.resolve()
    report_path = run_dir / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"Report not found: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    records = report.get("records", [])
    rendered = 0
    for record in records:
        if not record.get("success"):
            continue
        blog_image = Path(record["blog_image"])
        poster_path = Path(record["blog_title_poster"])
        poster_title = concise_poster_title(record["product_name"])
        render_text_overlay(
            blog_image,
            poster_path,
            poster_title,
            customer_product_name(record["product_name"]),
        )
        record["poster_title"] = poster_title
        rendered += 1
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_manual_review(run_dir / "manual-review.csv", records)
    print(f"Posters rendered: {rendered}")
    print(f"Run: {run_dir}")
    return 0


async def run(args: argparse.Namespace) -> int:
    if args.render_posters_from_run:
        return render_existing_posters(args.render_posters_from_run)
    if not 5 <= args.case_limit <= 10:
        raise ValueError("case-limit must be between 5 and 10.")
    if args.concurrency < 1:
        raise ValueError("concurrency must be at least 1.")

    metadata_path = find_metadata_csv(args.images_dir, args.metadata_csv)
    metadata_rows = load_metadata(metadata_path)
    if args.exclude_run:
        excluded_plan_path = args.exclude_run.resolve() / "plan.json"
        if not excluded_plan_path.is_file():
            raise FileNotFoundError(f"Excluded run plan not found: {excluded_plan_path}")
        excluded_plan = json.loads(excluded_plan_path.read_text(encoding="utf-8"))
        excluded_ids = {
            item["image_id"]
            for item in excluded_plan.get("cases", [])
            if item.get("image_id")
        }
        metadata_rows = [
            row
            for row in metadata_rows
            if row.get("final_image_id", "").strip() not in excluded_ids
        ]
        print(f"Excluded previous images: {len(excluded_ids)}")
    cases = select_cases(metadata_rows, args.images_dir, args.case_limit)
    plan = build_plan(
        cases,
        llm_model=args.llm_model,
        vision_model=args.vision_model,
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_dir.resolve() / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    save_plan(run_dir, plan, metadata_path)
    print(f"Cases: {len(cases)}")
    print(f"Plan: {run_dir / 'plan.json'}")
    if not args.execute:
        print("Dry run complete. Add --execute to call models.")
        return 0

    cases_by_id = {case["id"]: case for case in cases}
    jsonl_path = run_dir / "trials.jsonl"
    semaphore = asyncio.Semaphore(args.concurrency)
    records = await asyncio.gather(
        *(
            execute_case(
                cases_by_id[item["case_id"]],
                item,
                args,
                run_dir,
                jsonl_path,
                semaphore,
            )
            for item in plan
        )
    )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "channel": AdChannel.NAVER_BLOG.value,
        "case_count": len(records),
        "success_count": sum(bool(record["success"]) for record in records),
        "failure_count": sum(not record["success"] for record in records),
        "records": records,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_manual_review(run_dir / "manual-review.csv", records)
    print(f"Report: {run_dir / 'report.json'}")
    print(f"Success: {report['success_count']}/{report['case_count']}")
    return 0 if report["failure_count"] == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
