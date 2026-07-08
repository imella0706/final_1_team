from typing import Any


BUSINESS_TYPE_MAP = {
    "카페": "cafe",
    "베이커리": "bakery",
    "디저트": "dessert",
    "음식점": "restaurant",
    "주점": "pub",
}

SITUATION_MAP = {
    "신메뉴": "new_menu",
    "할인": "discount",
    "세트메뉴 할인": "discount",
    "세트 메뉴 할인": "discount",
    "이벤트": "event",
    "배달": "delivery",
    "포장": "takeout",
    "방문 유도": "visit",
}

AGE_GROUP_MAP = {
    "10대": "teens",
    "20대": "twenties",
    "30대": "thirties",
    "40대": "forties",
    "50대 이상": "fifties_plus",
}

TARGET_MAP = {
    "직장인": "office_workers",
    "가족": "families",
    "가족 고객": "families",
    "커플": "couples",
    "커플 고객": "couples",
    "혼자": "solo",
    "혼자 방문": "solo",
    "1인 고객": "solo",
}

TONE_MAP = {
    "감성적": "emotional",
    "감성적인": "emotional",
    "재치있는": "witty",
    "재치 있는": "witty",
    "친근한": "friendly",
    "따뜻한": "warm",
    "발랄한": "playful",
    "전문적인": "professional",
    "고급스러운": "premium",
}

CHANNEL_MAP = {
    "인스타그램": "instagram",
    "네이버 블로그": "naver_blog",
    "배달앱": "delivery_app",
    "배달 앱": "delivery_app",
    "매장 포스터": "store_poster",
}


def clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.replace("\n", ",").split(",")
    else:
        candidates = value
    return [str(item).strip() for item in candidates if str(item).strip()]


def normalize_scalar(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return mapping.get(stripped, stripped)
    return value


def normalize_target_audiences(value: Any) -> list[str]:
    return [TARGET_MAP.get(item, item) for item in clean_string_list(value)]


def normalize_age_groups(value: Any) -> list[str]:
    return [AGE_GROUP_MAP.get(item, item) for item in clean_string_list(value)]


def normalize_ad_copy_input(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    normalized["business_name"] = str(normalized.get("business_name", "")).strip()
    normalized["business_type"] = normalize_scalar(
        normalized.get("business_type"), BUSINESS_TYPE_MAP
    )
    normalized["situation"] = normalize_scalar(normalized.get("situation"), SITUATION_MAP)
    raw_targets = clean_string_list(normalized.get("target_audiences"))
    age_groups = clean_string_list(normalized.get("age_groups"))
    age_groups.extend(item for item in raw_targets if item in AGE_GROUP_MAP or item in AGE_GROUP_MAP.values())
    target_audiences = [
        item for item in raw_targets if item not in AGE_GROUP_MAP and item not in AGE_GROUP_MAP.values()
    ]
    normalized["age_groups"] = normalize_age_groups(age_groups)
    normalized["target_audiences"] = normalize_target_audiences(target_audiences)
    normalized["tone"] = normalize_scalar(normalized.get("tone"), TONE_MAP)
    normalized["channel"] = normalize_scalar(normalized.get("channel"), CHANNEL_MAP)
    normalized["product_names"] = clean_string_list(normalized.get("product_names"))
    normalized["features"] = clean_string_list(normalized.get("features"))
    normalized["required_terms"] = clean_string_list(normalized.get("required_terms"))
    normalized["prohibited_terms"] = clean_string_list(normalized.get("prohibited_terms"))
    if not normalized.get("promotion"):
        normalized["promotion"] = None
    return normalized
