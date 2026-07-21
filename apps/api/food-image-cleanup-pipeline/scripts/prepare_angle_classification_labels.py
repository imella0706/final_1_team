"""EfficientNet-B0 촬영 각도 분류용 라벨 원장을 준비한다.

객체 탐지와 달리 이미지 분류는 YOLO 형식의 좌표 TXT가 필요하지 않다.
이 스크립트는 이미지별 최종 각도 라벨을 기록할 CSV 원장을 만든다.

원본 메타데이터의 ``caption_camera_angle`` / ``view_type``은 4개 클래스
(``top``, ``side``, ``45``, ``low``)의 정답이 아니므로 자동 확정하지 않는다.
특히 ``front_or_45_degree``와 ``view_type=side``는 카메라 높이·시점을
구분하지 못한다. 후보와 근거만 기록하고 ``final_angle``은 검토자가 채운다.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ANGLE_CLASSES = ("top", "45")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EfficientNet-B0 각도 분류 라벨 원장을 생성합니다.")
    parser.add_argument("--images-dir", type=Path, required=True, help="train/val 이미지가 있는 디렉터리")
    parser.add_argument("--metadata", type=Path, required=True, help="원본 이미지 메타데이터 CSV")
    parser.add_argument("--output-dir", type=Path, required=True, help="생성할 라벨 디렉터리")
    return parser.parse_args()


def candidate_from_metadata(row: dict[str, str]) -> tuple[str, str, str]:
    """메타데이터로부터 검토용 후보만 반환한다.

    top_view도 일부 사선 이미지가 포함될 수 있어 최종 정답으로 확정하지 않는다.
    나머지 두 메타데이터 값은 4개 카메라 각도와 의미가 달라 후보를 비워 둔다.
    """

    if row.get("caption_camera_angle") == "top_view":
        return "top", "낮음", "원본 메타데이터가 top_view이지만 사선 이미지 포함 여부를 눈으로 확인해야 합니다."
    return "", "없음", "원본 메타데이터가 45도·low·side 카메라 각도를 구분하지 않습니다."


def main() -> int:
    args = parse_args()
    image_files = sorted(
        path for path in args.images_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not image_files:
        raise SystemExit(f"이미지를 찾지 못했습니다: {args.images_dir}")

    with args.metadata.open("r", encoding="utf-8-sig", newline="") as file:
        metadata_rows = list(csv.DictReader(file))
    metadata_by_name = {row.get("final_image_file_name", ""): row for row in metadata_rows}

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "angle_label_manifest.csv"
    review_path = args.output_dir / "angle_label_review.csv"
    class_map_path = args.output_dir / "class_map.json"
    summary_path = args.output_dir / "label_summary.json"
    guide_path = args.output_dir / "README.md"

    fieldnames = [
        "split",
        "image_path",
        "image_file_name",
        "source_final_image_id",
        "source_caption_camera_angle",
        "source_view_type",
        "candidate_angle",
        "candidate_confidence",
        "final_angle",
        "label_status",
        "review_note",
    ]
    rows: list[dict[str, str]] = []
    for image_path in image_files:
        source = metadata_by_name.get(image_path.name, {})
        candidate, confidence, note = candidate_from_metadata(source)
        rows.append(
            {
                "split": image_path.parent.name,
                "image_path": image_path.relative_to(args.images_dir).as_posix(),
                "image_file_name": image_path.name,
                "source_final_image_id": source.get("final_image_id", ""),
                "source_caption_camera_angle": source.get("caption_camera_angle", ""),
                "source_view_type": source.get("view_type", ""),
                "candidate_angle": candidate,
                "candidate_confidence": confidence,
                "final_angle": "",
                "label_status": "검토_필요",
                "review_note": note,
            }
        )

    for path in (manifest_path, review_path):
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    class_map_path.write_text(
        json.dumps({name: index for index, name in enumerate(ANGLE_CLASSES)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "total_images": len(rows),
        "splits": dict(Counter(row["split"] for row in rows)),
        "source_caption_camera_angle": dict(Counter(row["source_caption_camera_angle"] for row in rows)),
        "source_view_type": dict(Counter(row["source_view_type"] for row in rows)),
        "candidate_angle": dict(Counter(row["candidate_angle"] or "미지정" for row in rows)),
        "final_angle": "모든 행을 검토한 뒤 final_angle에 top, side, 45, low 중 하나를 입력해야 합니다.",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    guide_path.write_text(
        "# EfficientNet-B0 촬영 각도 라벨\n\n"
        "이 폴더는 이미지 분류 학습용 라벨 원장입니다. 객체 탐지의 YOLO TXT 좌표 라벨은 사용하지 않습니다.\n\n"
        "`angle_label_review.csv`의 `final_angle` 열에 아래 값 중 하나를 입력하세요.\n\n"
        "- `top`: 카메라가 음식·용기 위쪽에 거의 수직으로 위치한 탑뷰\n"
        "- `side`: 카메라가 테이블 높이와 가깝고 음식의 옆면이 주로 보이는 시점\n"
        "- `45`: 위쪽과 옆면이 함께 보이는 약 30~60도 사선 시점\n"
        "- `low`: 접시 높이보다 낮거나 매우 낮은 수평 시점\n\n"
        "원본 메타데이터의 `caption_camera_angle`과 `view_type`은 이 4개 클래스의 정답이 아닙니다. "
        "따라서 `candidate_angle`은 검토를 돕기 위한 참고값이며, `final_angle`을 확정하기 전에는 학습에 사용하면 안 됩니다.\n",
        encoding="utf-8",
    )
    print(f"라벨 원장 생성 완료: {manifest_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
