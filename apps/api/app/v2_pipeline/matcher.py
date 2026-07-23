"""Image/prompt matcher; it never alters the stored prompt_keywords text."""
from __future__ import annotations
import base64, hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from app.v2_pipeline.loader import DataRecord

BUSINESS_CATEGORY_MAP = {"cafe":"cafe", "bakery":"bakery", "dessert":"dessert", "restaurant":"restaurant", "pub":"pub"}
AD_USE_CASE_MAP = {"bakery_product_promotion":"new_menu", "cafe_product_promotion":"new_menu", "dessert_product_promotion":"new_menu", "restaurant_product_promotion":"visit", "pub_product_promotion":"visit", "product_promotion":"new_menu", "new_menu":"new_menu", "discount":"discount", "event":"event", "delivery":"delivery", "takeout":"takeout", "visit":"visit"}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_MODEL_IMAGE_DATA_URL_LENGTH = 3_800_000
class MatchError(ValueError): pass
@dataclass(frozen=True)
class MatchedRecord:
    record: DataRecord
    business_type: str
    situation: str
    image_data_url: str
    prompt_hash: str
def _compute_sha256(text: str) -> str: return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _encode_model_input_image(path: Path) -> bytes:
    """Create an API-safe, bounded JPEG in memory; never modify ``path``."""
    try:
        with Image.open(path) as source:
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                normalized = Image.new("RGB", rgba.size, "white")
                normalized.paste(rgba, mask=rgba.getchannel("A"))
            else:
                normalized = image.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise MatchError(f"Unsupported or corrupt image content: {path}") from exc

    # The public request schema caps data URLs at 4,000,000 characters.
    # Multiple quality/dimension candidates also convert MPO and unusual source
    # encodings into a single-frame RGB JPEG accepted by image-edit providers.
    for max_dimension in (1024,):
        candidate = normalized.copy()
        candidate.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        for quality in (90, 85, 80, 75, 70, 65):
            buffer = BytesIO()
            candidate.save(buffer, format="JPEG", quality=quality, optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            if len("data:image/jpeg;base64,") + len(encoded) <= MAX_MODEL_IMAGE_DATA_URL_LENGTH:
                return buffer.getvalue()
    raise MatchError(
        f"Image could not be encoded below the model input limit: {path}"
    )


def _image_to_data_url(path: Path) -> str:
    if not path.exists(): raise MatchError(f"Image file not found: {path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS: raise MatchError(f"Unsupported image extension '{ext}' for file: {path}")
    if path.stat().st_size == 0: raise MatchError(f"Image file is empty: {path}")
    encoded = base64.b64encode(_encode_model_input_image(path)).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
def match_record(record: DataRecord) -> MatchedRecord:
    business_type = BUSINESS_CATEGORY_MAP.get(record.business_category)
    if business_type is None: raise MatchError(f"[{record.final_image_id}] Unknown business_category '{record.business_category}'.")
    return MatchedRecord(record, business_type, AD_USE_CASE_MAP.get(record.ad_use_case, "new_menu"), _image_to_data_url(record.abs_image_path), _compute_sha256(record.prompt_keywords))
def build_copy_request_payload(
    matched: MatchedRecord,
    channel: str = "instagram",
    llm_model: str | None = None,
) -> dict:
    payload = {"business_name": matched.record.product_name, "business_type": matched.business_type,
            "situation": matched.situation, "tone":"friendly", "product_names":[matched.record.product_name],
            "features":[matched.record.prompt_keywords], "channel":channel, "age_groups":["twenties"],
            "target_audiences":["office_workers"]}
    if llm_model is not None:
        payload["model"] = llm_model
    return payload
