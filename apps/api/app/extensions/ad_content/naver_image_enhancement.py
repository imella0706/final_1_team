"""네이버 블로그 음식 사진을 같은 저장소 안의 배경 교체 파이프라인으로 처리한다."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import settings
from app.extensions.ad_content.naver_background_prompts import build_naver_background_prompt
from app.extensions.ad_content.schemas import AdImageResponse

if TYPE_CHECKING:
    from app.extensions.ad_content.schemas import BlogImageInput
    from app.modules.ad_copy.schemas import AdCopyRequest


class NaverImageEnhancementError(RuntimeError):
    """파이프라인 실행 또는 결과 검증 실패."""


class NaverImageEnhancementNotConfiguredError(NaverImageEnhancementError):
    """선택 기능이 비활성화됐거나 실행 환경이 준비되지 않음."""


_API_ROOT = Path(__file__).resolve().parents[3]
_MEDIA_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_TONE_TO_BACKGROUND_MOOD = {
    "emotional": "soft, emotional and memorable",
    "witty": "lively, playful and approachable",
    "friendly": "friendly, relaxed and approachable",
    "warm": "warm, comfortable and welcoming",
    "playful": "bright, playful and energetic",
    "professional": "clean, polished and trustworthy",
    "premium": "refined, premium and calm",
}


def _pipeline_root() -> Path:
    configured = Path(settings.naver_image_cleanup_root)
    return configured if configured.is_absolute() else _API_ROOT / configured


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:") or "," not in data_url:
        raise NaverImageEnhancementError("네이버 업로드 이미지가 올바른 Data URL 형식이 아닙니다.")
    header, encoded = data_url.split(",", 1)
    media_type = header.split(";", 1)[0].removeprefix("data:").lower()
    suffix = _MEDIA_SUFFIX.get(media_type)
    if suffix is None:
        raise NaverImageEnhancementError("JPG, PNG, WEBP 형식의 음식 사진만 보정할 수 있습니다.")
    try:
        return base64.b64decode(encoded, validate=True), suffix
    except ValueError as error:
        raise NaverImageEnhancementError("업로드 이미지의 Base64 데이터를 해석할 수 없습니다.") from error


def _configured_python(root: Path) -> str:
    value = settings.naver_image_cleanup_python
    if value:
        executable = Path(value)
        if not executable.is_file():
            raise NaverImageEnhancementNotConfiguredError(
                f"네이버 이미지 보정 Python 실행 파일을 찾을 수 없습니다: {executable}"
            )
        return str(executable)
    # API와 파이프라인 의존성을 같은 Python 환경에 설치한 경우의 기본값이다.
    return sys.executable


def _requested_background_mood(copy_request: "AdCopyRequest") -> str:
    """직접 입력한 desired_mood를 우선하고, 없으면 광고 톤을 배경 분위기로 변환한다."""
    explicit_mood = str(getattr(copy_request, "desired_mood", "") or "").strip()
    if explicit_mood:
        return explicit_mood
    tone = str(getattr(copy_request, "tone", "warm")).strip().lower()
    return _TONE_TO_BACKGROUND_MOOD.get(tone, "warm, welcoming and natural")


def enhance_naver_blog_image(
    copy_request: "AdCopyRequest", uploaded: "BlogImageInput"
) -> AdImageResponse:
    """업로드 이미지를 로컬 파이프라인으로 처리하고 API 응답 형식으로 반환한다."""
    if not settings.naver_image_enhancement_enabled:
        raise NaverImageEnhancementNotConfiguredError(
            "네이버 이미지 보정 기능이 비활성화되어 있습니다. "
            "BRANDMATE_NAVER_IMAGE_ENHANCEMENT_ENABLED=true로 설정하세요."
        )

    root = _pipeline_root()
    runner = root / "scripts" / "run_background_replacement.py"
    if not root.is_dir() or not runner.is_file():
        raise NaverImageEnhancementNotConfiguredError(
            f"내장 음식 사진 파이프라인을 찾을 수 없습니다: {root}"
        )

    image_bytes, suffix = _decode_data_url(uploaded.data_url)
    request_id = uuid.uuid4().hex
    input_dir = root / "data" / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / f"naver_{request_id}{suffix}"
    metadata_path = input_dir / f"naver_{request_id}_metadata.json"
    output_path = root / "data" / "output" / f"naver_{request_id}_background_replaced.jpg"
    report_path = root / "data" / "reports" / f"naver_{request_id}_background_replacement_report.json"
    prompt = build_naver_background_prompt(copy_request.business_type)
    metadata = {
        "business_type": prompt.business_type,
        "food_category": prompt.business_type,
        # 업종 분위기 프롬프트는 보존하고, 파이프라인의 EfficientNet-B0가
        # top/45 카메라 제약과 전경 배치 영역을 추가한다.
        "background_prompt_base": prompt.prompt,
        "desired_mood": _requested_background_mood(copy_request),
        "camera_angle_manual": False,
        "light_direction": "upper_left" if prompt.template == "pub" else "left",
    }
    input_path.write_bytes(image_bytes)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    started = time.perf_counter()
    command = [
        _configured_python(root),
        "-m",
        "scripts.run_background_replacement",
        "--input",
        str(input_path.relative_to(root)),
        "--metadata",
        str(metadata_path.relative_to(root)),
        "--enable-matting",
        "--enable-background-generator",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=settings.naver_image_cleanup_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise NaverImageEnhancementError("네이버 이미지 보정 시간이 제한을 초과했습니다.") from error
    finally:
        metadata_path.unlink(missing_ok=True)
        input_path.unlink(missing_ok=True)

    if completed.returncode != 0 or not output_path.is_file():
        detail = (completed.stderr or completed.stdout).strip().splitlines()[-1:]
        raise NaverImageEnhancementError(
            "음식 사진 배경 교체에 실패했습니다" + (f": {detail[0]}" if detail else "")
        )

    selected_prompt = prompt.prompt
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            selected_prompt = str(
                report.get("stages", {}).get("step_7_background_prompt", {}).get("prompt", selected_prompt)
            )
        except (OSError, ValueError, TypeError):
            # 합성 자체는 성공했으므로 보고서 표시 오류 때문에 API 응답을 실패시키지 않는다.
            pass

    return AdImageResponse(
        model="food-image-cleanup-pipeline",
        prompt=selected_prompt,
        image_base64=base64.b64encode(output_path.read_bytes()).decode("ascii"),
        media_type="image/jpeg",
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
