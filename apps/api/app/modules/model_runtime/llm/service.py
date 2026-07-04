from time import perf_counter

from app.modules.model_runtime.llm.clients import (
    HuggingFaceRouterClient,
    LMStudioClient,
    LlmRuntimeError,
    OllamaClient,
    OpenAICompatibleClient,
    VllmClient,
)
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    infer_provider,
    resolve_api_key,
    resolve_base_url,
    resolve_model_name,
)
from app.modules.model_runtime.schemas import (
    LlmGenerateRequest,
    LlmGenerateResponse,
    TextRuntimeProvider,
)


CLIENTS: dict[TextRuntimeProvider, OpenAICompatibleClient] = {
    TextRuntimeProvider.HUGGING_FACE_ROUTER: HuggingFaceRouterClient(),
    TextRuntimeProvider.LM_STUDIO: LMStudioClient(),
    TextRuntimeProvider.OLLAMA: OllamaClient(),
    TextRuntimeProvider.VLLM: VllmClient(),
}


async def generate_text(request: LlmGenerateRequest) -> LlmGenerateResponse:
    started_at = perf_counter()
    try:
        config = get_text_model_config(request.model)
    except KeyError as error:
        raise LlmRuntimeError(str(error)) from error

    base_url = resolve_base_url(config)
    model_name = resolve_model_name(config)
    api_key = resolve_api_key(config)
    provider = infer_provider(base_url, config.provider)
    messages = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.append({"role": "user", "content": request.prompt})

    content = await CLIENTS[provider].generate(
        config=config,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        messages=messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    return LlmGenerateResponse(
        model=model_name,
        provider=provider,
        content=content,
        latency_ms=round((perf_counter() - started_at) * 1000),
    )
