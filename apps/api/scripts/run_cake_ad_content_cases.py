"""Run cake ad-content test cases with a fixed reference image.

This script calls the integrated ad-content pipeline directly, so the API server
does not need to be running. Generated artifacts are saved by the normal
ad-content artifact store under outputs/ad-content.
"""

import argparse
import asyncio
import base64
import json
import mimetypes
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import HTTPException

from app.extensions.ad_content.router import generate_content
from app.extensions.ad_content.schemas import AdContentRequest, ImageModel
from app.modules.ad_copy.schemas import AdModel


API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_REFERENCE_IMAGE = PROJECT_ROOT / "data" / "cake" / "투썸 케이크(초코).jpg"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "outputs" / "ad-content-batches"

AGE_CASES = [
    {
        "id": "age-teens",
        "age_groups": ["teens"],
        "target_audiences": ["students"],
        "audience_detail": "친구 생일파티 케이크를 찾는 10대 고객",
    },
    {
        "id": "age-twenties",
        "age_groups": ["twenties"],
        "target_audiences": ["college_students", "couples"],
        "audience_detail": "감성 카페와 생일파티 사진을 인스타그램에 올리는 20대 고객",
    },
    {
        "id": "age-thirties",
        "age_groups": ["thirties"],
        "target_audiences": ["office_workers", "couples"],
        "audience_detail": "퇴근 후 생일파티용 케이크를 픽업하려는 30대 직장인",
    },
    {
        "id": "age-forties",
        "age_groups": ["forties"],
        "target_audiences": ["families"],
        "audience_detail": "가족 생일파티에 어울리는 케이크를 찾는 40대 고객",
    },
    {
        "id": "age-fifties-plus",
        "age_groups": ["fifties_plus"],
        "target_audiences": ["families"],
        "audience_detail": "가족 모임 선물용 케이크를 고르는 50대 이상 고객",
    },
]

SITUATION_CASES = [
    {
        "id": "situation-new-menu",
        "situation": "new_menu",
        "audience_detail": "신메뉴 케이크를 발견하고 저장해두는 인스타그램 고객",
    },
    {
        "id": "situation-event",
        "situation": "event",
        "audience_detail": "생일파티와 기념일 이벤트 케이크를 찾는 고객",
    },
    {
        "id": "situation-delivery",
        "situation": "delivery",
        "audience_detail": "생일파티 당일 배달 가능한 케이크를 찾는 고객",
    },
    {
        "id": "situation-takeout",
        "situation": "takeout",
        "audience_detail": "파티 전에 빠르게 픽업할 케이크를 찾는 고객",
    },
    {
        "id": "situation-visit",
        "situation": "visit",
        "audience_detail": "연남동 카페 방문 후 케이크를 포장하려는 고객",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-image", type=Path, default=DEFAULT_REFERENCE_IMAGE)
    parser.add_argument("--summary-dir", type=Path, default=DEFAULT_SUMMARY_DIR)
    parser.add_argument("--copy-model", choices=[model.value for model in AdModel], default=AdModel.OPENAI_GPT_5_4.value)
    parser.add_argument("--image-model", choices=[model.value for model in ImageModel], default=ImageModel.OPENAI_GPT_IMAGE_1_MINI.value)
    parser.add_argument("--case-set", choices=["age", "situation", "age-and-situation", "matrix"], default="age-and-situation")
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def image_to_data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def base_copy_payload() -> dict[str, Any]:
    return {
        "model": AdModel.OPENAI_GPT_5_4.value,
        "business_name": "나의최고의 하루",
        "business_type": "cafe",
        "situation": "event",
        "age_groups": ["twenties"],
        "target_audiences": ["couples"],
        "tone": "emotional",
        "product_names": ["초코케익"],
        "features": ["생일 파티에 적합한 케이크"],
        "channel": "instagram",
        "promotion": None,
        "required_terms": ["초코케익", "35,000원"],
        "prohibited_terms": ["최고", "무조건", "인생 맛집"],
        "gender": "all",
        "occupation_group": "none",
        "product_price": "35,000원",
        "interests": ["디저트 투어", "감성 카페"],
        "region": "서울 마포구 연남동",
        "trade_area": "연남동 골목상권",
        "audience_detail": "생일 파티에 적합한 초코케익을 찾는 인스타그램 고객",
    }


def build_cases(case_set: str, copy_model: str, image_model: str, reference_data_url: str) -> list[dict[str, Any]]:
    base = base_copy_payload()
    cases: list[dict[str, Any]] = []

    if case_set in {"age", "age-and-situation"}:
        for age_case in AGE_CASES:
            copy_payload = {**base, **age_case, "model": copy_model}
            copy_payload.pop("id", None)
            cases.append(
                {
                    "id": age_case["id"],
                    "copy": copy_payload,
                    "image_model": image_model,
                    "image_width": 1024,
                    "image_height": 1280,
                    "reference_image_data_url": reference_data_url,
                }
            )

    if case_set in {"situation", "age-and-situation"}:
        for situation_case in SITUATION_CASES:
            copy_payload = {**base, **situation_case, "model": copy_model}
            copy_payload.pop("id", None)
            cases.append(
                {
                    "id": situation_case["id"],
                    "copy": copy_payload,
                    "image_model": image_model,
                    "image_width": 1024,
                    "image_height": 1280,
                    "reference_image_data_url": reference_data_url,
                }
            )

    if case_set == "matrix":
        for age_case in AGE_CASES:
            for situation_case in SITUATION_CASES:
                case_id = f"{age_case['id']}-{situation_case['id']}"
                copy_payload = {
                    **base,
                    **age_case,
                    **situation_case,
                    "model": copy_model,
                }
                copy_payload.pop("id", None)
                cases.append(
                    {
                        "id": case_id,
                        "copy": copy_payload,
                        "image_model": image_model,
                        "image_width": 1024,
                        "image_height": 1280,
                        "reference_image_data_url": reference_data_url,
                    }
                )

    return cases


async def run_case(case: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
    async with semaphore:
        started_at = perf_counter()
        request = AdContentRequest.model_validate(case)
        record: dict[str, Any] = {"id": case["id"], "success": False}
        try:
            response = await generate_content(request)
        except HTTPException as error:
            record.update(
                {
                    "error_type": "HTTPException",
                    "error": str(error.detail),
                    "status_code": error.status_code,
                }
            )
        except Exception as error:
            record.update({"error_type": type(error).__name__, "error": str(error)})
        else:
            record.update(
                {
                    "success": True,
                    "copy_model": response.copy_result.model,
                    "image_model": response.image.model,
                    "headline": response.copy_result.headlines[0] if response.copy_result.headlines else "",
                    "artifacts": response.artifacts,
                    "validation": response.validation,
                }
            )
        finally:
            record["wall_latency_ms"] = round((perf_counter() - started_at) * 1000, 2)
        return record


async def run(args: argparse.Namespace) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.reference_image.exists():
        raise FileNotFoundError(f"Reference image not found: {args.reference_image}")

    reference_data_url = image_to_data_url(args.reference_image)
    cases = build_cases(args.case_set, args.copy_model, args.image_model, reference_data_url)
    if args.case_limit:
        cases = cases[: args.case_limit]

    args.summary_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    case_path = args.summary_dir / f"cake-ad-content-cases-{timestamp}.json"
    summary_path = args.summary_dir / f"cake-ad-content-summary-{timestamp}.json"

    case_path.write_text(
        json.dumps(
            [
                {**case, "reference_image_data_url": "[base64_reference_image]"}
                for case in cases
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Cases: {len(cases)}")
    print(f"Case file: {case_path}")

    if args.dry_run:
        print("Dry run only. No model calls were made.")
        return 0

    semaphore = asyncio.Semaphore(args.concurrency)
    records = await asyncio.gather(*(run_case(case, semaphore) for case in cases))
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "case_set": args.case_set,
        "reference_image": str(args.reference_image),
        "copy_model": args.copy_model,
        "image_model": args.image_model,
        "records": records,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    success_count = sum(1 for record in records if record["success"])
    print(f"Success: {success_count}/{len(records)}")
    print(f"Summary: {summary_path}")
    for record in records:
        status = "OK" if record["success"] else "FAIL"
        artifact_dir = record.get("artifacts", {}).get("directory", "")
        print(f"- {status} {record['id']} {artifact_dir}")
    return 0 if success_count == len(records) else 1


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
