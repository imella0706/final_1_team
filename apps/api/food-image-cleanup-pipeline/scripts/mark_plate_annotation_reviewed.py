"""CVAT에서 검수해 내보낸 COCO 파일을 기준으로 작업 목록 상태를 갱신한다."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1] / "data/training/plate_segmentation"
    parser = argparse.ArgumentParser(description="검수 완료 COCO 파일로 접시 분할 작업 목록을 갱신합니다.")
    parser.add_argument("--coco-json", type=Path, required=True, help="CVAT에서 내보낸 COCO Instances JSON")
    parser.add_argument("--manifest", type=Path, default=root / "plate_annotation_manifest.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.coco_json.read_text(encoding="utf-8"))
    category_names = {item["id"]: item["name"] for item in payload.get("categories", [])}
    wanted = {"plate_full", "food_visible"}
    image_names = {item["id"]: item["file_name"] for item in payload.get("images", [])}
    classes_by_file: dict[str, set[str]] = defaultdict(set)
    for annotation in payload.get("annotations", []):
        name = image_names.get(annotation.get("image_id"))
        category = category_names.get(annotation.get("category_id"))
        if name and category in wanted:
            classes_by_file[name].add(category)

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0]) if rows else []
    for field in ("review_status", "review_note"):
        if field not in fields:
            fields.append(field)

    completed = 0
    incomplete = 0
    for row in rows:
        classes = classes_by_file.get(row["image_file_name"], set())
        if classes == wanted:
            row["plate_full_status"] = "completed"
            row["food_visible_status"] = "completed"
            row["review_status"] = "approved"
            row["review_note"] = "CVAT 검수 COCO에서 두 인스턴스 확인"
            completed += 1
        elif classes:
            row["review_status"] = "incomplete"
            row["review_note"] = f"검수 COCO에 누락 클래스: {', '.join(sorted(wanted - classes))}"
            incomplete += 1

    with args.manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"completed": completed, "incomplete": incomplete, "manifest": str(args.manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
