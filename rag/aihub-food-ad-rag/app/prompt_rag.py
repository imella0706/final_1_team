from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

BUSINESS_CATEGORY_KO = {
    "cafe": "카페",
    "bakery": "베이커리",
    "dessert": "디저트",
    "restaurant": "음식점",
    "pub": "주점",
}


PRODUCT_GROUP_KO = {
    "coffee": "커피",
    "tea": "차/티",
    "ade_juice": "에이드/주스",
    "smoothie": "스무디",
    "brunch": "브런치",
    "bread": "빵",
    "pastry": "페이스트리",
    "bagel": "베이글",
    "sandwich": "샌드위치",
    "cake": "케이크",
    "cookie_macaron": "쿠키/마카롱",
    "ice_cream": "아이스크림",
    "shaved_ice": "빙수",
    "korean_food": "한식",
    "chinese_food": "중식",
    "japanese_food": "일식",
    "western_food": "양식",
    "meat_grill": "고기/구이",
    "chicken": "치킨",
    "pizza": "피자",
    "delivery_food": "배달음식",
    "alcohol": "주류",
    "fried_side": "튀김안주",
    "grilled_side": "구이안주",
    "seafood_side": "해산물안주",
    "korean_pub_food": "한식안주",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_retrieval_query(
    business_category: Optional[str] = None,
    product_group: Optional[str] = None,
    product_name: Optional[str] = None,
    situation: Optional[str] = None,
    tone: Optional[str] = None,
    channel: Optional[str] = None,
) -> str:
    """
    사용자 입력을 검색용 query로 변환한다.
    """
    parts = []

    if business_category:
        parts.append(BUSINESS_CATEGORY_KO.get(business_category, business_category))

    if product_group:
        parts.append(PRODUCT_GROUP_KO.get(product_group, product_group))

    if product_name:
        parts.append(product_name)

    if situation:
        parts.append(situation)

    if tone:
        parts.append(tone)

    if channel:
        parts.append(channel)

    return " ".join([part for part in parts if normalize_text(part)])


def retrieve_references(
    api_base_url: str,
    business_category: Optional[str] = None,
    product_group: Optional[str] = None,
    product_name: Optional[str] = None,
    situation: Optional[str] = None,
    tone: Optional[str] = None,
    channel: Optional[str] = None,
    top_k: int = 5,
    timeout: int = 30,
) -> List[Dict[str, Any]]:
    """
    retrieval_api.py의 /search를 호출해서 참고 이미지/메타데이터를 가져온다.
    """
    query = build_retrieval_query(
        business_category=business_category,
        product_group=product_group,
        product_name=product_name,
        situation=situation,
        tone=tone,
        channel=channel,
    )

    payload = {
        "query": query,
        "business_category": business_category,
        "product_group": product_group,
        "product_name": product_name,
        "top_k": top_k,
    }

    url = api_base_url.rstrip("/") + "/search"

    response = requests.post(
        url,
        json=payload,
        timeout=timeout,
    )

    response.raise_for_status()

    data = response.json()
    return data.get("results", [])


def format_reference_for_prompt(item: Dict[str, Any], index: int) -> str:
    """
    검색 결과 1개를 프롬프트에 넣기 좋은 텍스트로 변환한다.
    """
    business_category = normalize_text(item.get("business_category"))
    product_group = normalize_text(item.get("product_group"))
    original_food_name = normalize_text(item.get("original_food_name"))
    product_name = normalize_text(item.get("product_name"))
    caption = normalize_text(item.get("caption"))
    prompt_keywords = normalize_text(item.get("prompt_keywords"))
    image_path = normalize_text(item.get("final_image_path") or item.get("image_path"))

    business_ko = BUSINESS_CATEGORY_KO.get(business_category, business_category)
    group_ko = PRODUCT_GROUP_KO.get(product_group, product_group)

    lines = [
        f"[Reference {index}]",
        f"- 업종: {business_ko}",
        f"- 상품군: {group_ko}",
        f"- 유사 메뉴명: {product_name or original_food_name}",
    ]

    if caption:
        lines.append(f"- 이미지 설명: {caption}")

    if prompt_keywords:
        lines.append(f"- 시각 키워드: {prompt_keywords}")

    if image_path:
        lines.append(f"- 참고 이미지 경로: {image_path}")

    return "\n".join(lines)


def build_reference_context(results: List[Dict[str, Any]]) -> str:
    """
    여러 검색 결과를 LLM 프롬프트에 넣을 context block으로 변환한다.
    """
    if not results:
        return "참고 검색 결과 없음"

    blocks = []

    for idx, item in enumerate(results, start=1):
        blocks.append(format_reference_for_prompt(item, idx))

    return "\n\n".join(blocks)


def build_ad_copy_prompt(
    business_name: str,
    business_category: str,
    product_name: str,
    situation: str,
    target_audiences: List[str],
    tone: str,
    channel: str,
    features: List[str],
    prohibited_terms: Optional[List[str]] = None,
    reference_results: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    광고 문구 생성용 프롬프트.
    LLM에 넘길 수 있는 형태로 반환한다.
    """
    prohibited_terms = prohibited_terms or []
    reference_results = reference_results or []

    reference_context = build_reference_context(reference_results)

    prompt = f"""
당신은 소상공인 광고 콘텐츠를 만드는 한국어 마케팅 카피라이터입니다.

[사용자 입력]
- 상호명: {business_name}
- 업종: {BUSINESS_CATEGORY_KO.get(business_category, business_category)}
- 상품명: {product_name}
- 광고 상황: {situation}
- 타겟 고객: {", ".join(target_audiences)}
- 톤앤매너: {tone}
- 채널: {channel}
- 강조 특징: {", ".join(features)}
- 금지 표현: {", ".join(prohibited_terms) if prohibited_terms else "없음"}

[검색 기반 참고자료]
{reference_context}

[작성 규칙]
1. 한국어로 작성한다.
2. 금지 표현은 절대 사용하지 않는다.
3. 강조 특징은 반드시 반영한다.
4. 실제 음식/상품명과 다른 메뉴를 만들어내지 않는다.
5. 출력은 headlines, body_copies, cta, hashtags 구조로 작성한다.
6. 인스타그램/블로그/배달앱/포스터 등 채널에 맞는 길이와 톤으로 작성한다.

[출력 형식]
headlines:
- ...
- ...

body_copies:
- ...
- ...

cta:
- ...

hashtags:
- ...
""".strip()

    return prompt


def build_image_prompt(
    business_category: str,
    product_name: str,
    tone: str,
    channel: str,
    reference_results: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    이미지 생성 모델에 넘길 수 있는 visual prompt 초안.
    """
    reference_results = reference_results or []
    reference_context = build_reference_context(reference_results)

    prompt = f"""
Create a realistic commercial food advertising image.

[Main Product]
{product_name}

[Business Category]
{business_category}

[Tone]
{tone}

[Channel]
{channel}

[Visual References]
{reference_context}

[Requirements]
- The image must clearly show the main product: {product_name}
- Realistic commercial food photography
- Clean composition
- Natural appetizing lighting
- No text, no logo, no watermark
- Do not show a different food item
""".strip()

    return prompt


def build_rag_bundle(
    api_base_url: str,
    business_name: str,
    business_category: str,
    product_group: Optional[str],
    product_name: str,
    situation: str,
    target_audiences: List[str],
    tone: str,
    channel: str,
    features: List[str],
    prohibited_terms: Optional[List[str]] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    최종적으로 광고 생성 파이프라인에서 사용할 RAG 묶음 생성.

    반환:
    - retrieval_results
    - reference_context
    - ad_copy_prompt
    - image_prompt
    """
    retrieval_results = retrieve_references(
        api_base_url=api_base_url,
        business_category=business_category,
        product_group=product_group,
        product_name=product_name,
        situation=situation,
        tone=tone,
        channel=channel,
        top_k=top_k,
    )

    reference_context = build_reference_context(retrieval_results)

    ad_copy_prompt = build_ad_copy_prompt(
        business_name=business_name,
        business_category=business_category,
        product_name=product_name,
        situation=situation,
        target_audiences=target_audiences,
        tone=tone,
        channel=channel,
        features=features,
        prohibited_terms=prohibited_terms,
        reference_results=retrieval_results,
    )

    image_prompt = build_image_prompt(
        business_category=business_category,
        product_name=product_name,
        tone=tone,
        channel=channel,
        reference_results=retrieval_results,
    )

    return {
        "retrieval_results": retrieval_results,
        "reference_context": reference_context,
        "ad_copy_prompt": ad_copy_prompt,
        "image_prompt": image_prompt,
    }


if __name__ == "__main__":
    # 간단한 로컬 테스트용
    bundle = build_rag_bundle(
        api_base_url="http://127.0.0.1:7860",
        business_name="오후의 조각",
        business_category="dessert",
        product_group="cake",
        product_name="수제 딸기 티라미수",
        situation="new_menu",
        target_audiences=["20대", "직장인"],
        tone="감성적",
        channel="instagram",
        features=[
            "매일 아침 직접 만드는 디저트",
            "평일 오전 11시부터 오후 2시까지 런치 세트 운영",
        ],
        prohibited_terms=["최고", "무조건", "인생 맛집"],
        top_k=5,
    )

    print("=== Reference Context ===")
    print(bundle["reference_context"])
    print("\n=== Ad Copy Prompt ===")
    print(bundle["ad_copy_prompt"])
    print("\n=== Image Prompt ===")
    print(bundle["image_prompt"])
