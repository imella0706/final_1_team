import json
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    infer_provider,
    resolve_api_key,
    resolve_base_url,
    resolve_model_name,
)
from app.modules.model_runtime.schemas import TextRuntimeProvider


class ProductVisual(BaseModel):
    original_name: str = Field(min_length=1, max_length=120)
    english_name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    visual_description: list[str] = Field(min_length=1, max_length=12)
    serving_style: list[str] = Field(min_length=1, max_length=8)
    must_show: list[str] = Field(min_length=1, max_length=12)
    must_not_replace_with: list[str] = Field(default_factory=list, max_length=12)


class ProductVisualization(BaseModel):
    products: list[ProductVisual] = Field(min_length=1, max_length=10)


class ProductVisualizer:
    def build_prompt(
        self,
        request: AdCopyRequest,
        copy: AdCopyResponse,
        reference_profiles: list[ProductVisual] | None = None,
    ) -> str:
        visual_brief = copy.visual_brief.model_dump(mode="json")
        references = [
            product.model_dump(mode="json")
            for product in (reference_profiles or [])
        ]
        return f"""You are a Product Visualizer for multimodal advertising generation.

Your only responsibility is to convert user-entered product names into detailed visual descriptions.
You are NOT an image generation model.
You are NOT a copywriter.

Return JSON only. Do not return markdown. Do not explain.

INPUT
Business type: {request.business_type.value}
Product names: {json.dumps(request.product_names, ensure_ascii=False)}
Features: {json.dumps(request.features, ensure_ascii=False)}
Visual brief: {json.dumps(visual_brief, ensure_ascii=False)}
Reference visual profiles from licensed sources, if available: {json.dumps(references, ensure_ascii=False)}

RULES
1. Every product in Product names must appear exactly once in products.
2. original_name must be the exact user-entered product name. Never modify it.
3. english_name must be a natural English translation or description. Do not simply transliterate.
4. category must describe the product type, such as Dessert, Coffee, Tea, Ade, Bread, Restaurant Menu, Alcohol, Object, Gift, Package, Beauty Product, Fashion Item, or Merchandise.
5. visual_description must describe visible characteristics only. Do not describe taste, emotion, mood, or abstract qualities.
6. serving_style must describe how the product should appear in the image.
7. must_show must list visible objects, materials, textures, colors, shapes, packaging, toppings, props, or details that make the product recognizable.
8. must_not_replace_with must list visually similar products that must NOT replace this product.
9. If the product is unfamiliar, infer the most probable visual appearance from the product name and features. Do not leave fields empty.
10. For multiple products, describe each product independently.
11. Convert features into visual cues when possible.
12. If reference visual profiles are available, use their visual_description, serving_style, must_show, and must_not_replace_with as grounded visual evidence.
13. Do not copy a reference image composition. Use only general visual traits.

OUTPUT JSON FORMAT
{{
  "products": [
    {{
      "original_name": "",
      "english_name": "",
      "category": "",
      "visual_description": [],
      "serving_style": [],
      "must_show": [],
      "must_not_replace_with": []
    }}
  ]
}}
"""

    def fallback(self, request: AdCopyRequest, copy: AdCopyResponse) -> ProductVisualization:
        products: list[ProductVisual] = []
        for product_name in request.product_names:
            english_name = _simple_english_name(product_name)
            products.append(
                ProductVisual(
                    original_name=product_name,
                    english_name=english_name,
                    category="Product",
                    visual_description=[
                        product_name,
                    ],
                    serving_style=[
                        "main product only",
                    ],
                    must_show=[
                        product_name,
                    ],
                    must_not_replace_with=[
                        "different product",
                        "extra birthday candles",
                        "new toppings not shown in the reference image",
                    ],
                )
            )
        return ProductVisualization(products=products)

    def _payload(
        self,
        request: AdCopyRequest,
        copy: AdCopyResponse,
        model_name: str,
        provider: TextRuntimeProvider,
        reference_profiles: list[ProductVisual] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You convert product names into concrete visual descriptions. "
                        "Return valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": self.build_prompt(request, copy, reference_profiles),
                },
            ],
            "temperature": 0.2,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ProductVisualization",
                    "schema": ProductVisualization.model_json_schema(),
                    "strict": True,
                },
            },
        }
<<<<<<< HEAD
        token_limit_name = (
            "max_completion_tokens"
            if provider == TextRuntimeProvider.OPENAI
            else "max_tokens"
        )
        payload[token_limit_name] = 1200
=======
        token_limit_key = (
            "max_completion_tokens"
            if model_name.startswith("gpt-5")
            else "max_tokens"
        )
        payload[token_limit_key] = 1200
>>>>>>> origin/dev
        return payload

    def _parse(self, content: str) -> ProductVisualization:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```")
            cleaned = cleaned.removesuffix("```").strip()
        data, _ = json.JSONDecoder().raw_decode(cleaned)
        return ProductVisualization.model_validate(data)

    async def _load_reference_profiles(
        self,
        request: AdCopyRequest,
        copy: AdCopyResponse,
    ) -> list[ProductVisual]:
        if not settings.reference_search_enabled:
            return []

        from app.extensions.ad_content.reference_analyzer import ReferenceVisualAnalyzer
        from app.extensions.ad_content.reference_search import search_reference_images
        from app.extensions.ad_content.reference_store import ProductVisualProfileStore

        store = ProductVisualProfileStore()
        cached = store.get_many(request.product_names)
        profiles: dict[str, ProductVisual] = dict(cached)
        analyzer = ReferenceVisualAnalyzer()

        for product_name in request.product_names:
            if product_name in profiles:
                continue
            query, references = await search_reference_images(
                product_name,
                request.business_type.value,
            )
            product = await analyzer.analyze(request, copy, product_name, references)
            if product is None:
                continue
            sources = [
                reference.model_dump(mode="json")
                for reference in references
                if reference.page_url or reference.image_url
            ]
            store.upsert(product, reference_query=query, reference_sources=sources)
            profiles[product_name] = product

        return [
            profiles[product_name]
            for product_name in request.product_names
            if product_name in profiles
        ]

    async def visualize(self, request: AdCopyRequest, copy: AdCopyResponse) -> ProductVisualization:
        return self.fallback(request, copy)

        reference_profiles = await self._load_reference_profiles(request, copy)
        if len(reference_profiles) == len(request.product_names):
            return ProductVisualization(products=reference_profiles)

        try:
            config = get_text_model_config(request.model.value)
            base_url = resolve_base_url(config)
            model_name = resolve_model_name(config)
            api_key = resolve_api_key(config)
            provider = infer_provider(base_url, config.provider)
            if provider == TextRuntimeProvider.HUGGING_FACE_ROUTER and not api_key:
                return self.fallback(request, copy)

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=self._payload(
                        request,
                        copy,
                        model_name,
                        provider,
                        reference_profiles,
                    ),
                )
                if response.status_code in {400, 422}:
                    payload = self._payload(
                        request,
                        copy,
                        model_name,
                        provider,
                        reference_profiles,
                    )
                    payload.pop("response_format", None)
                    response = await client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                visualization = self._parse(content)
        except (KeyError, httpx.HTTPError, ValidationError, json.JSONDecodeError, TypeError, IndexError):
            return self.fallback(request, copy)

        original_names = {product.original_name for product in visualization.products}
        if any(product_name not in original_names for product_name in request.product_names):
            return self.fallback(request, copy)
        return visualization


async def visualize_products(
    request: AdCopyRequest,
    copy: AdCopyResponse,
) -> ProductVisualization:
    return await ProductVisualizer().visualize(request, copy)


def _simple_english_name(product_name: str) -> str:
    normalized = product_name.replace(" ", "").lower()
    if "초코" in normalized and ("케이크" in normalized or "케익" in normalized):
        return "Chocolate Cake"
    if "케이크" in normalized or "케익" in normalized:
        return "Cake"
    if "티라미수" in normalized:
        return "Tiramisu"
    if "라떼" in normalized:
        return "Latte"
    if "에이드" in normalized:
        return "Ade"
    return product_name
