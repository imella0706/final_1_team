"""Run the same advertising request against every configured model."""

from time import perf_counter

import httpx


API_URL = "http://localhost:8000/api/v1/ad-copies/generate"
MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "nvidia/meta/llama-3.1-8b-instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "google/gemma-2-9b-it",
    "microsoft/Phi-4-mini-instruct",
    "upstage/SOLAR-10.7B-Instruct-v1.0",
]
BASE_REQUEST = {
    "business_name": "오후의 조각",
    "business_type": "cafe",
    "situation": "new_menu",
    "target_audiences": ["twenties", "office_workers"],
    "tone": "emotional",
    "product_names": ["수제 딸기 티라미수", "런치세트"],
    "features": ["매일 직접 만든 디저트", "신선한 딸기 사용"],
    "channel": "instagram",
    "promotion": "7월 한정 10% 할인",
    "required_terms": ["생딸기"],
    "prohibited_terms": ["최고", "무조건", "인생 맛집"],
}


def main() -> None:
    print("model\tstatus\tapi_ms\twall_ms\tprovider", flush=True)
    with httpx.Client(timeout=300) as client:
        for model in MODELS:
            started_at = perf_counter()
            try:
                response = client.post(
                    API_URL,
                    json={**BASE_REQUEST, "model": model},
                )
                wall_ms = round((perf_counter() - started_at) * 1000)
                body = response.json()
                if response.is_success:
                    print(
                        f"{model}\tOK\t{body['latency_ms']}\t"
                        f"{wall_ms}\t{body['provider']}",
                        flush=True,
                    )
                else:
                    detail = str(body.get("detail", "")).replace("\n", " ")[:160]
                    print(
                        f"{model}\tHTTP {response.status_code}\t-\t"
                        f"{wall_ms}\t{detail}",
                        flush=True,
                    )
            except (httpx.HTTPError, ValueError) as error:
                wall_ms = round((perf_counter() - started_at) * 1000)
                print(
                    f"{model}\tERROR\t-\t{wall_ms}\t"
                    f"{type(error).__name__}: {error}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
