"""Vision evaluation metrics for generated advertising images."""

import base64
import binascii
import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from app.extensions.ad_content.schemas import AdImageResponse


DEFAULT_CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
DEFAULT_AESTHETIC_PREDICTOR_NAME = "laion_aesthetic_predictor"


class VisionMetricDependencyError(RuntimeError):
    """Raised when optional vision metric dependencies are not installed."""


class InvalidImagePayloadError(ValueError):
    """Raised when an image payload cannot be decoded for evaluation."""


class InvalidAestheticPredictorError(ValueError):
    """Raised when aesthetic predictor weights are missing or invalid."""


ClipScoreResult = dict[str, str | float]
AestheticScoreResult = dict[str, str | float]


# [Design Intent] CLIP 모델은 로드 비용이 크다. 같은 model_name으로 반복 평가할 때
# 매번 다시 로드하면 평가 시간이 폭증하므로, 프로세스 안에서 최대 2개 모델만 캐싱한다.
@lru_cache(maxsize=2)
def _load_clip_model(model_name: str) -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except ImportError as error:
        raise VisionMetricDependencyError(
            "CLIP Score requires optional image dependencies. "
            'Install them with `pip install -e ".[image]"`.'
        ) from error

    # [Design Intent] 로컬 ComfyUI/FLUX가 GPU VRAM을 거의 전부 사용하므로,
    # 평가용 CLIP은 기본적으로 CPU에서 실행한다. 별도 평가 GPU가 있는 서버에서만
    # BRANDMATE_VISION_METRIC_DEVICE=cuda를 명시해 GPU 평가를 켠다.
    requested_device = os.getenv("BRANDMATE_VISION_METRIC_DEVICE", "cpu").lower()
    if requested_device not in {"cpu", "cuda"}:
        raise VisionMetricDependencyError(
            "BRANDMATE_VISION_METRIC_DEVICE must be either 'cpu' or 'cuda'."
        )
    if requested_device == "cuda" and not torch.cuda.is_available():
        raise VisionMetricDependencyError(
            "BRANDMATE_VISION_METRIC_DEVICE=cuda was set, but CUDA is not available."
        )
    device = requested_device
    processor = CLIPProcessor.from_pretrained(model_name)
    # [Design Intent] torch<2.6 환경에서는 CVE-2025-32434 대응으로 .bin weight 로드가
    # 차단될 수 있다. 공개 CLIP 모델의 safetensors weight를 우선 사용해 torch 업그레이드
    # 없이도 평가 runner가 동작하게 한다.
    model = CLIPModel.from_pretrained(model_name, use_safetensors=True)
    model.to(device)
    model.eval()
    return processor, model, torch


def _image_from_bytes(image_bytes: bytes) -> Any:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise VisionMetricDependencyError(
            "Vision metrics require Pillow. Install optional image dependencies with "
            '`pip install -e ".[image]"`.'
        ) from error

    try:
        image = Image.open(BytesIO(image_bytes))
        return image.convert("RGB")
    except (OSError, UnidentifiedImageError) as error:
        raise InvalidImagePayloadError("Image payload is not a readable image.") from error


def _aesthetic_mlp(torch: Any, input_size: int) -> Any:
    return torch.nn.Sequential(
        torch.nn.Linear(input_size, 1024),
        torch.nn.Dropout(0.2),
        torch.nn.Linear(1024, 128),
        torch.nn.Dropout(0.2),
        torch.nn.Linear(128, 64),
        torch.nn.Dropout(0.1),
        torch.nn.Linear(64, 16),
        torch.nn.Linear(16, 1),
    )


def _load_state_dict(torch: Any, weights_path: Path) -> dict[str, Any]:
    if weights_path.suffix == ".safetensors":
        try:
            from safetensors.torch import load_file
        except ImportError as error:
            raise VisionMetricDependencyError(
                "Loading .safetensors aesthetic weights requires safetensors. "
                'Install optional image dependencies with `pip install -e ".[image]"`.'
            ) from error
        return load_file(str(weights_path))

    state = torch.load(weights_path, map_location="cpu")
    if isinstance(state, dict) and "state_dict" in state and isinstance(state["state_dict"], dict):
        return state["state_dict"]
    if isinstance(state, dict):
        return state
    raise InvalidAestheticPredictorError(
        "Aesthetic predictor weights must be a torch state_dict or safetensors file."
    )


def _validate_aesthetic_weights_path(predictor_weights_path: str | Path) -> Path:
    if isinstance(predictor_weights_path, str) and not predictor_weights_path.strip():
        raise InvalidAestheticPredictorError("predictor_weights_path must not be empty.")

    weights_path = Path(predictor_weights_path)
    if not weights_path.exists():
        raise InvalidAestheticPredictorError(
            f"Aesthetic predictor weights not found: {weights_path}"
        )
    if not weights_path.is_file():
        raise InvalidAestheticPredictorError(
            f"Aesthetic predictor weights path is not a file: {weights_path}"
        )
    return weights_path


@lru_cache(maxsize=2)
def _load_aesthetic_predictor(
    clip_model_name: str,
    predictor_weights_path: str,
) -> tuple[Any, Any]:
    processor, clip_model, torch = _load_clip_model(clip_model_name)
    del processor

    input_size = int(getattr(clip_model.config, "projection_dim", 0))
    if input_size <= 0:
        raise InvalidAestheticPredictorError(
            f"Could not infer CLIP projection dimension for {clip_model_name}."
        )

    # [Design Intent] Aesthetic Score는 CLIP 이미지 임베딩 위에 작은 MLP head를
    # 올려 계산한다. predictor weight는 코드에 포함하지 않고 로컬 파일 경로로 주입한다.
    device = next(clip_model.parameters()).device
    predictor = _aesthetic_mlp(torch, input_size)
    state_dict = _load_state_dict(torch, Path(predictor_weights_path))
    predictor.load_state_dict(state_dict)
    predictor.to(device)
    predictor.eval()
    return predictor, torch


def decode_image_base64(image_base64: str) -> bytes:
    try:
        return base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidImagePayloadError("Image payload is not valid base64.") from error


def calculate_clip_score(
    prompt: str,
    image_bytes: bytes,
    model_name: str = DEFAULT_CLIP_MODEL_NAME,
) -> ClipScoreResult:
    if not prompt.strip():
        raise ValueError("prompt must not be empty.")

    # [Design Intent] 텍스트와 이미지를 같은 CLIP 입력 형식으로 변환하고,
    # 모델이 올라간 CPU/GPU 장치와 입력 tensor 장치를 맞춘다.
    processor, model, torch = _load_clip_model(model_name)
    image = _image_from_bytes(image_bytes)
    # [Design Intent] CLIP text encoder는 보통 77 token 제한이 있다. 이미지 생성용
    # 프롬프트는 수백 token까지 길어질 수 있으므로, 평가에서는 모델 한계에 맞춰 잘라낸다.
    inputs = processor(
        text=[prompt],
        images=[image],
        return_tensors="pt",
        padding=True,
        truncation=True,
    )
    device = next(model.parameters()).device
    inputs = {key: value.to(device) for key, value in inputs.items()}

    with torch.no_grad():
        outputs = model(
            input_ids=inputs["input_ids"],
            attention_mask=inputs.get("attention_mask"),
            pixel_values=inputs["pixel_values"],
        )
        # [Design Intent] transformers 버전에 따라 get_text_features()의 반환 타입이
        # Tensor가 아닐 수 있다. CLIPModel forward의 projected embedding을 사용하면
        # text/image embedding 타입이 안정적으로 맞아 cosine similarity 계산이 깨지지 않는다.
        text_features = outputs.text_embeds
        image_features = outputs.image_embeds
        text_features = torch.nn.functional.normalize(text_features, dim=-1)
        image_features = torch.nn.functional.normalize(image_features, dim=-1)
        score = (text_features * image_features).sum(dim=-1).item()

    return {
        "metric": "clip_score",
        "model_name": model_name,
        "score": round(float(score), 6),
    }


def calculate_aesthetic_score(
    image_bytes: bytes,
    predictor_weights_path: str | Path,
    clip_model_name: str = DEFAULT_CLIP_MODEL_NAME,
) -> AestheticScoreResult:
    weights_path = _validate_aesthetic_weights_path(predictor_weights_path)

    processor, clip_model, torch = _load_clip_model(clip_model_name)
    predictor, _ = _load_aesthetic_predictor(clip_model_name, str(weights_path))
    image = _image_from_bytes(image_bytes)
    inputs = processor(images=[image], return_tensors="pt")
    device = next(clip_model.parameters()).device
    inputs = {key: value.to(device) for key, value in inputs.items()}

    with torch.no_grad():
        image_features = clip_model.get_image_features(pixel_values=inputs["pixel_values"])
        image_features = torch.nn.functional.normalize(image_features, dim=-1)
        score = predictor(image_features).squeeze().item()

    return {
        "metric": "aesthetic_score",
        "model_name": DEFAULT_AESTHETIC_PREDICTOR_NAME,
        "clip_model_name": clip_model_name,
        "score": round(float(score), 6),
    }


def calculate_clip_score_from_response(
    image: AdImageResponse,
    model_name: str = DEFAULT_CLIP_MODEL_NAME,
) -> ClipScoreResult:
    return calculate_clip_score(
        prompt=image.prompt,
        image_bytes=decode_image_base64(image.image_base64),
        model_name=model_name,
    )


def calculate_aesthetic_score_from_response(
    image: AdImageResponse,
    predictor_weights_path: str | Path,
    clip_model_name: str = DEFAULT_CLIP_MODEL_NAME,
) -> AestheticScoreResult:
    return calculate_aesthetic_score(
        image_bytes=decode_image_base64(image.image_base64),
        predictor_weights_path=predictor_weights_path,
        clip_model_name=clip_model_name,
    )
