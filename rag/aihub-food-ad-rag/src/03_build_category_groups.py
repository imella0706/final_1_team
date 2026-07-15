from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"YAML file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_keyword_rules(category_config: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    configs/category_map.yaml의 service_category_schema를
    검색하기 쉬운 keyword rule 리스트로 변환한다.
    """
    rules: List[Dict[str, str]] = []

    service_schema = category_config.get("service_category_schema", {})
    business_categories = service_schema.get("business_categories", {})

    for business_category, business_info in business_categories.items():
        product_groups = business_info.get("product_groups", {})

        for product_group, product_info in product_groups.items():
            keywords = product_info.get("keywords", [])

            for keyword in keywords:
                keyword_text = normalize_text(keyword)

                if not keyword_text:
                    continue

                rules.append(
                    {
                        "business_category": business_category,
                        "product_group": product_group,
                        "keyword": keyword_text,
                    }
                )

    # 긴 키워드를 먼저 매칭한다.
    # 예: "감자튀김"을 "튀김"보다 먼저 매칭
    rules = sorted(rules, key=lambda x: len(x["keyword"]), reverse=True)

    return rules


def infer_category_by_keyword(
    product_name: str,
    original_food_name: str,
    food_code: str,
    rules: List[Dict[str, str]],
) -> Tuple[str, str, str, str]:
    """
    음식명 기반으로 business_category와 product_group을 추론한다.

    반환:
    business_category, product_group, matched_keyword, mapping_status
    """
    search_text = " ".join(
        [
            normalize_text(product_name),
            normalize_text(original_food_name),
            normalize_text(food_code),
        ]
    )

    for rule in rules:
        keyword = rule["keyword"]

        if keyword and keyword in search_text:
            return (
                rule["business_category"],
                rule["product_group"],
                keyword,
                "matched_by_keyword",
            )

    return ("", "", "", "unmapped")


def apply_manual_overrides(
    row: pd.Series,
    business_category: str,
    product_group: str,
    matched_keyword: str,
    mapping_status: str,
) -> Tuple[str, str, str, str]:
    """
    키워드 규칙만으로 애매한 음식들을 보정한다.

    목적:
    - fallback_default 비율을 낮춘다.
    - AI Hub 음식명 기반으로 cafe/bakery/dessert/restaurant/pub 분류를 보강한다.
    - product_group은 현재 프로젝트에서 정의한 그룹 안에서만 사용한다.
    """
    food_name = normalize_text(row.get("original_food_name", ""))
    food_code = normalize_text(row.get("food_code", ""))

    # ------------------------------------------------------------
    # 1. 주점/안주류
    # ------------------------------------------------------------
    pub_seafood_keywords = [
        "회",
        "광어회",
        "우럭회",
        "연어회",
        "참치회",
        "방어회",
        "개불",
        "멍게",
        "해삼",
        "산낙지",
        "낙지",
        "문어",
        "오징어",
        "새우",
        "조개",
        "홍합",
        "골뱅이",
        "꼬막",
        "전복",
        "소라",
    ]

    if any(keyword in food_name for keyword in pub_seafood_keywords):
        # 해물탕/해물찜/해장국처럼 식사형 메뉴는 음식점으로 둔다.
        if not any(
            x in food_name
            for x in ["탕", "찜", "찌개", "국", "밥", "면", "덮밥", "볶음밥"]
        ):
            return (
                "pub",
                "seafood_side",
                "manual_pub_seafood",
                "matched_by_manual_rule",
            )

    pub_fried_keywords = [
        "감자튀김",
        "튀김",
        "새우튀김",
        "오징어튀김",
        "고로케",
        "치킨너겟",
        "치즈스틱",
        "가라아케",
        "카라아게",
        "닭강정",
    ]

    if any(keyword in food_name for keyword in pub_fried_keywords):
        return ("pub", "fried_side", "manual_pub_fried", "matched_by_manual_rule")

    pub_grilled_keywords = [
        "꼬치",
        "닭꼬치",
        "구이안주",
        "오징어구이",
        "쥐포",
        "먹태",
        "노가리",
        "소시지",
        "소세지",
        "버터구이",
    ]

    if any(keyword in food_name for keyword in pub_grilled_keywords):
        return ("pub", "grilled_side", "manual_pub_grilled", "matched_by_manual_rule")

    pub_korean_keywords = [
        "두부김치",
        "부대찌개",
        "골뱅이무침",
        "파전",
        "김치전",
        "해물파전",
        "육회",
        "어묵탕",
        "오뎅탕",
        "번데기탕",
    ]

    if any(keyword in food_name for keyword in pub_korean_keywords):
        return ("pub", "korean_pub_food", "manual_pub_korean", "matched_by_manual_rule")

    # ------------------------------------------------------------
    # 2. 카페/음료
    # ------------------------------------------------------------
    cafe_coffee_keywords = [
        "아메리카노",
        "카페라떼",
        "카페 라떼",
        "라떼",
        "카푸치노",
        "에스프레소",
        "마끼아또",
        "마키아토",
        "모카",
        "커피",
        "콜드브루",
        "더치커피",
    ]

    if any(keyword in food_name for keyword in cafe_coffee_keywords):
        return ("cafe", "coffee", "manual_cafe_coffee", "matched_by_manual_rule")

    cafe_tea_keywords = [
        "녹차",
        "홍차",
        "밀크티",
        "허브티",
        "아이스티",
        "티라떼",
        "유자차",
        "레몬차",
        "자몽차",
        "생강차",
        "차",
    ]

    if any(keyword in food_name for keyword in cafe_tea_keywords):
        return ("cafe", "tea", "manual_cafe_tea", "matched_by_manual_rule")

    cafe_ade_juice_keywords = [
        "에이드",
        "주스",
        "쥬스",
        "착즙",
        "레몬에이드",
        "자몽에이드",
        "청포도에이드",
        "오렌지주스",
        "딸기주스",
        "망고주스",
    ]

    if any(keyword in food_name for keyword in cafe_ade_juice_keywords):
        return ("cafe", "ade_juice", "manual_cafe_ade_juice", "matched_by_manual_rule")

    cafe_smoothie_keywords = [
        "스무디",
        "쉐이크",
        "셰이크",
        "프라페",
        "블렌디드",
    ]

    if any(keyword in food_name for keyword in cafe_smoothie_keywords):
        return ("cafe", "smoothie", "manual_cafe_smoothie", "matched_by_manual_rule")

    brunch_keywords = [
        "브런치",
        "팬케이크",
        "프렌치토스트",
        "에그베네딕트",
        "오믈렛",
        "스크램블",
        "샐러드",
        "샌드위치",
    ]

    if any(keyword in food_name for keyword in brunch_keywords):
        return ("cafe", "brunch", "manual_cafe_brunch", "matched_by_manual_rule")

    # ------------------------------------------------------------
    # 3. 베이커리
    # ------------------------------------------------------------
    bakery_bread_keywords = [
        "빵",
        "식빵",
        "소금빵",
        "바게트",
        "단팥빵",
        "크림빵",
        "모닝빵",
        "치아바타",
        "깜빠뉴",
        "호밀빵",
        "마늘빵",
    ]

    if any(keyword in food_name for keyword in bakery_bread_keywords):
        return ("bakery", "bread", "manual_bakery_bread", "matched_by_manual_rule")

    bakery_pastry_keywords = [
        "크루아상",
        "크로와상",
        "데니시",
        "파이",
        "페이스트리",
        "애플파이",
        "타르트",
    ]

    if any(keyword in food_name for keyword in bakery_pastry_keywords):
        return ("bakery", "pastry", "manual_bakery_pastry", "matched_by_manual_rule")

    bakery_bagel_keywords = [
        "베이글",
    ]

    if any(keyword in food_name for keyword in bakery_bagel_keywords):
        return ("bakery", "bagel", "manual_bakery_bagel", "matched_by_manual_rule")

    bakery_sandwich_keywords = [
        "샌드위치",
        "토스트",
        "햄치즈",
        "에그샌드",
    ]

    if any(keyword in food_name for keyword in bakery_sandwich_keywords):
        return (
            "bakery",
            "sandwich",
            "manual_bakery_sandwich",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 4. 디저트
    # ------------------------------------------------------------
    dessert_cake_keywords = [
        "케이크",
        "티라미수",
        "치즈케이크",
        "딸기케이크",
        "초코케이크",
        "롤케이크",
        "파운드케이크",
        "타르트",
        "브라우니",
    ]

    if any(keyword in food_name for keyword in dessert_cake_keywords):
        return ("dessert", "cake", "manual_dessert_cake", "matched_by_manual_rule")

    dessert_cookie_keywords = [
        "쿠키",
        "마카롱",
        "다쿠아즈",
        "휘낭시에",
        "스콘",
        "머핀",
    ]

    if any(keyword in food_name for keyword in dessert_cookie_keywords):
        return (
            "dessert",
            "cookie_macaron",
            "manual_dessert_cookie",
            "matched_by_manual_rule",
        )

    dessert_icecream_keywords = [
        "아이스크림",
        "젤라토",
        "소프트아이스크림",
        "샤베트",
    ]

    if any(keyword in food_name for keyword in dessert_icecream_keywords):
        return (
            "dessert",
            "ice_cream",
            "manual_dessert_icecream",
            "matched_by_manual_rule",
        )

    dessert_bingsu_keywords = [
        "빙수",
        "팥빙수",
        "망고빙수",
        "과일빙수",
    ]

    if any(keyword in food_name for keyword in dessert_bingsu_keywords):
        return (
            "dessert",
            "shaved_ice",
            "manual_dessert_bingsu",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 5. 음식점 - 한식
    # ------------------------------------------------------------
    korean_food_keywords = [
        "가자미구이",
        "고등어구이",
        "갈치구이",
        "조기구이",
        "생선구이",
        "김치찌개",
        "된장찌개",
        "순두부찌개",
        "부대찌개",
        "청국장",
        "비빔밥",
        "돌솥비빔밥",
        "불고기",
        "제육",
        "제육볶음",
        "국밥",
        "순대국",
        "설렁탕",
        "곰탕",
        "갈비탕",
        "삼계탕",
        "냉면",
        "물냉면",
        "비빔냉면",
        "칼국수",
        "수제비",
        "떡볶이",
        "김밥",
        "라면",
        "죽",
        "전골",
        "찜",
        "탕",
        "국",
        "찌개",
        "볶음",
        "나물",
        "잡채",
        "전",
        "전병",
        "족발",
        "보쌈",
        "순대",
        "만두국",
        "떡국",
    ]

    if any(keyword in food_name for keyword in korean_food_keywords):
        return (
            "restaurant",
            "korean_food",
            "manual_restaurant_korean",
            "matched_by_manual_rule",
        )

    meat_grill_keywords = [
        "삼겹살",
        "목살",
        "갈비",
        "돼지갈비",
        "소갈비",
        "양갈비",
        "불고기",
        "닭갈비",
        "곱창",
        "막창",
        "대창",
        "스테이크",
        "고기구이",
        "구이",
    ]

    if any(keyword in food_name for keyword in meat_grill_keywords):
        return (
            "restaurant",
            "meat_grill",
            "manual_restaurant_meat_grill",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 6. 음식점 - 중식
    # ------------------------------------------------------------
    chinese_keywords = [
        "짜장",
        "짜장면",
        "자장면",
        "짬뽕",
        "탕수육",
        "마라탕",
        "마라샹궈",
        "양장피",
        "깐풍기",
        "유린기",
        "깐쇼새우",
        "멘보샤",
        "고추잡채",
        "팔보채",
        "마파두부",
        "볶음밥",
        "중화",
        "춘권",
        "딤섬",
        "샤오롱바오",
        "가지튀김",
        "가지만두",
        "군만두",
        "물만두",
    ]

    if any(keyword in food_name for keyword in chinese_keywords):
        return (
            "restaurant",
            "chinese_food",
            "manual_restaurant_chinese",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 7. 음식점 - 일식
    # ------------------------------------------------------------
    japanese_keywords = [
        "초밥",
        "스시",
        "라멘",
        "라면",
        "우동",
        "소바",
        "돈카츠",
        "돈까스",
        "가츠동",
        "규동",
        "텐동",
        "덮밥",
        "오니기리",
        "타코야끼",
        "오코노미야끼",
        "야키소바",
        "가라아케",
        "카라아게",
        "사시미",
        "나베",
    ]

    if any(keyword in food_name for keyword in japanese_keywords):
        return (
            "restaurant",
            "japanese_food",
            "manual_restaurant_japanese",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 8. 음식점 - 양식
    # ------------------------------------------------------------
    western_keywords = [
        "파스타",
        "스파게티",
        "리조또",
        "스테이크",
        "햄버거",
        "버거",
        "샐러드",
        "그라탕",
        "라자냐",
        "오믈렛",
        "필라프",
        "피쉬앤칩스",
        "바비큐",
        "바베큐",
        "BBQ",
    ]

    if any(keyword in food_name for keyword in western_keywords):
        return (
            "restaurant",
            "western_food",
            "manual_restaurant_western",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 9. 음식점 - 치킨/피자
    # ------------------------------------------------------------
    chicken_keywords = [
        "치킨",
        "후라이드",
        "프라이드",
        "양념치킨",
        "간장치킨",
        "닭강정",
        "닭튀김",
    ]

    if any(keyword in food_name for keyword in chicken_keywords):
        return (
            "restaurant",
            "chicken",
            "manual_restaurant_chicken",
            "matched_by_manual_rule",
        )

    pizza_keywords = [
        "피자",
        "페퍼로니",
        "고르곤졸라",
    ]

    if any(keyword in food_name for keyword in pizza_keywords):
        return (
            "restaurant",
            "pizza",
            "manual_restaurant_pizza",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 10. 음식점 - 동남아/기타 외식 메뉴
    # 현재 product_group에 동남아/인도/기타가 없으므로 delivery_food로 보낸다.
    # 단, fallback_default가 아니라 명시적 manual rule로 처리한다.
    # ------------------------------------------------------------
    asian_delivery_keywords = [
        "커리",
        "카레",
        "팟타이",
        "쌀국수",
        "분짜",
        "나시고랭",
        "미고랭",
        "똠얌",
        "똠양",
        "카오팟",
        "푸팟퐁커리",
        "팟 퐁 커리",
        "가이 팟 퐁 커리",
        "탄두리",
        "난",
        "케밥",
        "타코",
        "부리또",
        "퀘사디아",
        "월남쌈",
        "반미",
        "샤브샤브",
        "훠궈",
    ]

    if any(keyword in food_name for keyword in asian_delivery_keywords):
        return (
            "restaurant",
            "delivery_food",
            "manual_restaurant_asian_delivery",
            "matched_by_manual_rule",
        )

    # ------------------------------------------------------------
    # 11. 배달/분식/일반 외식 메뉴
    # ------------------------------------------------------------
    delivery_keywords = [
        "도시락",
        "분식",
        "야식",
        "핫도그",
        "튀김만두",
        "만두",
        "떡",
        "어묵",
        "오뎅",
        "컵밥",
        "김말이",
    ]

    if any(keyword in food_name for keyword in delivery_keywords):
        return (
            "restaurant",
            "delivery_food",
            "manual_restaurant_delivery",
            "matched_by_manual_rule",
        )

        # ------------------------------------------------------------
    # 12. fallback 감소용 추가 보강 룰
    # 실제 fallback 리포트에서 발견된 음식명 기반 보정
    # ------------------------------------------------------------

    # 한식 식사류
    extra_korean_keywords = [
        "간장달걀밥",
        "계란밥",
        "달걀밥",
        "닭계장",
        "닭개장",
        "육개장",
        "돼지두루치기",
        "두부두루치기",
        "돼지짜글이",
        "짜글이",
        "명태조림",
        "조림",
        "묵밥",
        "묵사발",
        "물밀면",
        "비빔밀면",
        "밀면",
        "모시송편",
        "송편",
        "쑥버무리",
    ]

    if any(keyword in food_name for keyword in extra_korean_keywords):
        return (
            "restaurant",
            "korean_food",
            "manual_extra_korean",
            "matched_by_manual_rule",
        )

    # 중식
    extra_chinese_keywords = [
        "꿔바로우",
        "동파육",
        "라조기",
        "마라롱샤",
        "마라쇼룽샤",
        "마라빤",
        "가지튀김",
        "가지만두",
    ]

    if any(keyword in food_name for keyword in extra_chinese_keywords):
        return (
            "restaurant",
            "chinese_food",
            "manual_extra_chinese",
            "matched_by_manual_rule",
        )

    # 일식/돈가스류
    extra_japanese_keywords = [
        "돈가스",
        "돈까스",
        "돈카츠",
        "고구마돈가스",
        "고구마치즈돈가스",
        "로스카츠",
        "로제돈가스",
        "가라아케",
        "카라아게",
    ]

    if any(keyword in food_name for keyword in extra_japanese_keywords):
        return (
            "restaurant",
            "japanese_food",
            "manual_extra_japanese",
            "matched_by_manual_rule",
        )

    # 양식/브런치/펍 안주로 활용 가능한 메뉴
    extra_western_keywords = [
        "감바스",
        "맥앤치즈",
        "브로콜리수프",
        "수프",
        "스프",
        "나쵸",
        "나초",
        "버팔로윙",
    ]

    if any(keyword in food_name for keyword in extra_western_keywords):
        # 감바스/나쵸/버팔로윙은 술안주로도 좋지만,
        # 현재 식당 카테고리 내에서는 양식으로 먼저 분류한다.
        return (
            "restaurant",
            "western_food",
            "manual_extra_western",
            "matched_by_manual_rule",
        )

    # 치킨/닭튀김류
    extra_chicken_keywords = [
        "파닭",
        "순살파닭",
        "순살간장파닭",
        "순살양념파닭",
        "버팔로윙",
    ]

    if any(keyword in food_name for keyword in extra_chicken_keywords):
        return (
            "restaurant",
            "chicken",
            "manual_extra_chicken",
            "matched_by_manual_rule",
        )

    # 베이커리
    extra_bakery_keywords = [
        "꽈배기",
        "시나몬롤",
        "빨미까레",
    ]

    if any(keyword in food_name for keyword in extra_bakery_keywords):
        return ("bakery", "bread", "manual_extra_bakery", "matched_by_manual_rule")

    # 디저트
    extra_dessert_cake_keywords = [
        "까눌레",
        "마들렌",
        "단호박크럼블",
        "딸기롤케잌",
        "딸기롤케이크",
        "밀크크레이프",
        "크레이프",
        "크로플",
        "딸기크로플",
        "시나몬크로플",
        "와플",
        "바나나와플",
        "생딸기와플",
        "생크림와플",
    ]

    if any(keyword in food_name for keyword in extra_dessert_cake_keywords):
        return ("dessert", "cake", "manual_extra_dessert", "matched_by_manual_rule")

    # 카페 음료/브런치
    extra_cafe_drink_keywords = [
        "모히또",
        "미숫가루",
        "식혜",
    ]

    if any(keyword in food_name for keyword in extra_cafe_drink_keywords):
        return (
            "cafe",
            "ade_juice",
            "manual_extra_cafe_drink",
            "matched_by_manual_rule",
        )

    extra_cafe_brunch_keywords = [
        "그래놀라시리얼",
        "뮤즐리시리얼",
        "블루베리시리얼",
        "시리얼",
    ]

    if any(keyword in food_name for keyword in extra_cafe_brunch_keywords):
        return ("cafe", "brunch", "manual_extra_cafe_brunch", "matched_by_manual_rule")

    # 동남아/기타 외식류
    extra_asian_keywords = [
        "쏨땀",
        "솜땀",
        "팟타이",
        "쌀국수",
        "가이 팟 퐁 커리",
        "팟 퐁 커리",
        "커리",
    ]

    if any(keyword in food_name for keyword in extra_asian_keywords):
        return (
            "restaurant",
            "delivery_food",
            "manual_extra_asian",
            "matched_by_manual_rule",
        )

    # 기타 안주/간식류
    extra_pub_keywords = [
        "돼지간",
        "마약옥수수",
    ]

    if any(keyword in food_name for keyword in extra_pub_keywords):
        return ("pub", "korean_pub_food", "manual_extra_pub", "matched_by_manual_rule")

    # 기존 매핑 결과 유지
    return (business_category, product_group, matched_keyword, mapping_status)


def fallback_category(
    row: pd.Series,
    category_config: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    """
    끝까지 매핑되지 않은 데이터에 대한 기본값 처리.
    """
    policy = category_config.get("unmapped_policy", {})

    default_business = policy.get("default_business_category", "restaurant")
    default_group = policy.get("default_product_group", "delivery_food")

    return (
        default_business,
        default_group,
        "fallback_default",
        "fallback_default",
    )


def map_categories(df: pd.DataFrame, category_config: Dict[str, Any]) -> pd.DataFrame:
    rules = build_keyword_rules(category_config)

    mapped_rows = []

    for _, row in df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))
        original_food_name = normalize_text(row.get("original_food_name", ""))
        food_code = normalize_text(row.get("food_code", ""))

        business_category, product_group, matched_keyword, mapping_status = (
            infer_category_by_keyword(
                product_name=product_name,
                original_food_name=original_food_name,
                food_code=food_code,
                rules=rules,
            )
        )

        business_category, product_group, matched_keyword, mapping_status = (
            apply_manual_overrides(
                row=row,
                business_category=business_category,
                product_group=product_group,
                matched_keyword=matched_keyword,
                mapping_status=mapping_status,
            )
        )

        if not business_category or not product_group:
            business_category, product_group, matched_keyword, mapping_status = (
                fallback_category(
                    row=row,
                    category_config=category_config,
                )
            )

        mapped_rows.append(
            {
                "business_category": business_category,
                "product_group": product_group,
                "category_matched_keyword": matched_keyword,
                "category_mapping_status": mapping_status,
            }
        )

    mapped_df = pd.DataFrame(mapped_rows)
    result = pd.concat([df.reset_index(drop=True), mapped_df], axis=1)

    return result


def build_mapping_summary(df: pd.DataFrame) -> Dict[str, Any]:
    total_count = len(df)

    summary = {
        "total_count": int(total_count),
        "business_category_count": (
            df["business_category"].value_counts().to_dict()
            if "business_category" in df.columns
            else {}
        ),
        "product_group_count": (
            df["product_group"].value_counts().to_dict()
            if "product_group" in df.columns
            else {}
        ),
        "mapping_status_count": (
            df["category_mapping_status"].value_counts().to_dict()
            if "category_mapping_status" in df.columns
            else {}
        ),
        "unique_food_name_count": (
            int(df["original_food_name"].nunique())
            if "original_food_name" in df.columns
            else 0
        ),
    }

    return summary


def save_json(data: Dict[str, Any], path: Path) -> None:
    ensure_parent_dir(path)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_distribution(df: pd.DataFrame, column: str, output_path: Path) -> None:
    ensure_parent_dir(output_path)

    if column not in df.columns:
        pd.DataFrame(columns=[column, "count", "ratio"]).to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
        )
        return

    dist = (
        df[column]
        .fillna("")
        .astype(str)
        .replace("", "(missing)")
        .value_counts()
        .reset_index()
    )
    dist.columns = [column, "count"]
    dist["ratio"] = dist["count"] / len(df)

    dist.to_csv(output_path, index=False, encoding="utf-8-sig")


def save_unmapped_items(df: pd.DataFrame, output_path: Path) -> None:
    ensure_parent_dir(output_path)

    if "category_mapping_status" not in df.columns:
        return

    unmapped = df[
        df["category_mapping_status"].isin(["unmapped", "fallback_default"])
    ].copy()

    columns = [
        "original_food_name",
        "product_name",
        "food_code",
        "business_category",
        "product_group",
        "category_mapping_status",
        "category_matched_keyword",
    ]

    existing_cols = [col for col in columns if col in unmapped.columns]

    if existing_cols:
        result = (
            unmapped[existing_cols]
            .drop_duplicates()
            .sort_values(["business_category", "product_group", "original_food_name"])
        )
    else:
        result = unmapped

    result.to_csv(output_path, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build service category groups from raw metadata."
    )

    parser.add_argument(
        "--input",
        type=str,
        default="data/metadata/raw_metadata.parquet",
        help="Input raw metadata parquet path.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/category_map.yaml",
        help="Category mapping YAML path.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/metadata/category_enriched_metadata.parquet",
        help="Output enriched metadata parquet path.",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs/reports/category_mapping",
        help="Category mapping report directory.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    config_path = Path(args.config)
    output_path = Path(args.output)
    report_dir = Path(args.report_dir)

    print("[INFO] AIHub Food Ad RAG - Build Category Groups")
    print(f"[INFO] input     : {input_path}")
    print(f"[INFO] config    : {config_path}")
    print(f"[INFO] output    : {output_path}")
    print(f"[INFO] report_dir: {report_dir}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input metadata not found: {input_path}")

    category_config = load_yaml(config_path)
    df = pd.read_parquet(input_path)

    enriched_df = map_categories(df, category_config)

    ensure_parent_dir(output_path)
    enriched_df.to_parquet(output_path, index=False)

    report_dir.mkdir(parents=True, exist_ok=True)

    summary = build_mapping_summary(enriched_df)
    save_json(summary, report_dir / "category_mapping_summary.json")

    save_distribution(
        enriched_df,
        column="business_category",
        output_path=report_dir / "business_category_distribution.csv",
    )

    save_distribution(
        enriched_df,
        column="product_group",
        output_path=report_dir / "product_group_distribution.csv",
    )

    save_distribution(
        enriched_df,
        column="category_mapping_status",
        output_path=report_dir / "category_mapping_status_distribution.csv",
    )

    save_unmapped_items(
        enriched_df,
        output_path=report_dir / "unmapped_items.csv",
    )

    print("[DONE] Category mapping completed.")
    print(f"[DONE] enriched metadata: {output_path}")
    print(f"[DONE] summary          : {report_dir / 'category_mapping_summary.json'}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
