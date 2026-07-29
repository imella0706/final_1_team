"""접시 분할 주석 목록을 중복 그룹 단위로 train/val/test에 배정한다."""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1] / "data/training/plate_segmentation"
    parser = argparse.ArgumentParser(description="동일 촬영 그룹이 split을 넘지 않게 배정합니다.")
    parser.add_argument("--manifest", type=Path, default=root / "plate_annotation_manifest.csv")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = handle.seek(0) or list(csv.DictReader(handle).fieldnames or [])
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        group = row.get("split_group") or row["image_file_name"]
        groups[group].append(row)
    group_items = list(groups.items())
    random.Random(args.seed).shuffle(group_items)
    target_counts = {"train": round(len(rows) * 0.70), "val": round(len(rows) * 0.15)}
    totals = {"train": 0, "val": 0, "test": 0}
    for _, grouped_rows in group_items:
        split = "train" if totals["train"] < target_counts["train"] else "val" if totals["val"] < target_counts["val"] else "test"
        for row in grouped_rows:
            row["target_split"] = split
        totals[split] += len(grouped_rows)
    with args.manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"split 배정 완료: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
