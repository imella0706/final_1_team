"""Restore the local SNS TrendCard v2 runtime artifact from Git history.

The reviewed source cards were committed before the generated dataset paths
were removed from Git. This script provides a deterministic local fallback
when the GCS artifact is unavailable.
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "280ea67"
SOURCE_DIRECTORY = "gather_data/trendcards"
OUTPUT_DIRECTORY = (
    REPO_ROOT
    / "data"
    / "processed"
    / "sns_trend"
    / "v2"
    / "cross_platform_signal_top_candidates"
)


def git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def source_family(path: str) -> str:
    return Path(path).stem.split("_", maxsplit=1)[0]


def main() -> None:
    paths = [
        line.strip()
        for line in git_output(
            "ls-tree",
            "-r",
            "--name-only",
            SOURCE_COMMIT,
            SOURCE_DIRECTORY,
        ).splitlines()
        if line.strip().endswith(".json")
    ]
    if not paths:
        raise RuntimeError(
            f"No TrendCard JSON files found in {SOURCE_COMMIT}:{SOURCE_DIRECTORY}"
        )

    cards: list[dict[str, object]] = []
    rows: list[dict[str, str]] = []
    for path in paths:
        card = json.loads(git_output("show", f"{SOURCE_COMMIT}:{path}"))
        if card.get("schema_version") != "2.0":
            raise RuntimeError(f"Unsupported schema_version in {path}")
        if card.get("curation_meta", {}).get("status") != "reviewed":
            raise RuntimeError(f"Unreviewed TrendCard in {path}")
        cards.append(card)
        rows.append(
            {
                "meme_id": str(card.get("meme_id", "")),
                "display_name": str(card.get("display_name", "")),
                "source_family": source_family(path),
                "curation_status": str(card.get("curation_meta", {}).get("status", "")),
                "trend_status": str(card.get("trend_meta", {}).get("status", "")),
                "sources": json.dumps(
                    card.get("trend_meta", {}).get("sources", []),
                    ensure_ascii=False,
                ),
            }
        )

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIRECTORY / "cross_platform_signal_top_candidates.json"
    csv_path = OUTPUT_DIRECTORY / "cross_platform_signal_top_candidates.csv"

    json_path.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Restored {len(cards)} TrendCards")
    print(json_path)
    print(csv_path)


if __name__ == "__main__":
    main()
