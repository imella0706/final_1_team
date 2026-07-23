"""네이버 음식 광고용 배경 프롬프트를 업종별로 고정한다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NaverBackgroundPrompt:
    """배경 생성기에 전달할 업종별 프롬프트와 정규화된 업종 정보."""

    business_type: str
    template: str
    prompt: str


_PUB_PROMPT = """Photorealistic modern Korean pub interior,
a clean dark wooden table in the foreground,
warm ambient lighting from hanging pendant lamps,
subtle orange and amber color temperature,
soft directional light coming from the upper left,
cozy evening atmosphere,
slightly blurred bar shelves and warm interior lights in the background,
realistic wood texture,
shallow depth of field,
eye-level commercial food photography composition,
empty table surface,
enough clear space in the center for placing a food dish,
no food, no plate, no bowl, no cup, no glass,
no bottle, no alcohol, no utensils, no menu,
no people, no hands, no text, no logo, no watermark,
realistic restaurant photography,
commercial food advertisement background"""

_RESTAURANT_PROMPT = """Photorealistic modern Korean restaurant interior,
a clean natural wooden table in the foreground,
soft natural daylight coming from the left,
warm neutral color temperature,
bright and welcoming dining atmosphere,
subtle modern Korean interior design,
slightly blurred dining area in the background,
realistic table and interior textures,
shallow depth of field,
eye-level commercial food photography composition,
empty table surface,
enough clear space in the center for placing a food dish,
no food, no plate, no bowl, no cup,
no utensils, no napkin, no menu,
no people, no hands, no text, no logo, no watermark,
realistic restaurant photography,
commercial food advertisement background"""

_CAFE_PROMPT = """Photorealistic premium modern Korean cafe interior,
minimal Scandinavian-inspired cafe design,
clean walnut wooden table occupying the lower foreground,
smooth natural wood grain with realistic texture,
soft natural morning sunlight entering from large windows on the left,
warm neutral white color temperature (4500K–5000K),
soft directional lighting with gentle natural shadows,
bright and cozy atmosphere,
modern wooden chairs and tables subtly blurred in the background,
large floor-to-ceiling windows,
small indoor green plants,
minimal warm pendant lights,
clean white walls with light oak accents,
high-end commercial cafe interior,
eye-level camera angle,
50mm DSLR lens,
shallow depth of field,
cinematic bokeh background,
realistic perspective,
empty table surface,
large clear space in the center for placing a food dish,
no food, no plate, no bowl, no cup, no glass,
no utensils, no napkin, no menu, no laptop, no phone,
no decorations on the table, no people, no hands, no text, no logo, no watermark,
ultra photorealistic,
commercial food photography background,
high-end restaurant advertising photography"""

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
