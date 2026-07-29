"""Core utilities for a controlled TrendCard prompt-strategy evaluation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import settings
from app.evaluation.metrics import TOXICITY_TERMS, UNSUPPORTED_CLAIM_TERMS
from app.modules.ad_copy.models import get_model_spec
from app.modules.ad_copy.output_validator import (
    CopyValidationResult,
    build_repair_feedback,
    normalize_copy_output,
    validate_copy_output,
)
from app.modules.ad_copy.schemas import AdCopyContent, AdCopyRequest, AdModel
from app.modules.ad_copy.service import (
    InvalidModelOutputError,
    _extract_content,
    _parse_content,
    build_prompt_messages,
)
from app.modules.ad_copy.trend_context import (
    TrendCard,
    TrendCardDataError,
    TrendCardNotFoundError,
    TrendCardNotUsableError,
    load_trend_card,
)
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    infer_provider,
    resolve_api_key,
    resolve_base_url,
    resolve_model_name,
)
from app.modules.model_runtime.schemas import TextRuntimeProvider


ArmStrategy = Literal[
    "trendcard",
    "few_shot_good",
    "few_shot_good_bad",
    "structured_cot",
    "lora",
]


class MemeExperimentDataError(ValueError):
    """Raised when experiment configuration or local fixtures are invalid."""


class MemeGenerationNotConfiguredError(RuntimeError):
    """Raised when a generation endpoint or its required key is missing."""


class MemeGenerationProviderError(RuntimeError):
    """Raised when an OpenAI-compatible generation endpoint fails."""


class MemeEvalArm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    strategy: ArmStrategy
    enabled: bool = True
    disabled_reason: str | None = Field(default=None, max_length=500)
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    adapter_revision: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_lora_endpoint(self) -> "MemeEvalArm":
        if self.enabled and self.strategy == "lora" and not all(
            (self.base_url, self.model, self.base_revision, self.adapter_revision)
        ):
            raise ValueError(
                "활성 LoRA arm에는 base_url, model, base_revision, "
                "adapter_revision이 모두 필요합니다"
            )
        if not self.enabled and not self.disabled_reason:
            raise ValueError("비활성 arm에는 disabled_reason이 필요합니다")
        return self


class MemeGenerationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=100, le=16000)
    # Total attempts: one initial generation plus, optionally, one constrained repair.
    max_attempts: Literal[1, 2] = 1
    repeats: int = Field(ge=1, le=20)
    concurrency: int = Field(ge=1, le=20)
    generation_seed: int = Field(ge=0, le=2_147_483_647)
    shuffle_seed: int


class MemeJudgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    model: Literal["gpt-4.1-mini-2025-04-14"] = "gpt-4.1-mini-2025-04-14"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: Literal["BRANDMATE_OPENAI_API_KEY"] = "BRANDMATE_OPENAI_API_KEY"
    temperature: Literal[0] = 0
    timeout_seconds: float = Field(gt=0, le=300)


class MemeExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    base_model: str = Field(min_length=1, max_length=200)
    trend_card_payload_path: str = Field(min_length=1)
    dataset_path: str = Field(min_length=1)
    few_shot_path: str = Field(min_length=1)
    fixture_review_path: str = Field(min_length=1)
    arms: list[MemeEvalArm] = Field(min_length=1)
    generation: MemeGenerationSettings
    judge: MemeJudgeSettings

    @model_validator(mode="after")
    def validate_unique_arms(self) -> "MemeExperimentConfig":
        arm_ids = [arm.id for arm in self.arms]
        if len(arm_ids) != len(set(arm_ids)):
            raise ValueError("arm id는 서로 달라야 합니다")
        strategies = [arm.strategy for arm in self.arms]
        if len(strategies) != len(set(strategies)):
            raise ValueError("각 strategy는 한 번만 선언해야 합니다")
        return self


class MemeEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    case_type: Literal["single_product", "multi_product", "promotion", "far_transfer"]
    request: dict[str, Any]


class FewShotOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_copy: str = Field(min_length=1, max_length=500)
    channel_post_opening: str = Field(min_length=1, max_length=500)
    publish_cta: str = Field(min_length=1, max_length=300)
    publish_hashtags: list[str] = Field(min_length=1, max_length=10)
    product_name_preserved: bool
    language: Literal["ko", "mixed", "non_ko"]
    failure_codes: list[
        Literal[
            "mechanical_template_copy",
            "feature_enumeration",
            "product_enumeration",
            "required_term_missing",
            "marker_missing",
            "product_name_changed",
            "non_korean_output",
            "unsupported_claim",
            "hashtag_format_invalid",
            "channel_contract_incomplete",
            "trend_subject_not_before_marker",
            "trend_reason_count_insufficient",
            "trend_reason_not_grounded",
        ]
    ] = Field(default_factory=list, max_length=10)


class FewShotExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str = Field(min_length=1, max_length=160)
    input: dict[str, Any]
    good_output: FewShotOutput
    bad_output: FewShotOutput
    rationale: list[str] = Field(min_length=1, max_length=10)
    demonstrates: list[str] = Field(min_length=1, max_length=10)


class MemeFixtureReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    source_kind: Literal["assistant_authored_scaffold", "human_curated"]
    review_status: Literal["seed_needs_review", "reviewed"]
    rights_review_status: Literal["seed_needs_review", "reviewed"]
    reviewed_by: str | None = Field(default=None, max_length=200)
    reviewed_at: str | None = Field(default=None, max_length=100)
    notes: str = Field(default="", max_length=1000)

    @property
    def decision_ready(self) -> bool:
        return (
            self.review_status == "reviewed"
            and self.rights_review_status == "reviewed"
        )


@dataclass(frozen=True)
class LoadedMemeExperiment:
    config_path: Path
    config: MemeExperimentConfig
    trend_card_payload_path: Path
    dataset_path: Path
    few_shot_path: Path
    fixture_review_path: Path
    trend_card: TrendCard
    cases: list[MemeEvalCase]
    examples: list[FewShotExample]
    fixture_review: MemeFixtureReview


@dataclass(frozen=True)
class GenerationEndpoint:
    base_url: str
    model: str
    api_key: str | None
    provider: TextRuntimeProvider
    supports_system_role: bool
    supports_structured_output: bool
    source: str
    base_revision: str | None = None
    adapter_revision: str | None = None


@dataclass(frozen=True)
class ArmGenerationResult:
    # ``content`` / ``raw_content`` / ``validation`` retain their legacy names
    # and always describe the final usable candidate (repaired when available).
    content: AdCopyContent
    raw_content: str
    initial_content: AdCopyContent
    raw_initial_content: str
    initial_validation: CopyValidationResult
    normalized_initial_content: AdCopyContent
    normalized_initial_validation: CopyValidationResult
    repair_content: AdCopyContent | None
    raw_repair_content: str | None
    repair_validation: CopyValidationResult | None
    repair_attempted: bool
    repair_success: bool
    repair_error: str | None
    latency_ms: float
    validation: CopyValidationResult
    structured_output_fallback: bool
    endpoint_model: str
    endpoint_source: str
    generation_seed: int
    base_revision: str | None
    adapter_revision: str | None
    request_count: int
    initial_request_count: int
    repair_request_count: int
    usage: dict[str, int]
    initial_usage: dict[str, int]
    repair_usage: dict[str, int]
    actual_model: str | None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemeExperimentDataError(f"JSON 파일을 읽을 수 없습니다: {path}") from error


def _resolve_fixture_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def load_meme_experiment(config_path: Path) -> LoadedMemeExperiment:
    """Load and cross-check one self-contained meme experiment."""

    resolved_config = config_path.resolve()
    try:
        config = MemeExperimentConfig.model_validate(_read_json(resolved_config))
        trend_card_payload_path = _resolve_fixture_path(
            resolved_config,
            config.trend_card_payload_path,
        )
        dataset_path = _resolve_fixture_path(resolved_config, config.dataset_path)
        few_shot_path = _resolve_fixture_path(resolved_config, config.few_shot_path)
        fixture_review_path = _resolve_fixture_path(
            resolved_config,
            config.fixture_review_path,
        )
        trend_card = load_trend_card(path=trend_card_payload_path)
        cases = [MemeEvalCase.model_validate(item) for item in _read_json(dataset_path)]
        examples = [FewShotExample.model_validate(item) for item in _read_json(few_shot_path)]
        fixture_review = MemeFixtureReview.model_validate(
            _read_json(fixture_review_path)
        )
    except (
        ValidationError,
        TypeError,
        TrendCardDataError,
        TrendCardNotFoundError,
        TrendCardNotUsableError,
    ) as error:
        raise MemeExperimentDataError(
            f"Meme 평가 설정 또는 fixture 형식이 올바르지 않습니다: {resolved_config}"
        ) from error

    if not cases:
        raise MemeExperimentDataError("Meme 평가 케이스가 비어 있습니다")
    if not examples:
        raise MemeExperimentDataError("Few-shot 예시가 비어 있습니다")
    if len({case.id for case in cases}) != len(cases):
        raise MemeExperimentDataError("평가 case id는 서로 달라야 합니다")
    if len({example.example_id for example in examples}) != len(examples):
        raise MemeExperimentDataError("Few-shot example id는 서로 달라야 합니다")

    for case in cases:
        try:
            request = AdCopyRequest.model_validate(
                {**case.request, "model": config.base_model}
            )
            load_trend_card(
                request.trend_card_id,
                path=trend_card_payload_path,
                require_channel=request.channel.value,
                prohibited_terms=request.prohibited_terms,
            )
        except (
            ValidationError,
            TrendCardDataError,
            TrendCardNotFoundError,
            TrendCardNotUsableError,
        ) as error:
            raise MemeExperimentDataError(
                f"평가 case 입력 또는 TrendCard gate가 올바르지 않습니다: {case.id}"
            ) from error
        if request.trend_card_id != trend_card.meme_id:
            raise MemeExperimentDataError(
                f"{case.id}의 trend_card_id가 현재 카드와 다릅니다: "
                f"{request.trend_card_id} != {trend_card.meme_id}"
            )
        if trend_card.suitable_channels and request.channel.value not in (
            trend_card.suitable_channels
        ):
            raise MemeExperimentDataError(
                f"{case.id}의 채널은 현재 TrendCard 평가 대상이 아닙니다: "
                f"{request.channel.value}"
            )

    return LoadedMemeExperiment(
        config_path=resolved_config,
        config=config,
        trend_card_payload_path=trend_card_payload_path,
        dataset_path=dataset_path,
        few_shot_path=few_shot_path,
        fixture_review_path=fixture_review_path,
        trend_card=trend_card,
        cases=cases,
        examples=examples,
        fixture_review=fixture_review,
    )


def _append_user_block(messages: list[dict[str, str]], block: str) -> list[dict[str, str]]:
    copied = [message.copy() for message in messages]
    for message in reversed(copied):
        if message["role"] == "user":
            message["content"] = f"{message['content']}\n\n{block}"
            return copied
    raise MemeExperimentDataError("기본 광고 프롬프트에 user 메시지가 없습니다")


def _good_only_examples(examples: list[FewShotExample]) -> list[dict[str, Any]]:
    return [
        {
            "input": example.input,
            "desired_adaptation": example.good_output.model_dump(),
            "demonstrates": example.demonstrates,
        }
        for example in examples
    ]


def _good_bad_examples(examples: list[FewShotExample]) -> list[dict[str, Any]]:
    return [
        {
            "input": example.input,
            "good": example.good_output.model_dump(),
            "bad": example.bad_output.model_dump(),
            "why": example.rationale,
        }
        for example in examples
    ]


def build_arm_messages(
    request: AdCopyRequest,
    trend_card: TrendCard,
    arm: MemeEvalArm,
    examples: list[FewShotExample],
    *,
    supports_system_role: bool = True,
) -> list[dict[str, str]]:
    """Build an arm prompt while keeping the production TrendCard prompt constant."""

    messages = build_prompt_messages(
        request,
        trend_card=trend_card,
        supports_system_role=supports_system_role,
    )
    if arm.strategy in {"trendcard", "lora"}:
        return messages

    if arm.strategy == "few_shot_good":
        example_json = json.dumps(_good_only_examples(examples), ensure_ascii=False, indent=2)
        block = f"""--------------------------------------------------
TrendCard 응용 참고 예시 (좋은 예시만)
--------------------------------------------------
아래 예시는 text_patterns를 상품 사실에 맞게 변형하는 방법만 보여줍니다.
primary_copy는 화면의 첫 광고 문구, channel_post_opening은
channel_recommendation.caption의 도입부에 대응합니다.
publish_cta와 publish_hashtags까지 모두 자연스러운 한국어로 작성하고,
상품명은 번역·축약하지 않으며 required_terms는 정확한 문자열로 포함하세요.
product_name_preserved, language, failure_codes는 예시 품질을 설명하는 주석이며
최종 광고 JSON에 새 필드로 추가하지 마세요.
예시의 상호명, 상품명, 특징, 혜택을 현재 결과에 재사용하지 마세요.
현재 사용자 입력의 사실과 TrendCard 규칙을 우선하고 최종 JSON만 출력하세요.

{example_json}"""
        return _append_user_block(messages, block)

    if arm.strategy == "few_shot_good_bad":
        example_json = json.dumps(_good_bad_examples(examples), ensure_ascii=False, indent=2)
        block = f"""--------------------------------------------------
TrendCard 응용 대조 예시 (좋은 예시 + 피해야 할 예시)
--------------------------------------------------
good은 관계와 이유를 만든 결과이고 bad는 단순 치환·나열로 피해야 할 결과입니다.
primary_copy는 화면의 첫 광고 문구, channel_post_opening은
channel_recommendation.caption의 도입부에 대응합니다.
good처럼 상품명을 원문 그대로 유지하고, marker와 required_terms를 필요한 위치에
정확히 포함하며, publish_cta와 publish_hashtags까지 자연스러운 한국어로 작성하세요.
bad.failure_codes는 피해야 할 위반 유형입니다. product_name_preserved, language,
failure_codes는 예시 주석이며 최종 광고 JSON에 새 필드로 추가하지 마세요.
예시의 상호명, 상품명, 특징, 혜택을 현재 결과에 재사용하지 마세요.
현재 사용자 입력의 사실과 TrendCard 규칙을 우선하고 최종 JSON만 출력하세요.

{example_json}"""
        return _append_user_block(messages, block)

    if arm.strategy == "structured_cot":
        block = """--------------------------------------------------
내부 작성 절차
--------------------------------------------------
최종 응답을 쓰기 전에 내부적으로만 다음 순서로 점검하세요.
1. 사용자 입력에서 사용할 수 있는 상품, 특징, 혜택, 금지 표현을 구분한다.
2. copy_structure에서 대상의 출처와 위치, marker 횟수, 입력 특징 기반 이유의 최소 개수와 종결 표현을 추출한다.
3. subject_source에 맞는 대표 대상을 선택하고 subject_position과 marker_occurrences를 지킨다.
4. 서로 다른 입력 특징을 reason_source로 사용해 필요한 수만큼 이유를 만들고, 각 이유를 reason_ending으로 끝내 반복 리듬을 만든다.
5. text_patterns를 현재 상품과 상황에 맞게 자연스럽게 변형하되 입력에 없는 맛, 색, 재료, 효능, 혜택은 추가하지 않는다.
6. 화면용 첫 광고 문구와 channel_recommendation.caption 도입부가 같은 구조를 모두 갖췄는지 확인한다.
7. 단순 상품명 나열, 예시 사실 혼입, 입력에 없는 주장, 금지 표현을 제거한다.

이 점검 과정이나 분석은 출력하지 말고 요청된 최종 JSON 객체만 출력하세요."""
        return _append_user_block(messages, block)

    raise MemeExperimentDataError(f"지원하지 않는 arm strategy입니다: {arm.strategy}")


def _named_api_key(name: str | None) -> str | None:
    if not name:
        return None
    setting_by_env = {
        "BRANDMATE_LLM_API_KEY": settings.llm_api_key,
        "BRANDMATE_LOCAL_LLM_API_KEY": settings.local_llm_api_key,
        "BRANDMATE_OPENAI_API_KEY": settings.openai_api_key,
        "BRANDMATE_QWEN_API_KEY": settings.qwen_api_key,
        "BRANDMATE_NVIDIA_API_KEY": settings.nvidia_api_key,
    }
    value = setting_by_env.get(name)
    if value is not None:
        if hasattr(value, "get_secret_value"):
            return value.get_secret_value() or None
        return str(value) or None
    return os.getenv(name)


def resolve_generation_endpoint(
    experiment: MemeExperimentConfig,
    arm: MemeEvalArm,
) -> GenerationEndpoint:
    """Resolve either the common Qwen endpoint or an explicit LoRA endpoint."""

    if arm.strategy == "lora":
        if not arm.enabled or not arm.base_url or not arm.model:
            raise MemeGenerationNotConfiguredError(
                arm.disabled_reason or "LoRA serving endpoint가 설정되지 않았습니다."
            )
        api_key = _named_api_key(arm.api_key_env)
        if arm.api_key_env and not api_key:
            raise MemeGenerationNotConfiguredError(
                f"LoRA endpoint API key 환경변수가 없습니다: {arm.api_key_env}"
            )
        return GenerationEndpoint(
            base_url=arm.base_url,
            model=arm.model,
            api_key=api_key,
            provider=infer_provider(arm.base_url, TextRuntimeProvider.VLLM),
            supports_system_role=True,
            supports_structured_output=True,
            source="lora",
            base_revision=arm.base_revision,
            adapter_revision=arm.adapter_revision,
        )

    # Once a LoRA arm is enabled, every non-LoRA arm must use the base model on
    # that same server. Otherwise hosted-vs-local latency/runtime differences
    # would be confounded with the adapter effect.
    active_lora = next(
        (
            candidate
            for candidate in experiment.arms
            if candidate.enabled and candidate.strategy == "lora"
        ),
        None,
    )
    if active_lora is not None:
        if not active_lora.base_url:
            raise MemeGenerationNotConfiguredError(
                "활성 LoRA arm의 공통 serving base_url이 없습니다."
            )
        api_key = _named_api_key(active_lora.api_key_env)
        if active_lora.api_key_env and not api_key:
            raise MemeGenerationNotConfiguredError(
                "공통 LoRA server API key 환경변수가 없습니다: "
                f"{active_lora.api_key_env}"
            )
        return GenerationEndpoint(
            base_url=active_lora.base_url,
            model=experiment.base_model,
            api_key=api_key,
            provider=infer_provider(active_lora.base_url, TextRuntimeProvider.VLLM),
            supports_system_role=True,
            supports_structured_output=True,
            source="shared_lora_server_base",
            base_revision=active_lora.base_revision,
        )

    try:
        model = AdModel(experiment.base_model)
        model_spec = get_model_spec(model)
        model_config = get_text_model_config(experiment.base_model)
    except (KeyError, ValueError) as error:
        raise MemeGenerationNotConfiguredError(
            f"등록되지 않은 공통 생성 모델입니다: {experiment.base_model}"
        ) from error

    base_url = resolve_base_url(model_config)
    api_key = resolve_api_key(model_config)
    provider = infer_provider(base_url, model_config.provider)
    if provider in {
        TextRuntimeProvider.HUGGING_FACE_ROUTER,
        TextRuntimeProvider.OPENAI,
        TextRuntimeProvider.NVIDIA,
    } and not api_key:
        raise MemeGenerationNotConfiguredError(
            f"{model_config.api_key_setting}가 없습니다. API 서버의 .env를 설정해주세요."
        )
    return GenerationEndpoint(
        base_url=base_url,
        model=resolve_model_name(model_config),
        api_key=api_key,
        provider=provider,
        supports_system_role=model_spec.supports_system_role,
        supports_structured_output=model_spec.supports_structured_output,
        source="base",
    )


def _generation_payload(
    request: AdCopyRequest,
    endpoint: GenerationEndpoint,
    messages: list[dict[str, str]],
    generation: MemeGenerationSettings,
    generation_seed: int,
    *,
    structured: bool,
    temperature: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": endpoint.model,
        "messages": messages,
        "temperature": (
            generation.temperature if temperature is None else temperature
        ),
        "seed": generation_seed,
    }
    token_key = (
        "max_completion_tokens"
        if endpoint.provider == TextRuntimeProvider.OPENAI
        and endpoint.model.startswith("gpt-5")
        else "max_tokens"
    )
    payload[token_key] = generation.max_tokens
    if structured and request.channel.value != "naver_blog":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "AdCopyContent",
                "strict": True,
                "schema": AdCopyContent.model_json_schema(),
            },
        }
    return payload


def _structured_output_is_unsupported(response: httpx.Response) -> bool:
    if response.status_code not in {400, 422}:
        return False
    detail = response.text.casefold()
    markers = (
        "response_format",
        "json_schema",
        "json schema",
        "structured output",
        "structured_output",
        "failed to compile grammar",
        "grammar compilation",
    )
    return any(marker in detail for marker in markers)


def _response_metadata(response: httpx.Response) -> tuple[dict[str, int], str | None]:
    try:
        body = response.json()
    except json.JSONDecodeError:
        return {}, None
    raw_usage = body.get("usage") if isinstance(body, dict) else None
    usage = {
        key: value
        for key, value in (raw_usage or {}).items()
        if isinstance(key, str) and isinstance(value, int)
    }
    actual_model = body.get("model") if isinstance(body, dict) else None
    return usage, actual_model if isinstance(actual_model, str) else None


def _merge_usage(*usages: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for usage in usages:
        for key, value in usage.items():
            merged[key] = merged.get(key, 0) + value
    return merged


async def _post_generation_request(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: dict[str, str],
    request: AdCopyRequest,
    endpoint: GenerationEndpoint,
    messages: list[dict[str, str]],
    generation: MemeGenerationSettings,
    generation_seed: int,
    structured: bool,
    temperature: float | None = None,
) -> tuple[httpx.Response, bool, int]:
    """Send one logical attempt, with the existing schema fallback if needed."""

    request_count = 1
    try:
        response = await client.post(
            url,
            headers=headers,
            json=_generation_payload(
                request,
                endpoint,
                messages,
                generation,
                generation_seed,
                structured=structured,
                temperature=temperature,
            ),
        )
        structured_fallback = structured and _structured_output_is_unsupported(
            response
        )
        if structured_fallback:
            request_count += 1
            response = await client.post(
                url,
                headers=headers,
                json=_generation_payload(
                    request,
                    endpoint,
                    messages,
                    generation,
                    generation_seed,
                    structured=False,
                    temperature=temperature,
                ),
            )
        response.raise_for_status()
    except httpx.HTTPError as error:
        error.generation_request_count = request_count  # type: ignore[attr-defined]
        raise
    return response, structured_fallback, request_count


def _build_repair_messages(
    messages: list[dict[str, str]],
    initial_content: AdCopyContent,
    validation: CopyValidationResult,
) -> list[dict[str, str]]:
    previous_json = json.dumps(
        initial_content.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    feedback = build_repair_feedback(validation)
    return [
        *[message.copy() for message in messages],
        {"role": "assistant", "content": previous_json},
        {
            "role": "user",
            "content": f"""--------------------------------------------------
검증 실패 교정 요청
--------------------------------------------------
직전 JSON의 스키마와 입력 사실은 유지하고 아래 실패 항목만 교정하세요.
상품명과 required_terms는 원문 문자열을 유지하고, 고객 노출 필드는 자연스러운
한국어로 작성하세요. 입력에 없는 효능·혜택·주문 조건을 새로 만들지 마세요.
TrendCard 표현은 화면의 첫 광고 문구와 채널 게시물 첫 문장에 자연스럽게 반영하세요.
분석이나 설명 없이 교정된 전체 JSON 객체만 출력하세요.

{feedback}""",
        },
    ]


async def generate_arm_copy(
    request: AdCopyRequest,
    experiment: MemeExperimentConfig,
    trend_card: TrendCard,
    arm: MemeEvalArm,
    examples: list[FewShotExample],
    generation_seed: int,
) -> ArmGenerationResult:
    """Generate a raw candidate and optionally run one validator-guided repair."""

    endpoint = resolve_generation_endpoint(experiment, arm)
    messages = build_arm_messages(
        request,
        trend_card,
        arm,
        examples,
        supports_system_role=endpoint.supports_system_role,
    )
    headers = {"Content-Type": "application/json"}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
    structured = endpoint.supports_structured_output
    structured_fallback = False
    initial_request_count = 0
    repair_request_count = 0
    started_at = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response, initial_fallback, initial_request_count = (
                await _post_generation_request(
                    client,
                    url=url,
                    headers=headers,
                    request=request,
                    endpoint=endpoint,
                    messages=messages,
                    generation=experiment.generation,
                    generation_seed=generation_seed,
                    structured=structured,
                )
            )
            structured_fallback = initial_fallback

            initial_usage, initial_actual_model = _response_metadata(response)
            try:
                raw_initial_content = _extract_content(response)
                initial_content = _parse_content(raw_initial_content)
                initial_validation = validate_copy_output(
                    initial_content,
                    request,
                    trend_card,
                )
                normalized_initial_content = normalize_copy_output(
                    initial_content,
                    request,
                    trend_card,
                )
                normalized_initial_validation = validate_copy_output(
                    normalized_initial_content,
                    request,
                    trend_card,
                )
            except InvalidModelOutputError as error:
                error.request_count = initial_request_count  # type: ignore[attr-defined]
                error.usage = initial_usage  # type: ignore[attr-defined]
                error.actual_model = initial_actual_model  # type: ignore[attr-defined]
                raise

            content = normalized_initial_content
            raw_content = raw_initial_content
            validation = normalized_initial_validation
            repair_content: AdCopyContent | None = None
            raw_repair_content: str | None = None
            repair_validation: CopyValidationResult | None = None
            repair_attempted = (
                experiment.generation.max_attempts == 2
                and not normalized_initial_validation.valid
            )
            repair_success = False
            repair_error: str | None = None
            repair_usage: dict[str, int] = {}
            actual_model = initial_actual_model

            if repair_attempted:
                repair_messages = _build_repair_messages(
                    messages,
                    normalized_initial_content,
                    normalized_initial_validation,
                )
                try:
                    repair_response, repair_fallback, repair_request_count = (
                        await _post_generation_request(
                            client,
                            url=url,
                            headers=headers,
                            request=request,
                            endpoint=endpoint,
                            messages=repair_messages,
                            generation=experiment.generation,
                            generation_seed=generation_seed,
                            structured=structured and not initial_fallback,
                            temperature=0.2,
                        )
                    )
                    structured_fallback = structured_fallback or repair_fallback
                    repair_usage, repair_actual_model = _response_metadata(
                        repair_response
                    )
                    actual_model = repair_actual_model or actual_model
                    raw_repair_content = _extract_content(repair_response)
                    repair_content = normalize_copy_output(
                        _parse_content(raw_repair_content),
                        request,
                        trend_card,
                    )
                    repair_validation = validate_copy_output(
                        repair_content,
                        request,
                        trend_card,
                    )
                    content = repair_content
                    raw_content = raw_repair_content
                    validation = repair_validation
                    repair_success = repair_validation.valid
                except httpx.HTTPError as error:
                    repair_request_count = int(
                        getattr(error, "generation_request_count", 1)
                    )
                    repair_error = (
                        f"repair endpoint 오류: {type(error).__name__}"
                    )
                except InvalidModelOutputError as error:
                    repair_error = f"repair 응답 형식 오류: {error}"
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:500]
        wrapped = MemeGenerationProviderError(
            f"{arm.id} 생성 호출이 거절되었습니다: {detail}"
        )
        wrapped.request_count = int(  # type: ignore[attr-defined]
            getattr(error, "generation_request_count", initial_request_count or 1)
        )
        wrapped.usage = {}  # type: ignore[attr-defined]
        raise wrapped from error
    except httpx.HTTPError as error:
        wrapped = MemeGenerationProviderError(
            f"{arm.id} 생성 endpoint에 연결할 수 없습니다: {type(error).__name__}"
        )
        wrapped.request_count = int(  # type: ignore[attr-defined]
            getattr(error, "generation_request_count", initial_request_count or 1)
        )
        wrapped.usage = {}  # type: ignore[attr-defined]
        raise wrapped from error

    usage = _merge_usage(initial_usage, repair_usage)
    request_count = initial_request_count + repair_request_count
    return ArmGenerationResult(
        content=content,
        raw_content=raw_content,
        initial_content=initial_content,
        raw_initial_content=raw_initial_content,
        initial_validation=initial_validation,
        normalized_initial_content=normalized_initial_content,
        normalized_initial_validation=normalized_initial_validation,
        repair_content=repair_content,
        raw_repair_content=raw_repair_content,
        repair_validation=repair_validation,
        repair_attempted=repair_attempted,
        repair_success=repair_success,
        repair_error=repair_error,
        latency_ms=round((perf_counter() - started_at) * 1000, 2),
        validation=validation,
        structured_output_fallback=structured_fallback,
        endpoint_model=endpoint.model,
        endpoint_source=endpoint.source,
        generation_seed=generation_seed,
        base_revision=endpoint.base_revision,
        adapter_revision=endpoint.adapter_revision,
        request_count=request_count,
        initial_request_count=initial_request_count,
        repair_request_count=repair_request_count,
        usage=usage,
        initial_usage=initial_usage,
        repair_usage=repair_usage,
        actual_model=actual_model,
    )


def customer_visible_text(content: AdCopyContent) -> str:
    recommendation = content.channel_recommendation
    blog_text = " ".join(
        str(section.get(field, ""))
        for section in recommendation.blog_sections
        for field in ("title", "body")
    )
    return " ".join(
        [
            *content.headlines,
            *content.body_copies,
            *content.ctas,
            *content.hashtags,
            recommendation.overlay_headline,
            recommendation.caption,
            recommendation.publish_cta,
            *recommendation.publish_hashtags,
            recommendation.publish_title,
            recommendation.publish_body,
            recommendation.blog_title,
            blog_text,
        ]
    )


def find_example_leakage(
    request: AdCopyRequest,
    content: AdCopyContent,
    examples: list[FewShotExample],
) -> list[str]:
    """Flag exact example facts that are absent from the current request."""

    request_facts = json.dumps(request.model_dump(mode="json"), ensure_ascii=False).casefold()
    generated = customer_visible_text(content).casefold()
    normalized_request = re.sub(r"[^0-9a-z가-힣]+", "", request_facts)
    normalized_generated = re.sub(r"[^0-9a-z가-힣]+", "", generated)
    candidates: set[str] = set()
    distinctive_tokens: set[str] = set()
    generic_tokens = {
        "메뉴",
        "상품",
        "세트",
        "제공",
        "가능",
        "주문",
        "평일",
        "점심",
        "신메뉴",
        "출시",
        "사용",
        "아이스",
        "크림",
    }
    for example in examples:
        raw_input = example.input
        values = [raw_input.get("business_name"), raw_input.get("promotion")]
        values.extend(raw_input.get("product_names", []))
        values.extend(raw_input.get("features", []))
        for value in values:
            if isinstance(value, str) and len(value.strip()) >= 2:
                candidates.add(value.strip())
                distinctive_tokens.update(
                    token.casefold()
                    for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
                    if len(token) >= 3 and token.casefold() not in generic_tokens
                )

    leaked = {
        value
        for value in candidates
        if (
            re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())
            in normalized_generated
            and re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())
            not in normalized_request
        )
    }
    leaked.update(
        token
        for token in distinctive_tokens
        if token in normalized_generated and token not in normalized_request
    )
    return sorted(leaked)


def marker_compliance(content: AdCopyContent, trend_card: TrendCard) -> bool:
    generated = customer_visible_text(content).casefold()
    return any(marker.casefold() in generated for marker in trend_card.copy_markers)


def visible_required_term_compliance_rate(
    request: AdCopyRequest,
    content: AdCopyContent,
) -> float:
    if not request.required_terms:
        return 1.0
    generated = customer_visible_text(content).casefold()
    return round(
        sum(term.casefold() in generated for term in request.required_terms)
        / len(request.required_terms),
        4,
    )


def visible_context_adherence_score(
    request: AdCopyRequest,
    content: AdCopyContent,
) -> float:
    """Measure facts across primary copy and the actual channel post."""

    generated = customer_visible_text(content).casefold()
    components: list[float] = []
    product_scores: list[float] = []
    for product in request.product_names:
        tokens = [
            token
            for token in re.split(r"[\s,/]+", product.casefold())
            if token
        ]
        if tokens:
            product_scores.append(
                sum(token in generated for token in tokens) / len(tokens)
            )
    if product_scores:
        components.append(mean(product_scores))
    components.append(visible_required_term_compliance_rate(request, content))
    if request.prohibited_terms:
        components.append(
            1
            - sum(term.casefold() in generated for term in request.prohibited_terms)
            / len(request.prohibited_terms)
        )
    return round(mean(components), 4)


def visible_hallucination_terms(
    request: AdCopyRequest,
    content: AdCopyContent,
) -> list[str]:
    source = json.dumps(request.model_dump(mode="json"), ensure_ascii=False).casefold()
    generated = customer_visible_text(content).casefold()
    terms = set(UNSUPPORTED_CLAIM_TERMS)
    if request.situation.value in {"delivery", "takeout"} or (
        request.channel.value == "delivery_app"
    ):
        terms.discard("배송")
        terms.discard("주문")
    return sorted(
        term
        for term in terms
        if term.casefold() in generated and term.casefold() not in source
    )


def visible_toxicity_terms(content: AdCopyContent) -> list[str]:
    generated = customer_visible_text(content).casefold()
    return sorted(term for term in TOXICITY_TERMS if term.casefold() in generated)


def parse_failure_type(error: Exception) -> str:
    if isinstance(error, InvalidModelOutputError):
        return "invalid_model_output"
    if isinstance(error, MemeGenerationNotConfiguredError):
        return "generation_not_configured"
    if isinstance(error, MemeGenerationProviderError):
        return "generation_provider_error"
    return type(error).__name__
