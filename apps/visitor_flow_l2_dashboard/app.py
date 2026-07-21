#!/usr/bin/env python3
"""Render L2 visitor-flow aggregation artifacts as a Streamlit dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# [Design Intent] L2-2는 YOLO를 다시 실행하지 않는다. L2-1에서 생성한
# event/summary artifact만 읽어서 시간대별 관측량과 화면 grid 관측 분포를 검증한다.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = (
    REPO_ROOT / "outputs" / "visitor_flow_mvp" / "c0241_20210802_l2_1"
)

REQUIRED_FILES = {
    "analysis": "analysis.json",
    "dashboard_summary": "dashboard_summary.csv",
    "events": "events.parquet",
    "summary": "summary.parquet",
}

PREVIEW_EXTENSIONS = {".webm", ".mp4"}
ALL_TIME_BUCKET = "__all_time_buckets__"
ROW_LABELS = {
    0: "상단",
    1: "중상단",
    2: "중하단",
    3: "하단",
}
MARKETING_SIGNAL_LABELS = {
    "morning_promotion_candidate": "아침 판촉 후보",
    "storefront_visibility_candidate": "점심/오후 노출 후보",
    "evening_takeout_or_signage_candidate": "저녁 테이크아웃 후보",
}


def resolve_results_dir(path_text: str) -> Path:
    """Resolve an absolute path or a path relative to the repository root."""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def validate_results_dir(results_dir: Path) -> list[Path]:
    """Return required L2-1 artifacts that are missing."""
    return [
        results_dir / filename
        for filename in REQUIRED_FILES.values()
        if not (results_dir / filename).is_file()
    ]


def load_l2_artifacts(
    results_dir: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load L2-1 analysis metadata and aggregation tables."""
    analysis = json.loads(
        (results_dir / REQUIRED_FILES["analysis"]).read_text(encoding="utf-8")
    )
    dashboard_summary = pd.read_csv(results_dir / REQUIRED_FILES["dashboard_summary"])
    summary = pd.read_parquet(results_dir / REQUIRED_FILES["summary"])
    events = pd.read_parquet(results_dir / REQUIRED_FILES["events"])
    return analysis, dashboard_summary, summary, events


def resolve_repo_path(path_text: str) -> Path:
    """Resolve an artifact metadata path relative to the repository root."""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def source_video_paths(analysis: dict[str, Any]) -> list[Path]:
    sample_dir = resolve_repo_path(str(analysis.get("sample_dir", "")))
    return sorted((sample_dir / "videos").glob("*.mp4"))


def preview_video_by_source_stem(results_dir: Path) -> dict[str, Path]:
    preview_dir = results_dir / "preview_videos"
    previews = [
        path
        for path in preview_dir.glob("*")
        if (
            path.is_file()
            and path.suffix.lower() in PREVIEW_EXTENSIONS
            and "_yolo_conf_" in path.stem
        )
    ]
    mapping: dict[str, Path] = {}
    for preview in sorted(previews):
        source_stem = preview.stem.split("_yolo_conf_")[0]
        mapping[source_stem] = preview
    return mapping


def format_zone_for_owner(zone_id: str) -> str:
    """Convert an internal grid id like r0_c3 to owner-facing Korean text."""
    try:
        row_text, col_text = zone_id.split("_")
        row = int(row_text.removeprefix("r"))
        col = int(col_text.removeprefix("c"))
    except (AttributeError, ValueError):
        return zone_id

    row_label = ROW_LABELS.get(row, f"{row + 1}번째 줄")
    return f"{row_label} · 왼쪽에서 {col + 1}번째 구역"


def format_marketing_signal(signal: str) -> str:
    return MARKETING_SIGNAL_LABELS.get(signal, signal)


def render_video_validation(
    analysis: dict[str, Any],
    results_dir: Path,
) -> None:
    st.subheader("2. 실제 영상에서 구역 기준 확인")
    st.caption(
        "노란 선으로 나뉜 24칸이 아래 히트맵의 24칸과 같은 기준입니다. "
        "영상은 탐지 품질과 구역 기준을 눈으로 확인하기 위한 대표 피크 구간입니다."
    )

    source_videos = source_video_paths(analysis)
    if not source_videos:
        st.warning("analysis.json의 sample_dir 아래에서 원본 mp4를 찾지 못했습니다.")
        return

    previews = preview_video_by_source_stem(results_dir)
    preview_source_stems = set(previews)
    selectable_videos = [
        video_path for video_path in source_videos if video_path.stem in preview_source_stems
    ]
    if not selectable_videos:
        selectable_videos = source_videos

    if len(selectable_videos) == 1:
        selected_video = selectable_videos[0]
        st.markdown(f"**대표 검증 clip:** `{selected_video.stem}`")
    else:
        default_index = next(
            (
                index
                for index, video_path in enumerate(selectable_videos)
                if video_path.stem in preview_source_stems
            ),
            0,
        )
        selected_video = st.selectbox(
            "검증 clip 선택",
            options=selectable_videos,
            index=default_index,
            format_func=lambda path: path.stem,
        )

    preview_video = previews.get(selected_video.stem)
    if preview_video is None:
        st.info(
            "선택한 clip의 검증 영상이 아직 없습니다. 아래 명령으로 먼저 생성한 뒤 "
            "대시보드를 새로고침하세요."
        )
        confidence = float(analysis.get("confidence_threshold", 0.50))
        grid = analysis.get("grid", {})
        model_path = str(analysis.get("model", "/path/to/yolo.pt"))
        output_name = (
            f"{selected_video.stem}_yolo_conf_{confidence:.2f}_start_60s".replace(
                ".", "p"
            )
            + ".webm"
        )
        command = (
            "/home/imella0707/miniconda3/envs/ssakda/bin/python "
            "scripts/visitor_flow_l2_render_preview.py \\\n"
            f"  --video {selected_video} \\\n"
            f"  --model {model_path} \\\n"
            "  --device 0 \\\n"
            f"  --imgsz {int(analysis.get('imgsz', 960))} \\\n"
            f"  --conf {confidence:.2f} \\\n"
            f"  --grid-cols {int(grid.get('cols', 6))} \\\n"
            f"  --grid-rows {int(grid.get('rows', 4))} \\\n"
            "  --start-sec 60 \\\n"
            "  --max-seconds 60 \\\n"
            f"  --output {results_dir / 'preview_videos' / output_name}"
        )
        st.code(command, language="bash")
    else:
        st.video(str(preview_video), format="video/webm")
        st.caption(f"검증 영상 artifact: {preview_video}")

    st.info(
        "영상 속 초록 박스는 YOLO가 사람으로 탐지한 위치입니다. "
        "노란 grid id는 내부 검증용이며, 아래 히트맵에서는 같은 위치를 쉬운 구역명으로 바꿔 보여줍니다."
    )


def render_scope_notice() -> None:
    st.warning(
        "이 화면은 CCTV 화면에서 사람이 얼마나 자주 보였는지 비교하는 POC입니다. "
        "표시 값은 정확한 방문객 수가 아니라, 시간대별 붐빔 정도를 보는 보행 관측량입니다. "
        "화면 구역 정보는 원근 보정 전의 화면 좌표 기준 관측 분포입니다."
    )


def render_metric_cards(analysis: dict[str, Any]) -> None:
    first, second, third, fourth = st.columns(4)
    peak_bucket = str(analysis.get("peak_time_bucket", ""))
    top_zone_id = str(analysis.get("top_zone_id", "-"))
    first.metric("가장 붐빈 시간대", peak_bucket[11:16] if len(peak_bucket) >= 16 else "-")
    second.metric(
        "그 시간대 보행 관측",
        f"{int(analysis.get('peak_time_bucket_observations', 0))}건",
    )
    third.metric("화면 기준 최다 관측 구역", format_zone_for_owner(top_zone_id))
    fourth.metric("분석한 CCTV 영상", f"{int(analysis['clip_count'])}개")

    st.info(
        "보행 관측은 CCTV 화면에서 사람으로 탐지된 횟수입니다. "
        "같은 사람이 여러 장면에 보이면 여러 번 잡힐 수 있으므로, 실제 방문객 수로 해석하면 안 됩니다. "
        "최다 관측 구역은 실제 지면의 가장 붐비는 장소가 아니라 화면 기준으로 사람이 많이 잡힌 칸입니다."
    )

    with st.expander("검증용 세부 지표 보기", expanded=False):
        detail = pd.DataFrame(
            [
                {
                    "항목": "sampled frame",
                    "값": f"{int(analysis['sampled_frames'])}장",
                    "의미": "분석을 위해 일정 간격으로 뽑아 확인한 장면 수",
                },
                {
                    "항목": "bbox observation",
                    "값": f"{int(analysis['person_detection_observations'])}건",
                    "의미": "sampled frame에서 사람 bbox가 잡힌 총 횟수",
                },
                {
                    "항목": "confidence",
                    "값": f"{float(analysis['confidence_threshold']):.2f}",
                    "의미": "YOLO가 사람이라고 판단한 결과를 남기는 최소 신뢰도 기준",
                },
                {
                    "항목": "top zone",
                    "값": top_zone_id,
                    "의미": "내부 grid id. 고객 화면에서는 위치 설명으로 변환해 표시",
                },
                {
                    "항목": "top zone observation",
                    "값": f"{int(analysis.get('top_zone_observations', 0))}건",
                    "의미": "단일 화면 구역에서 가장 많이 잡힌 관측량",
                },
            ]
        )
        st.dataframe(detail, hide_index=True, width="stretch")


def render_time_trend(dashboard_summary: pd.DataFrame) -> None:
    st.subheader("1. 시간대별 보행 관측량")
    chart = dashboard_summary.copy()
    chart["time_label"] = pd.to_datetime(chart["time_bucket"]).dt.strftime("%H:%M")
    chart = chart.set_index("time_label")[["total_person_detection_observations"]]
    st.bar_chart(chart, height=320)

    display = dashboard_summary.copy()
    display["time_bucket"] = pd.to_datetime(display["time_bucket"]).dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    display["top_zone_label"] = display["top_zone_id"].map(format_zone_for_owner)
    display["marketing_signal_label"] = display["marketing_signal"].map(
        format_marketing_signal
    )
    st.dataframe(
        display[
            [
                "time_bucket",
                "total_person_detection_observations",
                "marketing_signal_label",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "time_bucket": "시간대",
            "total_person_detection_observations": "보행 관측량",
            "marketing_signal_label": "시간대 해석 후보",
        },
    )
    with st.expander("검증용 시간대별 화면 구역 보기", expanded=False):
        st.dataframe(
            display[
                [
                    "time_bucket",
                    "top_zone_label",
                    "top_zone_observations",
                ]
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "time_bucket": "시간대",
                "top_zone_label": "화면 기준 최다 관측 구역",
                "top_zone_observations": "구역 관측량",
            },
        )


def grid_labels(rows: int, cols: int) -> list[str]:
    return [f"r{row}_c{col}" for row in range(rows) for col in range(cols)]


def build_heatmap_table(
    summary: pd.DataFrame,
    selected_time_bucket: str,
    grid_rows: int,
    grid_cols: int,
) -> pd.DataFrame:
    if selected_time_bucket == ALL_TIME_BUCKET:
        selected = (
            summary.groupby("zone_id", as_index=False)["person_detection_observations"]
            .sum()
        )
    else:
        selected = summary.loc[summary["time_bucket"] == selected_time_bucket]
    counts = {
        zone_id: 0
        for zone_id in grid_labels(rows=grid_rows, cols=grid_cols)
    }
    counts.update(
        selected.set_index("zone_id")["person_detection_observations"]
        .astype(int)
        .to_dict()
    )
    matrix = [
        [counts[f"r{row}_c{col}"] for col in range(grid_cols)]
        for row in range(grid_rows)
    ]
    return pd.DataFrame(
        matrix,
        index=[ROW_LABELS.get(row, f"{row + 1}번째 줄") for row in range(grid_rows)],
        columns=[f"왼쪽 {col + 1}" for col in range(grid_cols)],
    )


def render_grid_heatmap(
    analysis: dict[str, Any],
    summary: pd.DataFrame,
    dashboard_summary: pd.DataFrame,
) -> None:
    st.subheader("3. 화면 구역별 보행 관측 분포")
    st.caption(
        "화면 기준 · 원근 미보정 · 실제 지면 밀집도 아님"
    )
    st.info(
        "아래 24칸은 검증 영상에 보이는 노란 6x4 grid와 같은 기준입니다. "
        "각 칸의 숫자는 선택한 시간대에 그 화면 구역에서 사람이 보인 관측량이고, "
        "색이 연하면 적게 보인 구역, 빨갛게 진하면 자주 보인 구역입니다. "
        "화면 상단의 먼 보행로는 원근 때문에 좁은 구역에 압축되어 보일 수 있으므로, "
        "이 표를 입간판 설치 위치나 실제 면적당 밀집도로 해석하면 안 됩니다."
    )

    time_bucket_options = sorted(
        str(value) for value in dashboard_summary["time_bucket"].unique()
    )
    time_options = [ALL_TIME_BUCKET] + time_bucket_options
    selected_time = st.selectbox(
        "확인할 시간대",
        options=time_options,
        index=0,
        format_func=lambda value: (
            "전체 시간대"
            if value == ALL_TIME_BUCKET
            else pd.to_datetime(value).strftime("%H:%M")
        ),
    )
    st.caption(
        "시간대 목록은 임의로 고른 시간이 아니라 AIHub C0241 폴더에 실제로 있는 "
        "8개 영상의 시작 시각을 1시간 단위로 묶은 결과입니다. "
        "예를 들어 17시는 17:09와 17:51 두 clip이 합쳐진 값입니다."
    )

    grid = analysis.get("grid", {})
    grid_cols = int(grid.get("cols", 6))
    grid_rows = int(grid.get("rows", 4))
    heatmap = build_heatmap_table(
        summary=summary,
        selected_time_bucket=selected_time,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
    )

    st.dataframe(
        heatmap.style.background_gradient(axis=None, cmap="YlOrRd"),
        width="stretch",
    )
    st.caption(
        "색상 범례: 연노랑 = 적음, 주황 = 중간, 진한 빨강 = 많음. "
        "빨간색은 해당 화면 칸에서 탐지된 횟수가 상대적으로 많다는 뜻입니다."
    )

    zone_rows = (
        summary.groupby("zone_id", as_index=False)
        .agg(
            person_detection_observations=(
                "person_detection_observations",
                "sum",
            ),
            density_score=("density_score", "max"),
            hotspot_rank=("hotspot_rank", "min"),
            marketing_signal=("marketing_signal", "first"),
        )
        if selected_time == ALL_TIME_BUCKET
        else summary.loc[summary["time_bucket"] == selected_time]
        .sort_values("person_detection_observations", ascending=False)
        .reset_index(drop=True)
    )
    if selected_time == ALL_TIME_BUCKET:
        max_observations = zone_rows["person_detection_observations"].max()
        if max_observations > 0:
            zone_rows["density_score"] = (
                zone_rows["person_detection_observations"] / max_observations
            )
        zone_rows["hotspot_rank"] = (
            zone_rows["person_detection_observations"]
            .rank(method="min", ascending=False)
            .astype(int)
        )
        zone_rows = zone_rows.sort_values(
            "person_detection_observations",
            ascending=False,
        ).reset_index(drop=True)
    zone_rows["zone_label"] = zone_rows["zone_id"].map(format_zone_for_owner)
    with st.expander("분석 상세 보기: 화면 구역별 관측 순위", expanded=False):
        st.dataframe(
            zone_rows[
                [
                    "zone_label",
                    "person_detection_observations",
                    "density_score",
                    "hotspot_rank",
                ]
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "zone_label": "화면 구역",
                "person_detection_observations": "보행 관측량",
                "density_score": st.column_config.NumberColumn(
                    "상대 관측 강도",
                    format="%.3f",
                ),
                "hotspot_rank": "관측 순위",
            },
        )


def render_marketing_interpretation(dashboard_summary: pd.DataFrame) -> None:
    st.subheader("4. 마케팅 해석 후보")
    peak = dashboard_summary.sort_values(
        "total_person_detection_observations",
        ascending=False,
    ).iloc[0]
    peak_time = pd.to_datetime(peak["time_bucket"]).strftime("%H:%M")
    st.info(
        f"이 데이터에서는 {peak_time}에 보행 관측량이 가장 높았습니다. "
        f"해당 시간대에 CCTV 화면에서 사람이 보인 관측은 총 {int(peak['total_person_detection_observations'])}건입니다. "
        "이 값은 시간대별 붐빔 정도를 비교하기 위한 지표이며, 실제 방문객 수가 아닙니다."
    )
    st.markdown(
        "- 오전 시간대 관측량이 높으면 아침 판촉 후보로 볼 수 있습니다.\n"
        "- 점심/오후 시간대 관측량은 매장 전면 노출이 커질 수 있는 시간대 후보로 볼 수 있습니다.\n"
        "- 늦은 저녁 관측량은 테이크아웃, 배달 픽업 후보 시간대로 볼 수 있습니다.\n"
        "- 입간판 위치 같은 공간 기반 추천은 L2-3 수동 ROI 검증 이후에만 다룹니다.\n"
        "- 현재 마케팅 후보는 규칙 기반 가설이며 매출 상승 검증 결과가 아닙니다."
    )


def render_raw_tables(
    analysis: dict[str, Any],
    events: pd.DataFrame,
    summary: pd.DataFrame,
    results_dir: Path,
) -> None:
    st.subheader("5. 개발/검증용 원본 artifact")
    with st.expander("analysis.json", expanded=False):
        st.json(analysis)
    with st.expander("summary.parquet sample", expanded=False):
        st.dataframe(summary.head(50), hide_index=True, width="stretch")
    with st.expander("events.parquet sample", expanded=False):
        st.dataframe(events.head(50), hide_index=True, width="stretch")
    st.caption(f"현재 읽는 L2-1 결과 폴더: {results_dir}")


def main() -> None:
    st.set_page_config(
        page_title="Visitor Flow L2 Dashboard",
        layout="wide",
    )
    st.title("CCTV 매장 앞 보행 관측 대시보드")
    st.caption("C0241 · 2021-08-02 · L2-1 artifact 기반 L2-2 POC")
    render_scope_notice()

    with st.sidebar:
        st.header("데이터 경로")
        results_path_text = st.text_input(
            "L2-1 결과 폴더",
            value=str(DEFAULT_RESULTS_DIR.relative_to(REPO_ROOT)),
        )
        st.caption("절대 경로 또는 저장소 루트 기준 상대 경로를 사용할 수 있습니다.")

    results_dir = resolve_results_dir(results_path_text)
    missing_files = validate_results_dir(results_dir)
    if missing_files:
        st.error("필수 L2-1 산출물을 찾지 못했습니다.")
        st.code("\n".join(str(path) for path in missing_files))
        st.stop()

    try:
        analysis, dashboard_summary, summary, events = load_l2_artifacts(results_dir)
    except (json.JSONDecodeError, OSError, KeyError, pd.errors.ParserError) as error:
        st.error(f"L2-1 산출물을 읽지 못했습니다: {error}")
        st.stop()

    render_metric_cards(analysis)
    st.divider()
    render_time_trend(dashboard_summary)
    st.divider()
    render_video_validation(analysis, results_dir)
    st.divider()
    render_grid_heatmap(analysis, summary, dashboard_summary)
    st.divider()
    render_marketing_interpretation(dashboard_summary)
    st.divider()
    render_raw_tables(analysis, events, summary, results_dir)


if __name__ == "__main__":
    main()
