"""Send one local image to every configured Ollama Vision model."""

import argparse
import asyncio
import base64
import mimetypes
import sys
import time
from pathlib import Path

from app.extensions.ad_content.schemas import VisionModel
from app.extensions.ad_content.vision_service import request_vision_completion


LOCAL_VISION_MODELS = (
    VisionModel.LOCAL_QWEN_3_VL_2B,
    VisionModel.LOCAL_QWEN_3_VL_4B,
    VisionModel.LOCAL_QWEN_2_5_VL_7B,
    VisionModel.LOCAL_QWEN_3_VL_8B,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--prompt",
        default="이 이미지에서 보이는 주요 상품과 시각적 특징을 한국어 두 문장으로 설명하세요.",
    )
    parser.add_argument("--max-tokens", type=int, default=160)
    return parser.parse_args()


def image_data_url(path: Path) -> str:
    image_bytes = path.read_bytes()
    is_supported_image = (
        image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        or image_bytes.startswith(b"\xff\xd8\xff")
        or (image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP")
    )
    if not is_supported_image:
        raise ValueError(f"Not a valid PNG, JPEG, or WebP image: {path}")
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


async def run(args: argparse.Namespace) -> None:
    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    content: list[dict[str, object]] = [
        {"type": "text", "text": args.prompt},
        {"type": "image_url", "image_url": {"url": image_data_url(args.image)}},
    ]
    for model in LOCAL_VISION_MODELS:
        started = time.perf_counter()
        try:
            result, resolved = await request_vision_completion(
                model,
                content,
                max_tokens=args.max_tokens,
            )
            elapsed = time.perf_counter() - started
            print(
                f"\n[{model.value}] {resolved.routed_model} · {elapsed:.1f}s",
                flush=True,
            )
            print(result.strip(), flush=True)
        except Exception as error:  # noqa: BLE001 - smoke test should continue
            elapsed = time.perf_counter() - started
            print(f"\n[{model.value}] FAILED · {elapsed:.1f}s")
            print(f"{type(error).__name__}: {error}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run(parse_args()))
