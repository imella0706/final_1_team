import json
from typing import Any

import httpx

from app.core.config import settings
from app.extensions.ad_content.product_visualizer import ProductVisual, ProductVisualization
from app.extensions.ad_content.reference_search import ReferenceImageResult
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    infer_provider,
    resolve_api_key,
    resolve_base_url,
    resolve_model_name,
)
from app.modules.model_runtime.schemas import TextRuntimeProvider


class ReferenceVisualAnalyzer:
    def build_prompt(
        self,
        request: AdCopyRequest,
        copy: AdCopyResponse,
        product_name: str,
        references: list[ReferenceImageResult],
    ) -> str:
        reference_payload = [reference.model_dump() for reference in references]
        return f"""You are a reference-image visual analyzer for advertising image generation.

You do not copy source images.
You extract only general visual characteristics useful for generating a new original advertisement image.
Do not include brand names, logos, watermarks, photographer names, or copyrighted composition details.

Return JSON only.

Product to analyze:
{product_name}

Business type:
{request.business_type.value}

User features:
{json.dumps(request.features, ensure_ascii=False)}

Visual brief:
{json.dumps(copy.visual_brief.model_dump(mode="json"), ensure_ascii=False)}

Licensed/reference image metadata:
{json.dumps(reference_payload, ensure_ascii=False)}

Create one product visual profile for the product.
Use the reference metadata only as evidence for visible traits.
If metadata is incomplete, infer probable visible traits from the product name and user features.

Output:
{{
  "products": [
    {{
      "original_name": "{product_name}",
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

    def _payload(
        self,
        request: AdCopyRequest,
        copy: AdCopyResponse,
        product_name: str,
        references: list[ReferenceImageResult],
        model_name: str,
        provider: TextRuntimeProvider,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract general product visual traits from licensed reference "
                        "metadata. Return valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": self.build_prompt(request, copy, product_name, references),
                },
            ],
            "temperature": 0.1,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ProductVisualization",
                    "schema": ProductVisualization.model_json_schema(),
                    "strict": True,
                },
            },
        }
        token_limit_key = (
            "max_completion_tokens"
            if provider == TextRuntimeProvider.OPENAI and model_name.startswith("gpt-5")
            else "max_tokens"
        )
        payload[token_limit_key] = 900
        return payload

    def _parse_product(self, product_name: str, content: str) -> ProductVisual | None:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```")
            cleaned = cleaned.removesuffix("```").strip()
        data, _ = json.JSONDecoder().raw_decode(cleaned)
        visualization = ProductVisualization.model_validate(data)
        for product in visualization.products:
            if product.original_name == product_name:
                return product
        return None

    async def analyze(
        self,
        request: AdCopyRequest,
        copy: AdCopyResponse,
        product_name: str,
        references: list[ReferenceImageResult],
    ) -> ProductVisual | None:
        if not references:
            return None
        try:
            config = get_text_model_config(request.model.value)
            base_url = resolve_base_url(config)
            model_name = resolve_model_name(config)
            api_key = resolve_api_key(config)
            provider = infer_provider(base_url, config.provider)
            if provider == TextRuntimeProvider.HUGGING_FACE_ROUTER and not api_key:
                return None

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            endpoint = f"{base_url.rstrip('/')}/chat/completions"
            payload = self._payload(
                request,
                copy,
                product_name,
                references,
                model_name,
                provider,
            )
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                if response.status_code in {400, 422}:
                    payload.pop("response_format", None)
                    response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return self._parse_product(product_name, content)
        except (KeyError, httpx.HTTPError, json.JSONDecodeError, TypeError, IndexError, ValueError):
            return None
