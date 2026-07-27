from __future__ import annotations

import sys
from pathlib import Path


# [Design Intent] Make repository-root imports stable for both `pytest` and
# `python -m pytest`; the console-script entrypoint may not put cwd on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
