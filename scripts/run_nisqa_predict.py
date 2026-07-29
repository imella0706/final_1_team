#!/usr/bin/env python3
"""Run the official NISQA predictor with a configurable segment limit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nisqa-root", required=True, type=Path)
    parser.add_argument("--pretrained-model", required=True, type=Path)
    parser.add_argument("--csv-file", required=True, type=Path)
    parser.add_argument("--csv-deg", default="deg")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--max-segments", type=int, default=10_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(args.nisqa_root))

    from nisqa.NISQA_model import nisqaModel

    model_args = {
        "mode": "predict_csv",
        "pretrained_model": str(args.pretrained_model),
        "deg": None,
        "data_dir": "",
        "output_dir": str(args.output_dir),
        "csv_file": str(args.csv_file),
        "csv_deg": args.csv_deg,
        "num_workers": args.num_workers,
        "bs": args.batch_size,
        "ms_channel": None,
        "ms_max_segments": args.max_segments,
        "tr_bs_val": args.batch_size,
        "tr_num_workers": args.num_workers,
    }
    nisqa = nisqaModel(model_args)
    nisqa.predict()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
