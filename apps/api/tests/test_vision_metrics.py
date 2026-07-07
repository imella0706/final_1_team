import base64

import pytest

from app.evaluation.vision_metrics import (
    InvalidAestheticPredictorError,
    InvalidImagePayloadError,
    calculate_aesthetic_score,
    calculate_clip_score,
    decode_image_base64,
)


def test_decode_image_base64_accepts_strict_base64_payload() -> None:
    payload = base64.b64encode(b"image-bytes").decode("ascii")

    assert decode_image_base64(payload) == b"image-bytes"


def test_decode_image_base64_rejects_corrupt_payload() -> None:
    with pytest.raises(InvalidImagePayloadError):
        decode_image_base64("not valid base64")


def test_calculate_clip_score_rejects_empty_prompt_before_model_load() -> None:
    with pytest.raises(ValueError, match="prompt must not be empty"):
        calculate_clip_score(" ", b"unused")


def test_calculate_aesthetic_score_rejects_empty_weight_path_before_model_load() -> None:
    with pytest.raises(InvalidAestheticPredictorError, match="must not be empty"):
        calculate_aesthetic_score(b"unused", "")


def test_calculate_aesthetic_score_rejects_missing_weight_path_before_model_load() -> None:
    with pytest.raises(InvalidAestheticPredictorError, match="weights not found"):
        calculate_aesthetic_score(b"unused", "missing-aesthetic-predictor.pt")
