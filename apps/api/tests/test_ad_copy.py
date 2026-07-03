import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import app
from app.core.config import settings
from app.modules.ad_copy.prompt import PROMPT_VERSION, build_prompt
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.ad_copy.service import _parse_content


def sample_request() -> dict[str, object]:
    return {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "business_name": "동네봄 카페",
        "business_type": "cafe",
        "situation": "new_menu",
        "target_audiences": ["twenties", "office_workers"],
        "tone": "emotional",
        "product_names": ["수제 딸기 티라미수", "런치세트"],
        "features": ["매일 손질한 생딸기", "직접 만든 딸기청"],
        "channel": "instagram",
        "promotion": "7월 한 달간 10% 할인",
        "required_terms": ["생딸기"],
        "prohibited_terms": ["무조건", "최고"],
    }


def test_build_prompt_uses_business_facts_and_safety_terms() -> None:
    prompt = build_prompt(AdCopyRequest.model_validate(sample_request()))

    assert PROMPT_VERSION == "ad-copy-v1"
    assert "동네봄 카페" in prompt
    assert "수제 딸기 티라미수, 런치세트" in prompt
    assert "매일 손질한 생딸기" in prompt
    assert "필수 표현: 생딸기" in prompt
    assert "금지 표현: 무조건, 최고" in prompt


def test_model_catalog_contains_all_comparison_models() -> None:
    response = TestClient(app).get("/api/v1/ad-copies/models")

    assert response.status_code == 200
    models = response.json()
    assert len(models) == 6
    assert models[0]["id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert models[0]["recommended"] is True
    assert models[2]["availability"] == "local_only"
    assert models[3]["availability"] == "local_only"
    assert models[4]["availability"] == "local_only"
    assert models[5]["availability"] == "research_only"


def test_generate_returns_clear_error_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", None)
    response = TestClient(app).post("/api/v1/ad-copies/generate", json=sample_request())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "BRANDMATE_LLM_API_KEY가 없습니다. API 서버의 .env를 설정해주세요."
    }


def test_generate_uses_selected_model_and_returns_structured_copy(monkeypatch) -> None:
    captured_payloads: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, json):
            del headers
            captured_payloads.append(json)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"headlines":["딸기빛 오후를 한 조각"],'
                                    '"body_copies":["수제 딸기 티라미수로 달콤한 오후를 만나보세요."],'
                                    '"ctas":["오늘 매장에서 만나보세요."],'
                                    '"hashtags":["#딸기티라미수","#동네카페"],'
                                    '"image_prompt":"Editorial strawberry tiramisu photography",'
                                    '"safety_notes":[]}'
                                )
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(settings, "llm_api_key", SecretStr("test-token"))
    monkeypatch.setattr(
        "app.modules.ad_copy.service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    request = sample_request()
    request["model"] = "microsoft/Phi-4-mini-instruct"
    response = TestClient(app).post("/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 200
    assert response.json()["model"] == "microsoft/Phi-4-mini-instruct"
    assert response.json()["headlines"] == ["딸기빛 오후를 한 조각"]
    assert captured_payloads[0]["model"] == "microsoft/Phi-4-mini-instruct"
    assert captured_payloads[0]["response_format"]["type"] == "json_schema"


def test_parse_content_normalizes_single_string_to_list() -> None:
    content = _parse_content(
        '{"headlines":"새로운 한 조각",'
        '"body_copies":["오늘 만나보세요."],'
        '"ctas":"지금 방문해보세요.",'
        '"hashtags":["#신메뉴"],'
        '"image_prompt":"Editorial dessert photography",'
        '"safety_notes":"과장 표현이 없는지 확인해주세요."}'
    )

    assert content.headlines == ["새로운 한 조각"]
    assert content.ctas == ["지금 방문해보세요."]
    assert content.safety_notes == ["과장 표현이 없는지 확인해주세요."]


def test_parse_content_ignores_explanation_after_json() -> None:
    content = _parse_content(
        '{"headlines":["새로운 한 조각"],'
        '"body_copies":["오늘 만나보세요."],'
        '"ctas":["지금 방문해보세요."],'
        '"hashtags":["#신메뉴"],'
        '"image_prompt":"Editorial dessert photography",'
        '"safety_notes":[]}\n'
        "위 JSON은 요청한 광고 문구입니다."
    )

    assert content.headlines == ["새로운 한 조각"]
