import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.evaluation import text_judge
from app.evaluation.meme_arm_runner import load_meme_experiment
from app.evaluation.text_judge import (
    InvalidMemeJudgeOutputError,
    build_meme_judge_input,
    build_meme_judge_messages,
    judge_meme_copy_with_metadata,
    parse_meme_judge_result,
)
from app.modules.ad_copy.output_validator import build_fallback_copy
from app.modules.ad_copy.schemas import AdCopyRequest


API_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_PATH = API_ROOT / "evals" / "meme_5arm_experiment.json"


def _judge_fixture():
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    content = build_fallback_copy(request, [], loaded.trend_card)
    return loaded, request, content


def test_judge_input_is_blind_and_allow_listed() -> None:
    loaded, request, content = _judge_fixture()
    judge_input = build_meme_judge_input(request, loaded.trend_card, content)
    payload = judge_input.model_dump(mode="json")

    assert "model" not in payload["request_facts"]
    assert "trend_card_id" not in payload["request_facts"]
    assert set(payload["trend_context"]) == {
        "meaning",
        "text_patterns",
        "usage_rules",
        "prohibited_usage",
        "copy_markers",
    }
    assert set(payload) == {
        "request_facts",
        "trend_context",
        "operational_requirements",
        "customer_visible_result",
    }
    requirements = "\n".join(payload["operational_requirements"])
    assert "caption의 첫 문장" in requirements
    assert "publish_body" in requirements
    assert "publish_cta" in requirements
    serialized = "\n".join(
        message["content"] for message in build_meme_judge_messages(judge_input)
    )
    assert "few_shot_good" not in serialized
    assert "structured_cot" not in serialized
    assert loaded.config.base_model not in serialized
    assert "operational_requirements" in serialized
    assert "channel_readiness는 최대 2점" in serialized


def test_judge_result_is_strict_json_and_computes_overall_score() -> None:
    result = parse_meme_judge_result(
        """{
          "naturalness": 5,
          "pattern_fidelity": 4,
          "product_relevance": 5,
          "factuality": 4,
          "channel_readiness": 3,
          "hard_failures": [],
          "reason": "상품 사실에 맞게 자연스럽게 응용했다."
        }"""
    )
    assert result.overall_score == 4.2

    with pytest.raises(InvalidMemeJudgeOutputError):
        parse_meme_judge_result(
            """```json
            {"naturalness": 5}
            ```"""
        )


def test_judge_uses_configured_endpoint_model_timeout_and_records_usage(
    monkeypatch,
) -> None:
    loaded, request, content = _judge_fixture()
    captured = {}
    response_payload = {
        "model": "gpt-4.1-mini-2025-04-14",
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        "choices": [
            {
                "message": {
                    "content": (
                        '{"naturalness":5,"pattern_fidelity":4,'
                        '"product_relevance":5,"factuality":5,'
                        '"channel_readiness":4,"hard_failures":[],'
                        '"reason":"자연스럽고 사실에 맞는다."}'
                    )
                }
            }
        ],
    }

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            captured.update({"url": url, "headers": headers, "payload": json})
            return httpx.Response(
                200,
                json=response_payload,
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("judge-test-key"))
    monkeypatch.setattr(text_judge.httpx, "AsyncClient", FakeClient)

    call = asyncio.run(
        judge_meme_copy_with_metadata(
            request,
            loaded.trend_card,
            content,
            base_url_override="https://judge.example/v1",
            model_override="gpt-4.1-mini-2025-04-14",
            timeout_seconds=7,
        )
    )

    assert captured["url"] == "https://judge.example/v1/chat/completions"
    assert captured["timeout"] == 7
    assert captured["payload"]["model"] == "gpt-4.1-mini-2025-04-14"
    assert call.actual_model == "gpt-4.1-mini-2025-04-14"
    assert call.usage["total_tokens"] == 130
    assert call.result.overall_score == 4.6
