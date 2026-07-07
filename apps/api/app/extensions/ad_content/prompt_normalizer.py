from app.extensions.ad_content.image_prompt import build_ad_image_prompt
from app.extensions.ad_content.product_visualizer import ProductVisualization
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse

MAX_IMAGE_PROMPT_CHARS = 3800
MAX_NEGATIVE_PROMPT_CHARS = 1800


def _limit_prompt(text: str, max_chars: int) -> str:
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(",", 1)[0].strip()


def normalize_image_prompt(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None = None,
) -> tuple[str, str]:
    prompt, negative_prompt = build_ad_image_prompt(copy, request, product_visualization)
    return (
        _limit_prompt(prompt, MAX_IMAGE_PROMPT_CHARS),
        _limit_prompt(negative_prompt, MAX_NEGATIVE_PROMPT_CHARS),
    )
