from __future__ import annotations

import argparse
import json

from brandmate_meme_validation import run_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate BrandMate weekly meme CSV.")
    parser.add_argument("--base-dir", default="/opt/airflow/mock_gcs")
    parser.add_argument("--week", default=None)
    args = parser.parse_args()

    result = run_validation(base_dir=args.base_dir, week=args.week)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
