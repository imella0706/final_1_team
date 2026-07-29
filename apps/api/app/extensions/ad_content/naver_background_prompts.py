"""네이버 음식 광고용 배경 프롬프트를 업종별로 고정한다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NaverBackgroundPrompt:
    """배경 생성기에 전달할 업종별 프롬프트와 정규화된 업종 정보."""

    business_type: str
    template: str
    prompt: str


_PUB_PROMPT = """Photorealistic modern Korean pub atmosphere,
dark walnut and deep brown material palette,
warm amber and subtle orange ambient light,
cozy evening mood,
realistic wood and softly reflective material textures,
refined modern Korean pub styling,
commercial food advertising atmosphere"""

_RESTAURANT_PROMPT = """Photorealistic modern Korean restaurant atmosphere,
natural oak and warm neutral material palette,
soft natural daylight and gentle warm neutral color balance,
bright and welcoming dining mood,
subtle modern Korean interior styling,
realistic table and interior material textures,
commercial food advertising atmosphere"""

_CAFE_PROMPT = """Photorealistic premium modern Korean cafe atmosphere,
minimal Scandinavian-inspired cafe design,
walnut wood and light oak material palette,
warm neutral white color balance (4500K–5000K),
soft natural morning daylight,
bright cozy premium mood,
clean white walls, light oak accents and subtle green styling,
realistic high-end commercial cafe material textures,
ultra photorealistic commercial food advertising atmosphere"""

_NORMALIZED_TYPES = {
    "카페": "cafe",
    "cafe": "cafe",
    "베이커리": "bakery",
    "bakery": "bakery",
    "디저트": "dessert",
    "dessert": "dessert",
    "음식점": "restaurant",
    "restaurant": "restaurant",
    "주점": "pub",
    "pub": "pub",
}


def build_naver_background_prompt(business_type: object) -> NaverBackgroundPrompt:
    """JSON 업종값을 pub/restaurant/cafe 계열의 안전한 빈 배경 프롬프트로 변환한다."""
    normalized = _NORMALIZED_TYPES.get(str(business_type).strip().lower(), "restaurant")
    if normalized == "pub":
        return NaverBackgroundPrompt(normalized, "pub", _PUB_PROMPT)
    if normalized == "restaurant":
        return NaverBackgroundPrompt(normalized, "restaurant", _RESTAURANT_PROMPT)
    # 카페·베이커리·디저트는 사용자가 지정한 동일한 카페형 광고 배경을 사용한다.
    return NaverBackgroundPrompt(normalized, "cafe", _CAFE_PROMPT)
