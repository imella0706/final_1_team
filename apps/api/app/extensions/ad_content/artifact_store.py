import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.extensions.ad_content.schemas import AdContentResponse


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ARTIFACT_ROOT = PROJECT_ROOT / "outputs" / "ad-content"
KST = timezone(timedelta(hours=9))


def _safe_name(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return normalized.strip("._-") or "unknown"


def _media_extension(media_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(media_type.lower(), "png")


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def save_ad_content_artifacts(response: AdContentResponse) -> dict[str, str]:
    """Persist generated copy JSON and generated image under outputs/ad-content."""

    saved_at = datetime.now(KST)
    timestamp = saved_at.strftime("%Y%m%d-%H%M%S")
    copy_model = _safe_name(response.models.get("copy_model") or response.copy_result.model)
    image_model = _safe_name(response.models.get("image_model") or response.image.model)
    run_name = f"{timestamp}-{copy_model}-{image_model}"

    output_dir = ARTIFACT_ROOT / run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = output_dir / f"{run_name}.json"
    image_extension = _media_extension(response.image.media_type)
    image_path = output_dir / f"{run_name}.{image_extension}"
    prompt_path = output_dir / f"{run_name}-image-prompt.txt"
    llm_prompt_path = output_dir / f"{run_name}-llm-prompt.json"
    vision_prompt_path = output_dir / f"{run_name}-vision-prompt.json"

    metadata: dict[str, Any] = response.model_dump(mode="json", by_alias=True)
    metadata["image"]["image_base64"] = "[saved_to_image_file]"
    metadata["saved_at"] = saved_at.isoformat()
    metadata["generated_at"] = saved_at.isoformat()
    metadata["total_latency_ms"] = (
        int(getattr(response.copy_result, "latency_ms", 0) or 0)
        + int(getattr(response.image, "latency_ms", 0) or 0)
    )

    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prompt_artifact = ""
    if response.image_prompt.strip():
        prompt_path.write_text(response.image_prompt, encoding="utf-8")
        prompt_artifact = _relative(prompt_path)
    llm_prompt_path.write_text(
        json.dumps(getattr(response, "llm_prompt", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    vision_prompt_path.write_text(
        json.dumps(getattr(response, "vision_prompt", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image_path.write_bytes(base64.b64decode(response.image.image_base64))

    artifacts = {
        "directory": _relative(output_dir),
        "metadata_json": _relative(metadata_path),
        "image": _relative(image_path),
        "llm_prompt": _relative(llm_prompt_path),
        "vision_prompt": _relative(vision_prompt_path),
    }
    if prompt_artifact:
        artifacts["image_prompt"] = prompt_artifact
    return artifacts
