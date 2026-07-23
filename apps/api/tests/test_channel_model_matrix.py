from argparse import Namespace

from app.extensions.ad_content.schemas import ImageModel, VisionModel
from app.modules.ad_copy.schemas import AdChannel, AdModel
from scripts.run_channel_model_matrix import build_matrix


def matrix_args(**overrides) -> Namespace:
    values = {
        "copy_model": None,
        "vision_model": None,
        "image_model": None,
        "channel": None,
        "max_runs": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_default_matrix_crosses_local_models_by_channel() -> None:
    cases = build_matrix(matrix_args())

    instagram = [case for case in cases if case["channel"] == AdChannel.INSTAGRAM]
    naver_blog = [case for case in cases if case["channel"] == AdChannel.NAVER_BLOG]
    assert len(instagram) == 36
    assert len(naver_blog) == 12
    assert len(cases) == 48


def test_filtered_matrix_does_not_cross_image_models_for_naver_blog() -> None:
    cases = build_matrix(
        matrix_args(
            copy_model=[AdModel.LOCAL_QWEN_2_5_7B.value],
            vision_model=[VisionModel.LOCAL_QWEN_3_VL_4B.value],
            image_model=[ImageModel.SDXL_BASE.value, ImageModel.FLUX_SCHNELL.value],
            channel=[AdChannel.INSTAGRAM.value, AdChannel.NAVER_BLOG.value],
        )
    )

    assert len(cases) == 3
    assert sum(case["channel"] == AdChannel.INSTAGRAM for case in cases) == 2
    assert sum(case["channel"] == AdChannel.NAVER_BLOG for case in cases) == 1


def test_matrix_max_runs_limits_execution_plan() -> None:
    assert len(build_matrix(matrix_args(max_runs=5))) == 5
