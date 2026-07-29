"""Download pipeline model weights into the local models directory.

Run with: python -m scripts.download_models --all
"""
from __future__ import annotations

import argparse
import os
import shutil
import urllib.request
from pathlib import Path


MODEL_URLS = {
    "yolo": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt",
    "sam2": "https://github.com/ultralytics/assets/releases/download/v8.3.0/sam2.1_s.pt",
    "big-lama": "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download model weights for local use")
    parser.add_argument(
        "--models",
        nargs="+",
        choices=[
            *MODEL_URLS,
            "openclip",
            "birefnet",
            "flux",
            "sana",
            "grounding-dino",
            "hq-sam",
        ],
    )
    parser.add_argument("--all", action="store_true", help="download all configured models")
    parser.add_argument("--model-dir", default="models")
    return parser.parse_args()


def download(url: str, destination: Path) -> None:
    if destination.is_file() and destination.stat().st_size > 0:
        print(f"[SKIP] {destination}")
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"[DOWNLOAD] {destination.name}")
    try:
        with urllib.request.urlopen(url) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def download_openclip(model_dir: Path) -> None:
    try:
        import open_clip
    except ImportError as exc:
        raise RuntimeError("Install open_clip_torch before downloading OpenCLIP") from exc
    cache_dir = model_dir / "openclip"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))
    print("[DOWNLOAD] OpenCLIP ViT-B-32 (laion2b_s34b_b79k)")
    open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k", cache_dir=str(cache_dir)
    )


def download_huggingface_model(repo_id: str, destination: Path, completion_file: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Install huggingface_hub before downloading this model") from exc
    if (destination / completion_file).is_file():
        print(f"[SKIP] {destination}")
        return
    print(f"[DOWNLOAD] {repo_id}")
    try:
        snapshot_download(repo_id=repo_id, local_dir=str(destination))
    except Exception as exc:
        if repo_id == "black-forest-labs/FLUX.1-schnell":
            raise RuntimeError(
                "FLUX.1 Schnell은 Hugging Face gated 모델입니다. "
                "모델 페이지에서 접근 조건에 동의한 뒤, 읽기 권한 HF 토큰을 "
                "HF_TOKEN 환경 변수로 설정하고 다시 실행하세요."
            ) from exc
        raise


def main() -> int:
    args = parse_args()
    selected = (
        list(MODEL_URLS) + ["openclip", "sana", "grounding-dino", "hq-sam"]
        if args.all
        else (args.models or [])
    )
    if not selected:
        raise SystemExit("Choose --all or one or more values with --models")
    model_dir = Path(args.model_dir)
    for name in selected:
        if name == "openclip":
            download_openclip(model_dir)
        elif name == "birefnet":
            download_huggingface_model(
                "ZhengPeng7/BiRefNet_HR", model_dir / "birefnet", "config.json"
            )
        elif name == "flux":
            download_huggingface_model(
                "black-forest-labs/FLUX.1-schnell", model_dir / "flux-schnell", "model_index.json"
            )
        elif name == "sana":
            download_huggingface_model(
                "Efficient-Large-Model/Sana_1600M_1024px_BF16_diffusers",
                model_dir / "sana-1.6b",
                "model_index.json",
            )
        elif name == "grounding-dino":
            download_huggingface_model(
                "IDEA-Research/grounding-dino-tiny",
                model_dir / "grounding-dino",
                "config.json",
            )
        elif name == "hq-sam":
            download_huggingface_model(
                "syscv-community/sam-hq-vit-base",
                model_dir / "hq-sam",
                "config.json",
            )
        else:
            download(MODEL_URLS[name], model_dir / Path(MODEL_URLS[name]).name)
    print("[DONE] Model download completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
