"""Model selections exposed by the v2 test CLI.

This module only reads the existing production model catalogs.  It does not
define prompts, alter prompt payloads, or change provider configuration.
"""

from __future__ import annotations

import re

from app.extensions.ad_content.schemas import ImageModel
from app.modules.ad_copy.models import MODEL_CATALOG
from app.modules.ad_copy.schemas import AdModel


def available_llm_models() -> tuple[AdModel, ...]:
    """Return canonical, user-selectable models from the production catalog."""
    return tuple(spec.id for spec in MODEL_CATALOG)


def available_image_models() -> tuple[ImageModel, ...]:
    """Return every image-generation model supported by the production enum."""
    return tuple(ImageModel)


def model_slug(model: AdModel | ImageModel | str) -> str:
    """Make a deterministic, filesystem-safe identifier for a model run."""
    value = getattr(model, "value", str(model))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
