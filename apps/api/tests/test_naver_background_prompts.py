from app.extensions.ad_content.naver_background_prompts import build_naver_background_prompt


def test_korean_business_types_map_to_expected_background_templates() -> None:
    expected = {
        "카페": ("cafe", "cafe"),
        "베이커리": ("bakery", "cafe"),
        "디저트": ("dessert", "cafe"),
        "음식점": ("restaurant", "restaurant"),
        "주점": ("pub", "pub"),
    }

    for business_type, (normalized, template) in expected.items():
        result = build_naver_background_prompt(business_type)
        assert result.business_type == normalized
        assert result.template == template
        assert "no food" in result.prompt.lower()
        assert "no text" in result.prompt.lower()


def test_unknown_business_type_uses_restaurant_template() -> None:
    result = build_naver_background_prompt("기타")

    assert result.business_type == "restaurant"
    assert result.template == "restaurant"
