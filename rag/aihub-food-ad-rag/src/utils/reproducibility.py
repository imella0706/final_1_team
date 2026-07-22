from __future__ import annotations

import os
import random
from typing import Any, Dict

DEFAULT_RANDOM_SEED = 42


def set_global_seed(seed: int = DEFAULT_RANDOM_SEED) -> Dict[str, Any]:
    """Set best-effort deterministic seeds for the data pipeline."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)

    result: Dict[str, Any] = {
        "seed": seed,
        "python_random": True,
        "pythonhashseed": str(seed),
        "numpy": False,
        "torch": False,
        "torch_deterministic_algorithms": False,
    }

    try:
        import numpy as np

        np.random.seed(seed)
        result["numpy"] = True
    except Exception as exc:  # pragma: no cover - optional dependency guard
        result["numpy_error"] = str(exc)

    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
        if hasattr(torch, "use_deterministic_algorithms"):
            try:
                torch.use_deterministic_algorithms(True, warn_only=True)
                result["torch_deterministic_algorithms"] = True
            except TypeError:
                torch.use_deterministic_algorithms(True)
                result["torch_deterministic_algorithms"] = True
        result["torch"] = True
    except Exception as exc:  # pragma: no cover - optional dependency guard
        result["torch_error"] = str(exc)

    return result
