from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate mask-quality and rim-repair results for a fixed regression set."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))

    results: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        image_id = record["final_image_id"]
        report_path = args.reports_dir / f"{image_id}_background_replacement_report.json"
        if not report_path.exists():
            item = {
                "final_image_id": image_id,
                "status": "missing_report",
                "container_hint": record["container_hint"],
                "appearance_hint": record["appearance_hint"],
            }
        else:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            stages = report.get("stages", {})
            quality = stages.get("step_2c_mask_quality", {})
            repair = stages.get("step_5d_plate_edge_repair", {})
            item = {
                "final_image_id": image_id,
                "status": report.get("status", "unknown"),
                "container_hint": record["container_hint"],
                "appearance_hint": record["appearance_hint"],
                "food_mask_passed": bool(
                    quality.get("food", {}).get("passed", False)
                ),
                "plate_mask_passed": bool(
                    quality.get("plate", {}).get("passed", False)
                ),
                "shape_type": quality.get("plate", {}).get("shape_type", "unknown"),
                "adaptive_rim_used": bool(
                    repair.get("adaptive_rim_observation", {}).get("used", False)
                ),
                "synthetic_rim_allowed": bool(
                    repair.get("synthetic_rim_allowed", False)
                ),
                "synthetic_rim_bridge_pixels": int(
                    repair.get("synthetic_rim_bridge_pixels", 0)
                ),
            }
        results.append(item)
        grouped[f'{item["container_hint"]}/{item["appearance_hint"]}'].append(item)

    def _rate(items: list[dict[str, Any]], key: str) -> float:
        available = [item for item in items if item.get("status") != "missing_report"]
        if not available:
            return 0.0
        return round(
            sum(bool(item.get(key, False)) for item in available) / len(available),
            6,
        )

    summary = {
        "manifest": str(args.manifest.resolve()),
        "reports_dir": str(args.reports_dir.resolve()),
        "total": len(results),
        "reports_found": sum(
            item.get("status") != "missing_report" for item in results
        ),
        "food_mask_pass_rate": _rate(results, "food_mask_passed"),
        "plate_mask_pass_rate": _rate(results, "plate_mask_passed"),
        "adaptive_rim_use_rate": _rate(results, "adaptive_rim_used"),
        "groups": {
            group: {
                "count": len(items),
                "food_mask_pass_rate": _rate(items, "food_mask_passed"),
                "plate_mask_pass_rate": _rate(items, "plate_mask_passed"),
                "adaptive_rim_use_rate": _rate(items, "adaptive_rim_used"),
            }
            for group, items in sorted(grouped.items())
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
