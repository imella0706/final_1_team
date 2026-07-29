# LLM Runtime

광고 문구 생성용 LLM은 모델 서버를 먼저 띄운 뒤 FastAPI가 HTTP API로 호출합니다.

## 지원 대상

| 모델 | 기본 실행 방식 | 설정 |
| --- | --- | --- |
| Mistral 7B Instruct v0.3 | LM Studio | `BRANDMATE_MISTRAL_MODEL` |
| Gemma 2 9B Instruct | LM Studio | `BRANDMATE_GEMMA_MODEL` |
| Phi 4 Mini Instruct | LM Studio | `BRANDMATE_PHI_MODEL` |
| SOLAR 10.7B Instruct | LM Studio | `BRANDMATE_SOLAR_MODEL` |
| Qwen 2.5 7B Instruct | Hugging Face Router 또는 LM Studio/Ollama | `BRANDMATE_QWEN_MODEL` |
| Llama 3.1 8B Instruct | Hugging Face Router 또는 LM Studio/Ollama | `BRANDMATE_LLAMA_MODEL` |

## LM Studio 실행

1. LM Studio에서 모델을 다운로드합니다.
2. `Developer` 또는 `Local Server` 화면에서 서버를 켭니다.
3. CMD에서 모델 ID를 확인합니다.

```bat
curl http://localhost:1234/v1/models
```

4. `.env`에 반영합니다.

```env
BRANDMATE_LOCAL_LLM_BASE_URL=http://localhost:1234/v1
BRANDMATE_LOCAL_LLM_API_KEY=

BRANDMATE_MISTRAL_MODEL=lm-studio에_표시된_mistral_id
BRANDMATE_GEMMA_MODEL=lm-studio에_표시된_gemma_id
BRANDMATE_PHI_MODEL=lm-studio에_표시된_phi_id
BRANDMATE_SOLAR_MODEL=lm-studio에_표시된_solar_id
```

## Ollama 확장

Ollama도 OpenAI-compatible endpoint를 제공합니다.

```bat
ollama pull qwen2.5:7b
ollama pull llama3.1:8b
```

```env
BRANDMATE_QWEN_BASE_URL=http://localhost:11434/v1
BRANDMATE_QWEN_MODEL=qwen2.5:7b

BRANDMATE_LLAMA_BASE_URL=http://localhost:11434/v1
BRANDMATE_LLAMA_MODEL=llama3.1:8b
```

## vLLM 확장

Windows 네이티브보다는 WSL2/Linux GPU 서버에서 실행하는 방식을 권장합니다.

```bash
vllm serve mistralai/Mistral-7B-Instruct-v0.3 --host 0.0.0.0 --port 8001 --served-model-name mistralai/Mistral-7B-Instruct-v0.3
```

```env
BRANDMATE_MISTRAL_BASE_URL=http://localhost:8001/v1
BRANDMATE_MISTRAL_MODEL=mistralai/Mistral-7B-Instruct-v0.3
```

## 요청 예시

```bat
curl -X POST http://127.0.0.1:8000/api/llm/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"mistral-7b-instruct-v0.3\",\"prompt\":\"딸기 티라미수 광고 문구를 만들어줘\"}"
```
