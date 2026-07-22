#!/usr/bin/env python3
"""Render the single-clip visitor-flow YOLO evaluation as a Streamlit POC."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# [Design Intent] 이 앱은 단일 영상 L1-3 결과를 설명하는 시연 화면이다.
# 실제 방문객 수, 시간대별 상권 피크, 최종 마케팅 처방으로 확대 해석하지 않는다.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = (
    REPO_ROOT
    / "outputs"
    / "visitor_flow_mvp"
    / "c0241_20210802_yolo_l1_3"
)

REQUIRED_FILES = {
    "summary": "evaluation_summary.json",
    "thresholds": "threshold_metrics.csv",
    "frame_errors": "frame_error_summary.csv",
}


def resolve_results_dir(path_text: str) -> Path:
    """Resolve an absolute path or a path relative to the repository root."""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def validate_results_dir(results_dir: Path) -> list[Path]:
    """Return required result files that are missing."""
    return [
        results_dir / filename
        for filename in REQUIRED_FILES.values()
        if not (results_dir / filename).is_file()
    ]


def load_results(
    results_dir: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Load the small L1-3 evaluation artifacts used by this POC."""
    summary = json.loads(
        (results_dir / REQUIRED_FILES["summary"]).read_text(encoding="utf-8")
    )
    threshold_metrics = pd.read_csv(results_dir / REQUIRED_FILES["thresholds"])
    frame_errors = pd.read_csv(results_dir / REQUIRED_FILES["frame_errors"])
    return summary, threshold_metrics, frame_errors


def find_threshold_row(metrics: pd.DataFrame, threshold: float) -> pd.Series:
    """Find the closest stored threshold row while tolerating float serialization."""
    row_index = (metrics["confidence_threshold"] - threshold).abs().idxmin()
    return metrics.loc[row_index]


def selected_frame_errors(
    frame_errors: pd.DataFrame, threshold: float, sample_every_sec: float
) -> pd.DataFrame:
    """Build a timestamped frame table for one confidence threshold."""
    mask = (frame_errors["confidence_threshold"] - threshold).abs() < 1e-9
    selected = frame_errors.loc[mask].copy().sort_values("frame_index")
    selected["timestamp_sec"] = [
        index * sample_every_sec for index in range(len(selected))
    ]
    return selected


def preview_paths(results_dir: Path) -> list[Path]:
    """Return selected-threshold diagnostic previews in frame order."""
    return sorted((results_dir / "previews_selected_threshold").glob("frame_*.jpg"))


def render_scope_notice() -> None:
    st.warning(
        "이 화면은 C0241 17:09 단일 영상의 L1 POC입니다. "
        "표시되는 수치는 18개 sampled frame의 bbox 관측/평가 결과이며, "
        "실제 방문객 수나 하루 시간대별 유동인구가 아닙니다."
    )


def render_metric_cards(selected: pd.Series) -> None:
    first, second, third, fourth = st.columns(4)
    first.metric("임시 confidence", f"{selected['confidence_threshold']:.2f}")
    second.metric("F1", f"{selected['f1']:.3f}")
    third.metric("Precision", f"{selected['precision']:.3f}")
    fourth.metric("Recall", f"{selected['recall']:.3f}")

    fifth, sixth, seventh, eighth = st.columns(4)
    fifth.metric("샘플 프레임", f"{int(selected['sampled_frames'])}장")
    sixth.metric("AIHub bbox 관측", f"{int(selected['ground_truth_boxes'])}건")
    seventh.metric("YOLO bbox 관측", f"{int(selected['prediction_boxes'])}건")
    eighth.metric("TP / FP / FN", f"{int(selected['tp'])} / {int(selected['fp'])} / {int(selected['fn'])}")
    st.info(
        "AIHub bbox 관측과 YOLO bbox 관측은 사람 수가 아니라 frame-level person bbox observation count입니다. "
        "같은 사람이 여러 sampled frame에 보이면 여러 건으로 반복 집계됩니다. "
        "현재 L1-3 평가는 tracking 없이 bbox detection 성능만 비교하므로, 순방문자 수나 실제 유동인구 수로 해석하면 안 됩니다."
    )


def render_threshold_comparison(metrics: pd.DataFrame, selected_threshold: float) -> None:
    st.subheader("1. Confidence threshold 비교")
    st.write(
        "confidence를 높이면 화면은 깔끔해지지만 사람을 더 많이 놓칠 수 있습니다. "
        "F1은 Precision과 Recall의 균형을 보는 지표라서, L1-3에서는 단일 영상의 임시 threshold 후보를 고르는 기준으로 사용했습니다."
    )
    st.info(
        f"현재 conf={selected_threshold:.2f}는 최종값이 아닙니다. "
        "단일 영상 18개 sampled frame에서 Precision과 Recall 균형이 가장 좋은 임시 후보입니다. "
        "최종 threshold는 L1-5에서 8개 clip으로 확장 평가한 뒤, 유동인구 분석 목적상 Recall 저하를 얼마나 허용할지 정해서 확정합니다."
    )

    chart_data = metrics.set_index("confidence_threshold")[[
        "precision",
        "recall",
        "f1",
    ]]
    st.line_chart(chart_data, height=320)

    display_metrics = metrics[
        [
            "confidence_threshold",
            "tp",
            "fp",
            "fn",
            "precision",
            "recall",
            "f1",
        ]
    ].copy()
    display_metrics["selected"] = display_metrics["confidence_threshold"].map(
        lambda value: "✓" if abs(value - selected_threshold) < 1e-9 else ""
    )
    st.dataframe(
        display_metrics,
        hide_index=True,
        width="stretch",
        column_config={
            "confidence_threshold": st.column_config.NumberColumn(
                "confidence", format="%.2f"
            ),
            "precision": st.column_config.NumberColumn("Precision", format="%.3f"),
            "recall": st.column_config.NumberColumn("Recall", format="%.3f"),
            "f1": st.column_config.NumberColumn("F1", format="%.3f"),
            "selected": "임시 후보",
        },
    )


def render_frame_diagnostics(
    frame_errors: pd.DataFrame,
    thresholds: list[float],
    selected_threshold: float,
    sample_every_sec: float,
) -> None:
    st.subheader("2. 프레임별 bbox 관측과 오류")
    st.caption(
        "AIHub/YOLO bbox 관측은 frame 단위 bbox 총합입니다. "
        "같은 사람이 여러 sampled frame에 나오면 반복 집계되며, unique visitor count가 아닙니다."
    )

    default_index = min(
        range(len(thresholds)), key=lambda index: abs(thresholds[index] - selected_threshold)
    )
    inspected_threshold = st.selectbox(
        "프레임 오류를 확인할 confidence",
        options=thresholds,
        index=default_index,
        format_func=lambda value: f"conf={value:.2f}",
    )
    selected_frames = selected_frame_errors(
        frame_errors, inspected_threshold, sample_every_sec
    )

    observation_chart = selected_frames.set_index("timestamp_sec")[[
        "gt_count",
        "prediction_count",
    ]].rename(
        columns={
            "gt_count": "AIHub bbox 관측",
            "prediction_count": "YOLO bbox 관측",
        }
    )
    st.line_chart(observation_chart, height=300)

    error_chart = selected_frames.set_index("timestamp_sec")[["fp", "fn"]].rename(
        columns={"fp": "reference-label FP", "fn": "FN"}
    )
    st.bar_chart(error_chart, height=260)

    st.dataframe(
        selected_frames[
            [
                "timestamp_sec",
                "frame_index",
                "gt_count",
                "prediction_count",
                "tp",
                "fp",
                "fn",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "timestamp_sec": st.column_config.NumberColumn("영상 시점(초)", format="%.1f"),
            "frame_index": "frame",
            "gt_count": "AIHub bbox 관측",
            "prediction_count": "YOLO bbox 관측",
            "tp": "TP",
            "fp": "reference-label FP",
            "fn": "FN",
        },
    )


def render_preview(results_dir: Path, selected_threshold: float) -> None:
    st.subheader("3. 선택 threshold bbox 감사")
    st.write(
        f"아래 이미지는 평가 코드가 선택한 conf={selected_threshold:.2f}의 진단 preview입니다."
    )

    images = preview_paths(results_dir)
    if not images:
        st.info("preview가 없습니다. 평가 CLI를 `--save-previews`와 함께 다시 실행하세요.")
        return

    frame_by_path = {
        int(path.stem.removeprefix("frame_")): path for path in images
    }
    selected_frame = st.select_slider(
        "확인할 frame",
        options=list(frame_by_path),
        value=list(frame_by_path)[0],
    )
    st.image(
        str(frame_by_path[selected_frame]),
        caption=f"frame={selected_frame} · 파랑=TP 예측 · 초록=matched GT · 빨강=reference-label FP · 주황=FN GT",
        width="stretch",
    )
    st.caption(
        "reference-label FP는 반드시 사물 오탐이라는 뜻이 아닙니다. "
        "AIHub 라벨 누락 또는 IoU 0.50 미만 bbox 불일치도 포함될 수 있습니다."
    )


def render_poc_decision(selected: pd.Series) -> None:
    missed_rate = 1.0 - float(selected["recall"])
    st.subheader("4. 지금 증명된 것과 아직 못 한 것")

    confirmed, pending = st.columns(2)
    with confirmed:
        st.success("현재 POC에서 확인됨")
        st.markdown(
            "- mp4 → sampled frame → person-only YOLO → bbox 평가 파이프라인 동작\n"
            "- threshold별 Precision/Recall/F1 비교 가능\n"
            "- GT/TP/FP/FN preview로 오류 프레임 수동 감사 가능"
        )
    with pending:
        st.error("아직 주장하면 안 됨")
        st.markdown(
            "- 실제 방문객 수와 중복 제거\n"
            "- tracking 기반 순방문자/진입 이벤트 카운팅\n"
            "- 하루 시간대별 피크 비교\n"
            "- 구역 heatmap과 체류/동선\n"
            "- 점포별 운영·마케팅 최종 추천"
        )

    st.info(
        f"선택 threshold에서도 AIHub bbox 기준 약 {missed_rate:.1%}를 놓쳤습니다. "
        "다음 검증은 C0241의 나머지 7개 영상으로 확장하는 L1-5입니다."
    )


def main() -> None:
    st.set_page_config(
        page_title="Visitor Flow YOLO POC",
        page_icon="🚶",
        layout="wide",
    )
    st.title("매장 앞 방문객 흐름 YOLO POC")
    st.caption("C0241 · 2021-08-02 17:09 · 단일 180초 영상 · L1-3 모델 검증")
    render_scope_notice()

    with st.sidebar:
        st.header("데이터 경로")
        results_path_text = st.text_input(
            "L1-3 결과 폴더",
            value=str(DEFAULT_RESULTS_DIR.relative_to(REPO_ROOT)),
        )
        st.caption("절대 경로 또는 저장소 루트 기준 상대 경로를 사용할 수 있습니다.")

    results_dir = resolve_results_dir(results_path_text)
    missing_files = validate_results_dir(results_dir)
    if missing_files:
        st.error("필수 평가 산출물을 찾지 못했습니다.")
        st.code("\n".join(str(path) for path in missing_files))
        st.stop()

    try:
        summary, threshold_metrics, frame_errors = load_results(results_dir)
    except (json.JSONDecodeError, OSError, KeyError, pd.errors.ParserError) as error:
        st.error(f"평가 산출물을 읽지 못했습니다: {error}")
        st.stop()

    selected_threshold = float(summary["selected_threshold"])
    sample_every_sec = float(summary["sample_every_sec"])
    selected = find_threshold_row(threshold_metrics, selected_threshold)
    thresholds = sorted(
        float(value) for value in threshold_metrics["confidence_threshold"].unique()
    )

    render_metric_cards(selected)
    st.divider()
    render_threshold_comparison(threshold_metrics, selected_threshold)
    st.divider()
    render_frame_diagnostics(
        frame_errors,
        thresholds,
        selected_threshold,
        sample_every_sec,
    )
    st.divider()
    render_preview(results_dir, selected_threshold)
    st.divider()
    render_poc_decision(selected)

    with st.expander("실험 설정과 원본 경로"):
        st.json(summary)
        st.caption(f"현재 읽는 결과 폴더: {results_dir}")


if __name__ == "__main__":
    main()
