from app.extensions.ad_content.image_prompt import build_ad_image_prompt
from app.extensions.ad_content.product_visualizer import ProductVisualization
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse

IMAGE_PROMPT_MAX_CHARS = 3900
NEGATIVE_PROMPT_MAX_CHARS = 1900


def _compact_prompt(value: str, max_chars: int) -> str:
    compacted = "\n".join(line.strip() for line in value.splitlines() if line.strip())
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 80].rstrip(" ,.\n") + (
        "\nKeep all listed product identities exact. No readable text."
    )


def normalize_image_prompt(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None = None,
    reference_image_context: str | None = None,
    reference_image_provided: bool = False,
) -> tuple[str, str]:
    image_prompt, negative_prompt = build_ad_image_prompt(
        copy,
        request,
        product_visualization,
        reference_image_context,
        reference_image_provided,
    )
    return (
        _compact_prompt(image_prompt, IMAGE_PROMPT_MAX_CHARS),
        _compact_prompt(negative_prompt, NEGATIVE_PROMPT_MAX_CHARS),
    )


def compact_regenerated_prompt(image_prompt: str) -> str:
    return _compact_prompt(image_prompt, IMAGE_PROMPT_MAX_CHARS)
