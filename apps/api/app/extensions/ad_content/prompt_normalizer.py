from app.extensions.ad_content.image_prompt import build_ad_image_prompt
from app.extensions.ad_content.product_visualizer import ProductVisualization
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse


def normalize_image_prompt(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None = None,
) -> tuple[str, str]:
    return build_ad_image_prompt(copy, request, product_visualization)
