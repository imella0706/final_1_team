#!/usr/bin/env python3
"""Render L2 visitor-flow aggregation artifacts as a Streamlit dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# [Design Intent] L2-2는 YOLO를 다시 실행하지 않는다. L2-1에서 생성한
# event/summary artifact만 읽어서 시간대별 관측량과 화면 grid 밀도를 검증한다.
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


def render_video_validation(
    analysis: dict[str, Any],
    results_dir: Path,
) -> None:
    st.subheader("0. 연속 영상 탐지 품질 검증")
    st.caption(
        "이 화면은 사람이 YOLO bbox overlay 영상을 직접 확인하는 qualitative QA입니다. "
        "연속 preview frame의 detection 수는 10초 간격으로 집계한 L2-1의 245건에 포함되지 않습니다."
    )

    source_videos = source_video_paths(analysis)
    if not source_videos:
        st.warning("analysis.json의 sample_dir 아래에서 원본 mp4를 찾지 못했습니다.")
        return

    previews = preview_video_by_source_stem(results_dir)
    preview_source_stems = set(previews)
    default_index = next(
        (
            index
            for index, video_path in enumerate(source_videos)
            if video_path.stem in preview_source_stems
        ),
        0,
    )
    selected_video = st.selectbox(
        "확인할 원본 clip",
        options=source_videos,
        index=default_index,
        format_func=lambda path: path.stem,
    )
    preview_video = previews.get(selected_video.stem)

    st.markdown("**YOLO bbox + 6×4 grid 검증 영상**")
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

    st.warning(
        "bbox의 person/confidence/zone은 detection 결과입니다. tracker ID가 아니며, "
        "같은 사람이 다음 frame에 다시 나오면 새로운 observation으로 보입니다. "
        "노란 ROI와 In front of shop 카운트는 L2-3 범위입니다."
    )


def render_scope_notice() -> None:
    st.warning(
        "이 화면은 L2-1 산출물을 검증하는 L2-2 대시보드 POC입니다. "
        "표시되는 값은 frame-level person bbox observation이며, "
        "방문객 수·순방문자 수·정확한 유동인구 수가 아닙니다."
    )


def render_metric_cards(analysis: dict[str, Any]) -> None:
    first, second, third, fourth = st.columns(4)
    first.metric("분석 clip", f"{int(analysis['clip_count'])}개")
    second.metric("sampled frame", f"{int(analysis['sampled_frames'])}장")
    third.metric(
        "bbox observation",
        f"{int(analysis['person_detection_observations'])}건",
    )
    fourth.metric("confidence", f"{float(analysis['confidence_threshold']):.2f}")

    fifth, sixth, seventh, eighth = st.columns(4)
    peak_bucket = str(analysis.get("peak_time_bucket", ""))
    fifth.metric("peak 시간대", peak_bucket[11:16] if len(peak_bucket) >= 16 else "-")
    sixth.metric(
        "peak 관측량",
        f"{int(analysis.get('peak_time_bucket_observations', 0))}건",
    )
    seventh.metric("top zone", str(analysis.get("top_zone_id", "-")))
    eighth.metric(
        "top zone 관측량",
        f"{int(analysis.get('top_zone_observations', 0))}건",
    )

    st.info(
        "시간대 기준 peak는 전체 화면 관측량의 시간대 총합이고, "
        "top zone은 단일 화면 grid 구역의 hotspot입니다. "
        "두 지표는 시간 축과 공간 축이 다르므로 같은 기준으로 해석하면 안 됩니다."
    )


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
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "time_bucket": "시간대",
            "total_person_detection_observations": "총 bbox observation",
            "marketing_signal": "마케팅 후보 신호",
            "top_zone_id": "해당 시간대 top zone",
            "top_zone_observations": "top zone observation",
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
        index=[f"row {row}" for row in range(grid_rows)],
        columns=[f"col {col}" for col in range(grid_cols)],
    )


def render_grid_heatmap(
    analysis: dict[str, Any],
    summary: pd.DataFrame,
    dashboard_summary: pd.DataFrame,
) -> None:
    st.subheader("2. 화면 grid heatmap")
    st.caption(
        "bbox bottom-center point를 화면 기준 6x4 grid에 넣어 집계했습니다. "
        "이 grid는 실제 지면 좌표가 아니라 CCTV 화면상의 상대 구역입니다."
    )

    time_options = sorted(str(value) for value in dashboard_summary["time_bucket"].unique())
    default_time = str(analysis.get("peak_time_bucket") or time_options[0])
    default_index = time_options.index(default_time) if default_time in time_options else 0
    selected_time = st.selectbox(
        "확인할 시간대",
        options=time_options,
        index=default_index,
        format_func=lambda value: pd.to_datetime(value).strftime("%H:%M"),
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
        "색이 진할수록 해당 시간대에 그 화면 구역에서 person bbox observation이 많았다는 뜻입니다."
    )

    zone_rows = (
        summary.loc[summary["time_bucket"] == selected_time]
        .sort_values("person_detection_observations", ascending=False)
        .reset_index(drop=True)
    )
    st.dataframe(
        zone_rows[
            [
                "zone_id",
                "person_detection_observations",
                "density_score",
                "hotspot_rank",
                "marketing_signal",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "zone_id": "zone",
            "person_detection_observations": "bbox observation",
            "density_score": st.column_config.NumberColumn(
                "density score",
                format="%.3f",
            ),
            "hotspot_rank": "hotspot rank",
            "marketing_signal": "마케팅 후보 신호",
        },
    )


def render_marketing_interpretation(dashboard_summary: pd.DataFrame) -> None:
    st.subheader("3. 마케팅 해석 후보")
    peak = dashboard_summary.sort_values(
        "total_person_detection_observations",
        ascending=False,
    ).iloc[0]
    peak_time = pd.to_datetime(peak["time_bucket"]).strftime("%H:%M")
    st.info(
        f"현재 L2-1 artifact 기준 전체 관측량 peak는 {peak_time}이며, "
        f"총 {int(peak['total_person_detection_observations'])}건의 person bbox observation이 잡혔습니다. "
        "이 값은 보행 관측량 후보이지 실제 방문객 수가 아닙니다."
    )
    st.markdown(
        "- 오전 시간대 관측량이 높으면 아침 판촉 후보로 볼 수 있습니다.\n"
        "- 점심/오후 시간대 관측량은 매장 전면 노출 또는 간판 노출 후보로 볼 수 있습니다.\n"
        "- 늦은 저녁 관측량은 테이크아웃, 배달 픽업, 야간 간판 노출 후보로 볼 수 있습니다.\n"
        "- 현재 marketing signal은 rule-based hypothesis이며 매출 상승 검증 결과가 아닙니다."
    )


def render_raw_tables(
    analysis: dict[str, Any],
    events: pd.DataFrame,
    summary: pd.DataFrame,
    results_dir: Path,
) -> None:
    st.subheader("4. 원본 artifact 검증")
    with st.expander("analysis.json"):
        st.json(analysis)
    with st.expander("summary.parquet sample"):
        st.dataframe(summary.head(50), hide_index=True, width="stretch")
    with st.expander("events.parquet sample"):
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
    render_video_validation(analysis, results_dir)
    st.divider()
    render_time_trend(dashboard_summary)
    st.divider()
    render_grid_heatmap(analysis, summary, dashboard_summary)
    st.divider()
    render_marketing_interpretation(dashboard_summary)
    st.divider()
    render_raw_tables(analysis, events, summary, results_dir)


if __name__ == "__main__":
    main()
