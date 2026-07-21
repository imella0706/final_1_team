from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class BackgroundGenerationError(RuntimeError):
    """Raised when the configured text-to-image background generator fails."""


class BackgroundGenerator:
    """Generate an empty advertising background with FLUX.1 Schnell or Sana 1.6B."""

    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("enabled", False):
            raise ValueError("models.background_generator.enabled must be true")
        self.provider = str(config.get("provider", "sana-1.6b")).lower()
        providers = config.get("providers", {})
        provider_config = providers.get(self.provider, {}) if isinstance(providers, dict) else {}
        merged = {**config, **provider_config}
        defaults = {
            "flux-schnell": ("black-forest-labs/FLUX.1-schnell", "models/flux-schnell", 4, 0.0),
            "sana-1.6b": ("Efficient-Large-Model/Sana_1600M_1024px_BF16_diffusers", "models/sana-1.6b", 20, 5.0),
        }
        if self.provider not in defaults:
            raise ValueError("background_generator.provider must be 'flux-schnell' or 'sana-1.6b'")
        default_model, default_cache, default_steps, default_guidance = defaults[self.provider]
        self.model_id = str(merged.get("model_id", default_model))
        self.cache_dir = Path(str(merged.get("cache_dir", default_cache)))
        self.device = str(merged.get("device", "auto"))
        self.steps = int(merged.get("steps", default_steps))
        self.guidance_scale = float(merged.get("guidance_scale", default_guidance))
        self.seed = merged.get("seed")
        self._pipeline: Any | None = None
        self._torch: Any | None = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            import torch
            from diffusers import FluxPipeline, SanaPipeline
        except ImportError as exc:
            raise BackgroundGenerationError(
                "배경 생성에는 diffusers, transformers, accelerate, torch가 필요합니다. "
                "requirements-local.txt 또는 requirements-colab.txt를 설치하세요."
            ) from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        device_name = "cuda" if self.device == "auto" and torch.cuda.is_available() else self.device
        if device_name == "auto":
            device_name = "cpu"
        local_index = self.cache_dir / "model_index.json"
        model_source = str(self.cache_dir) if local_index.is_file() else self.model_id
        try:
            if self.provider == "flux-schnell":
                dtype = torch.bfloat16 if device_name == "cuda" else torch.float32
                self._pipeline = FluxPipeline.from_pretrained(
                    model_source,
                    torch_dtype=dtype,
                    cache_dir=str(self.cache_dir),
                    local_files_only=local_index.is_file(),
                )
                if device_name == "cuda":
                    self._pipeline.enable_model_cpu_offload()
                else:
                    self._pipeline.to(device_name)
            else:
                # Sana 공식 Diffusers 예제처럼 VAE는 float32로 두고, CUDA에서 텍스트 인코더와
                # 변환기만 bfloat16으로 옮긴다.
                self._pipeline = SanaPipeline.from_pretrained(
                    model_source,
                    torch_dtype=torch.float32,
                    variant="bf16",
                    cache_dir=str(self.cache_dir),
                    local_files_only=local_index.is_file(),
                )
                self._pipeline.to(device_name)
                if device_name == "cuda":
                    self._pipeline.text_encoder.to(torch.bfloat16)
                    self._pipeline.transformer = self._pipeline.transformer.to(torch.bfloat16)
        except Exception as exc:
            raise BackgroundGenerationError(
                f"{self.provider} 배경 생성 모델을 불러오지 못했습니다: {self.model_id}"
            ) from exc
        self._torch = torch

    def generate(
        self, prompt: str, width: int, height: int, *, seed: int | None = None
    ) -> np.ndarray:
        self._load()
        assert self._pipeline is not None and self._torch is not None
        width, height = max(64, width - width % 16), max(64, height - height % 16)
        generator = None
        active_seed = self.seed if seed is None else seed
        if active_seed is not None:
            generator = self._torch.Generator(device="cpu").manual_seed(int(active_seed))
        call_args: dict[str, Any] = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "generator": generator,
        }
        if self.provider == "flux-schnell":
            call_args["max_sequence_length"] = 256
        try:
            result = self._pipeline(**call_args).images[0]
        except Exception as exc:
            raise BackgroundGenerationError(f"{self.provider} 배경 생성에 실패했습니다.") from exc
        return cv2.cvtColor(np.asarray(result), cv2.COLOR_RGB2BGR)


# 기존 호출부와의 호환성을 유지한다.
FluxBackgroundGenerator = BackgroundGenerator
