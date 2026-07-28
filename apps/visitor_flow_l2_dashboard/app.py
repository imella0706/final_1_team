#!/usr/bin/env python3
"""Render L2 visitor-flow and L3-1 manual ROI artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# [Design Intent] 대시보드는 YOLO를 다시 실행하지 않는다. L2 집계와 L3-1 ROI
# artifact를 읽어서 전체 화면과 매장 전면 관측 결과를 함께 검증한다.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = (
    REPO_ROOT / "outputs" / "visitor_flow_mvp" / "c0241_20210802_20210803_l2_4"
)
DEFAULT_ROI_RESULTS_DIR = (
    REPO_ROOT / "outputs" / "visitor_flow_mvp" / "c0241_20210802_20210803_l3_1_roi"
)
DEFAULT_PRIVACY_MEDIA_DIR = (
    REPO_ROOT
    / "outputs"
    / "visitor_flow_mvp"
    / "c0241_20210802_20210803_l3_2_privacy_media"
)
DEFAULT_TRACKING_QA_DIR = (
    REPO_ROOT
    / "outputs"
    / "visitor_flow_mvp"
    / "c0241_20210802_20210803_l3_4_tracking_qa"
)
DEFAULT_CROSSING_RESULTS_DIR = (
    REPO_ROOT
    / "outputs"
    / "visitor_flow_mvp"
    / "c0241_20210802_20210803_l3_5_line_crossing"
)

REQUIRED_FILES = {
    "analysis": "analysis.json",
    "dashboard_summary": "dashboard_summary.csv",
    "events": "events.parquet",
    "frames": "frames.parquet",
    "summary": "summary.parquet",
}

REQUIRED_ROI_FILES = {
    "analysis": "roi_analysis.json",
    "config": "roi_config.json",
    "events": "roi_events.parquet",
    "frames": "roi_frames.parquet",
    "summary": "roi_summary.parquet",
}

REQUIRED_PRIVACY_MEDIA_FILES = {
    "summary": Path("qa") / "masking_qa_summary.json",
    "image": Path("images") / "roi_overlay_preview_masked.jpg",
}
PRIVACY_VIDEO_PATH = Path("media") / "roi_preview_masked.webm"
REQUIRED_TRACKING_QA_FILES = {
    "summary": Path("qa") / "tracking_qa_summary.json",
    "events": Path("tracks") / "track_events.csv",
}
TRACKING_VIDEO_PATH = Path("media") / "tracking_id_qa.webm"

REQUIRED_CROSSING_FILES = {
    "summary": Path("qa") / "crossing_summary.json",
    "events": Path("crossings") / "crossing_events.csv",
}
CROSSING_VIDEO_PATH = Path("media") / "line_crossing_qa.webm"

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
DEFAULT_REPORT_STORE_NAME = "탐앤탐스 C0241 분석 사례"
DEFAULT_REPORT_LOCATION = "매장 앞 보행로와 계단 진입로"
DEFAULT_REPORT_NUMBER = "BM-C0241-20210802-01"


def resolve_results_dir(path_text: str) -> Path:
    """Resolve an absolute path or a path relative to the repository root."""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def validate_results_dir(results_dir: Path) -> list[Path]:
    """Return required L2 artifacts that are missing."""
    return [
        results_dir / filename
        for filename in REQUIRED_FILES.values()
        if not (results_dir / filename).is_file()
    ]


def validate_roi_results_dir(results_dir: Path) -> list[Path]:
    """Return required L3-1 ROI artifacts that are missing."""
    return [
        results_dir / filename
        for filename in REQUIRED_ROI_FILES.values()
        if not (results_dir / filename).is_file()
    ]


def validate_privacy_media_dir(results_dir: Path) -> list[Path]:
    """Return required L3-2 privacy-safe media artifacts that are missing."""
    missing = [
        results_dir / filename
        for filename in REQUIRED_PRIVACY_MEDIA_FILES.values()
        if not (results_dir / filename).is_file()
    ]
    if not (results_dir / PRIVACY_VIDEO_PATH).is_file():
        missing.append(results_dir / PRIVACY_VIDEO_PATH)
    return missing


def validate_tracking_qa_dir(results_dir: Path) -> list[Path]:
    """Return required L3-4 tracking QA artifacts that are missing."""
    missing = [
        results_dir / filename
        for filename in REQUIRED_TRACKING_QA_FILES.values()
        if not (results_dir / filename).is_file()
    ]
    if not (results_dir / TRACKING_VIDEO_PATH).is_file():
        missing.append(results_dir / TRACKING_VIDEO_PATH)
    return missing


def load_l2_artifacts(
    results_dir: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load L2 analysis metadata and aggregation tables."""
    analysis = json.loads(
        (results_dir / REQUIRED_FILES["analysis"]).read_text(encoding="utf-8")
    )
    dashboard_summary = pd.read_csv(results_dir / REQUIRED_FILES["dashboard_summary"])
    summary = pd.read_parquet(results_dir / REQUIRED_FILES["summary"])
    frames = pd.read_parquet(results_dir / REQUIRED_FILES["frames"])
    events = pd.read_parquet(results_dir / REQUIRED_FILES["events"])
    return analysis, dashboard_summary, summary, frames, events


def load_roi_artifacts(
    results_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load deterministic L3-1 ROI metadata and tables."""
    analysis = json.loads(
        (results_dir / REQUIRED_ROI_FILES["analysis"]).read_text(encoding="utf-8")
    )
    config = json.loads(
        (results_dir / REQUIRED_ROI_FILES["config"]).read_text(encoding="utf-8")
    )
    summary = pd.read_parquet(results_dir / REQUIRED_ROI_FILES["summary"])
    frames = pd.read_parquet(results_dir / REQUIRED_ROI_FILES["frames"])
    events = pd.read_parquet(results_dir / REQUIRED_ROI_FILES["events"])
    return analysis, config, summary, frames, events


def load_privacy_media(results_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    """Load L3-2 privacy-safe media metadata and artifact paths."""
    summary_path = results_dir / REQUIRED_PRIVACY_MEDIA_FILES["summary"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    image_path = results_dir / REQUIRED_PRIVACY_MEDIA_FILES["image"]
    video_path = results_dir / PRIVACY_VIDEO_PATH
    return summary, image_path, video_path


def load_tracking_qa(results_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    """Load L3-4 tracking QA metadata and artifact paths."""
    summary_path = results_dir / REQUIRED_TRACKING_QA_FILES["summary"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    events_path = results_dir / REQUIRED_TRACKING_QA_FILES["events"]
    video_path = results_dir / TRACKING_VIDEO_PATH
    return summary, video_path, events_path


def validate_crossing_dir(results_dir: Path) -> list[Path]:
    """Return required L3-5 line crossing artifacts that are missing."""
    missing = [
        results_dir / filename
        for filename in REQUIRED_CROSSING_FILES.values()
        if not (results_dir / filename).is_file()
    ]
    if not (results_dir / CROSSING_VIDEO_PATH).is_file():
        missing.append(results_dir / CROSSING_VIDEO_PATH)
    return missing


def load_crossing_results(results_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    """Load L3-5 line crossing metadata and artifact paths."""
    summary_path = results_dir / REQUIRED_CROSSING_FILES["summary"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    events_path = results_dir / REQUIRED_CROSSING_FILES["events"]
    video_path = results_dir / CROSSING_VIDEO_PATH
    return summary, video_path, events_path


def resolve_repo_path(path_text: str) -> Path:
    """Resolve an artifact metadata path relative to the repository root."""
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def display_path_for_command(path: Path) -> str:
    """Return a repo-relative path when possible for copyable CLI examples."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def source_video_paths(analysis: dict[str, Any]) -> list[Path]:
    source_videos = [
        resolve_repo_path(str(path))
        for path in analysis.get("source_videos", [])
        if str(path)
    ]
    if source_videos:
        return sorted(path for path in source_videos if path.is_file())

    sample_dirs = analysis.get("sample_dirs") or []
    if not sample_dirs and analysis.get("sample_dir"):
        sample_dirs = [analysis["sample_dir"]]
    videos: list[Path] = []
    for sample_dir_text in sample_dirs:
        sample_dir = resolve_repo_path(str(sample_dir_text))
        videos.extend((sample_dir / "videos").rglob("*.mp4"))
    return sorted(videos)


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


def video_format(path: Path) -> str:
    if path.suffix.lower() == ".mp4":
        return "video/mp4"
    return "video/webm"


def format_zone_for_owner(zone_id: str, *, compact: bool = False) -> str:
    """Convert an internal grid id like r0_c3 to owner-facing Korean text."""
    try:
        row_text, col_text = zone_id.split("_")
        row = int(row_text.removeprefix("r"))
        col = int(col_text.removeprefix("c"))
    except (AttributeError, ValueError):
        return zone_id

    row_label = ROW_LABELS.get(row, f"{row + 1}번째 줄")
    if compact:
        return f"{row_label} · 좌측 {col + 1}번"
    return f"{row_label} · 왼쪽에서 {col + 1}번째 구역"


def format_marketing_signal(signal: str) -> str:
    return MARKETING_SIGNAL_LABELS.get(signal, signal)


def format_report_date(date_value: str) -> str:
    """Format an ISO date as a customer-facing Korean report date."""
    timestamp = pd.to_datetime(date_value)
    return timestamp.strftime("%Y.%m.%d")


def build_customer_report_facts(
    analysis: dict[str, Any],
    dashboard_summary: pd.DataFrame,
    roi_analysis: dict[str, Any],
) -> dict[str, Any]:
    """Build deterministic, customer-safe facts from validated L2/L3 artifacts."""
    summary = dashboard_summary.copy()
    summary["timestamp"] = pd.to_datetime(summary["time_bucket"])
    summary["hour"] = summary["timestamp"].dt.strftime("%H:%M")
    summary = summary.sort_values(["timestamp", "date_id"]).reset_index(drop=True)

    peak = summary.sort_values(
        "mean_persons_per_sampled_frame",
        ascending=False,
    ).iloc[0]
    peak_date_id = str(peak["date_id"])
    date_averages = {
        str(item["date_id"]): float(item["mean_persons_per_sampled_frame"])
        for item in analysis.get("date_summary", [])
    }
    peak_date_average = date_averages.get(peak_date_id, 0.0)
    peak_mean = float(peak["mean_persons_per_sampled_frame"])
    peak_to_date_average = peak_mean / peak_date_average if peak_date_average else 0.0

    clip_summaries = analysis.get("clip_summaries", [])
    total_duration_seconds = sum(
        float(clip.get("frame_count", 0)) / float(clip.get("fps", 1))
        for clip in clip_summaries
        if float(clip.get("fps", 0)) > 0
    )
    if total_duration_seconds <= 0:
        total_duration_seconds = (
            float(analysis.get("sampled_frames", 0))
            * float(analysis.get("sample_every_sec", 0))
        )

    dates = sorted(str(date_id) for date_id in summary["date_id"].unique())
    observed_hours = {
        date_id: sorted(
            summary.loc[summary["date_id"] == date_id, "hour"].unique().tolist()
        )
        for date_id in dates
    }
    hour_date_counts = summary.groupby("hour")["date_id"].nunique()
    comparable_hours = sorted(hour_date_counts[hour_date_counts >= 2].index.tolist())
    comparable = summary[summary["hour"].isin(comparable_hours)].copy()

    return {
        "camera_id": str(roi_analysis.get("camera_id", "C0241")),
        "dates": dates,
        "observed_hours": observed_hours,
        "clip_count": int(analysis.get("clip_count", 0)),
        "analysis_minutes": int(round(total_duration_seconds / 60)),
        "analysis_scene_count": int(analysis.get("sampled_frames", 0)),
        "peak_date_id": peak_date_id,
        "peak_hour": str(peak["hour"]),
        "peak_scene_average": peak_mean,
        "peak_date_average": peak_date_average,
        "peak_to_date_average": peak_to_date_average,
        "storefront_share": float(roi_analysis.get("roi_observation_share", 0.0)),
        "storefront_peak_date_id": str(roi_analysis.get("peak_date_id", "")),
        "storefront_peak_hour": pd.to_datetime(
            roi_analysis.get("peak_time_bucket")
        ).strftime("%H:%M"),
        "storefront_peak_scene_average": float(
            roi_analysis.get(
                "peak_mean_roi_observations_per_sampled_frame",
                0.0,
            )
        ),
        "comparable_hours": comparable_hours,
        "comparable_summary": comparable,
    }


def customer_time_chart(summary: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """Create a compact date-by-hour table for customer-facing charts."""
    chart = summary.copy()
    chart["시간대"] = pd.to_datetime(chart["time_bucket"]).dt.strftime("%H시")
    chart["날짜"] = pd.to_datetime(chart["date_id"]).dt.strftime("%m월 %d일")
    return chart.pivot_table(
        index="시간대",
        columns="날짜",
        values=value_column,
        aggfunc="first",
    ).sort_index()


def render_customer_report(
    analysis: dict[str, Any],
    dashboard_summary: pd.DataFrame,
    roi_analysis: dict[str, Any],
    roi_summary: pd.DataFrame,
    masked_image_path: Path,
    *,
    crossing_summary: dict[str, Any] | None = None,
    store_name: str,
    survey_location: str,
    report_number: str,
) -> None:
    """Render the customer report without exposing operator implementation details."""
    facts = build_customer_report_facts(analysis, dashboard_summary, roi_analysis)
    date_labels = [format_report_date(date_id) for date_id in facts["dates"]]
    period_label = " ~ ".join(date_labels)

    st.header("CCTV 관측량 기반 상권분석 보고서")
    st.markdown(f"**{store_name}**")
    st.caption(f"조사 기간 {period_label} · 보고서 번호 {report_number}")

    st.divider()
    st.subheader("1. 조사 개요")
    observed_time_rows = [
        f"{format_report_date(date_id)}: "
        + ", ".join(f"{hour[:2]}시" for hour in facts["observed_hours"][date_id])
        for date_id in facts["dates"]
    ]
    overview = pd.DataFrame(
        [
            {"항목": "조사 대상", "내용": store_name},
            {"항목": "조사 위치", "내용": survey_location},
            {"항목": "조사 기간", "내용": period_label},
            {"항목": "실제 관측 시간대", "내용": " / ".join(observed_time_rows)},
            {
                "항목": "분석 범위",
                "내용": (
                    f"영상 {facts['clip_count']}개 · 총 {facts['analysis_minutes']}분 · "
                    f"분석 장면 {facts['analysis_scene_count']}개"
                ),
            },
            {"항목": "분석 목적", "내용": "시간대별 관측량 변화와 매장 앞 노출 기회 파악"},
        ]
    )
    st.table(overview)

    st.divider()
    st.subheader("2. 핵심 발견")
    first, second, third, fourth = st.columns(4)
    first.metric(
        "가장 높은 관측 시간대",
        f"{format_report_date(facts['peak_date_id'])} {facts['peak_hour']}",
    )
    second.metric(
        "해당 시간대 평균 인원",
        f"{facts['peak_scene_average']:.2f}명",
    )
    third.metric(
        "매장 앞 관측 비중",
        f"{facts['storefront_share'] * 100:.1f}%",
    )
    fourth.metric(
        "분석 범위",
        f"{facts['clip_count']}개 영상 · {facts['analysis_minutes']}분",
    )
    st.markdown(
        f"분석한 영상 표본에서는 **{format_report_date(facts['peak_date_id'])} "
        f"{facts['peak_hour']}**의 관측량이 가장 높았습니다. 해당 시간대에는 "
        f"분석 장면마다 평균 **{facts['peak_scene_average']:.2f}명**이 보였으며, "
        f"같은 날짜 평균의 **{facts['peak_to_date_average']:.2f}배**였습니다."
    )
    st.caption(
        "관측량은 CCTV 화면에서 사람으로 탐지된 횟수이며, 방문자 수나 통행량을 의미하지 않습니다. "
        "해당 시간대 평균 인원은 일정 간격으로 확인한 화면에서 동시에 보인 사람 수의 평균입니다."
    )

    st.divider()
    st.subheader("3. 시간대별 관측량 추이")
    st.bar_chart(
        customer_time_chart(
            dashboard_summary,
            "mean_persons_per_sampled_frame",
        ),
        x_label="시간대",
        y_label="분석 장면당 평균 인원(명)",
        stack=False,
        height=380,
    )
    st.markdown(
        f"가장 강한 신호는 **{facts['peak_hour']}**에 나타났습니다. "
        "이 시간대는 매장 입구의 메뉴 안내, 입간판, 테이크아웃 혜택처럼 "
        "지나가는 사람이 바로 볼 수 있는 안내 요소의 반응을 시험할 "
        "우선 후보입니다. 영상이 제공되지 않은 시간대는 추정하지 않았습니다."
    )

    st.divider()
    st.subheader("4. 매장 앞 관측구역 분석")
    image_column, chart_column = st.columns([1.15, 1])
    with image_column:
        if masked_image_path.is_file():
            st.image(
                str(masked_image_path),
                caption=(
                    "매장 앞 보행로와 계단 진입로를 포함한 관측구역을 "
                    "노란 박스로 표시했습니다."
                ),
                width="stretch",
            )
        else:
            st.warning("고객 보고서용 개인정보 보호 이미지를 찾지 못했습니다.")
    with chart_column:
        st.bar_chart(
            customer_time_chart(
                roi_summary,
                "mean_roi_observations_per_sampled_frame",
            ),
            x_label="시간대",
            y_label="분석 장면당 평균 인원(명)",
            stack=False,
            height=360,
        )
        st.caption("시간대별로 매장 앞 관측구역에서 동시에 보인 평균 인원")
    st.markdown(
        "전체 관측량 중 매장 앞 보행로와 계단 진입로에서 "
        f"나타난 비중은 {facts['storefront_share'] * 100:.1f}%입니다. "
        "매장 앞 관측구역의 "
        f"관측 수준은 **{format_report_date(facts['storefront_peak_date_id'])} "
        f"{facts['storefront_peak_hour']}**에 가장 높았습니다. 이 비중은 매장 입장률이나 "
        "구매 전환율이 아니라, 분석 화면의 매장 앞 관측구역에 등장한 사람의 비율입니다."
    )

    st.divider()
    st.subheader("5. 날짜별 공통 시간대 비교")
    comparable = facts["comparable_summary"]
    if facts["comparable_hours"] and not comparable.empty:
        comparison_chart = customer_time_chart(
            comparable,
            "mean_persons_per_sampled_frame",
        )
        st.bar_chart(
            comparison_chart,
            x_label="공통 관측 시간대",
            y_label="분석 장면당 평균 인원(명)",
            stack=False,
            height=320,
        )
        st.markdown(
            "두 날짜에 모두 영상이 있는 "
            f"**{', '.join(hour[:2] + '시' for hour in facts['comparable_hours'])}**만 "
            "직접 비교했습니다. 공통 시간대가 제한적이므로 날짜 전체의 우열로 확대 "
            "해석하지 않고, 반복 관측이 필요한 시간 후보를 찾는 데 사용합니다."
        )
    else:
        st.info("두 날짜에 공통으로 관측된 시간대가 없어 직접 비교하지 않았습니다.")

    st.divider()
    st.subheader("6. 보행 방향 이동 흐름 분석 (Line Crossing)")
    if crossing_summary is not None:
        c_results = crossing_summary.get("results", {})
        c_directions = c_results.get("direction_event_counts", {})
        total_crossing = int(c_results.get("total_crossing_events", 0))
        downward = int(c_directions.get("screen_downward_event", 0))
        upward = int(c_directions.get("screen_upward_event", 0))
        down_pct = (downward / total_crossing * 100.0) if total_crossing > 0 else 0.0
        up_pct = (upward / total_crossing * 100.0) if total_crossing > 0 else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 보행 통과 이벤트", f"{total_crossing}건")
        c2.metric("화면 하향 이동 (downward)", f"{down_pct:.1f}% ({downward}건)")
        c3.metric("화면 상향 이동 (upward)", f"{up_pct:.1f}% ({upward}건)")
        c4.metric("통과 트랙 수", f"{int(c_results.get('unique_track_ids_crossed', 0))}개")

        st.markdown(
            f"대표 검증 구간 분석 결과, 매장 전면 보행로 수동 기준선을 통과한 보행 이동 이벤트는 **총 {total_crossing}건**입니다. "
            f"화면 기준 아래쪽 이동(하향)과 위쪽 이동(상향)이 **각각 {downward}건({down_pct:.1f}%)과 {upward}건({up_pct:.1f}%)**으로 "
            "동일한 이동 비중을 형성하고 있습니다."
        )
        st.caption(
            "※ 보행 방향 통과 이벤트는 추적 경로가 기준선을 통과한 횟수이며, 고유 방문자 수나 하루 전체 총 유동인구를 의미하지 않습니다."
        )
    else:
        st.info("보행 방향 이동 흐름(Line Crossing) 산출물이 아직 로드되지 않았습니다.")

    st.divider()
    st.subheader("7. 운영·마케팅 실행 제안")
    st.markdown(
        f"**피크 시간 활용 · {facts['peak_hour']} 전후 프로모션 메시지 추천**  \n"
        "분석 범위에서 이 시간대의 매장 앞 관측량이 가장 높았습니다. 지나가는 "
        "고객의 시선을 빠르게 사로잡을 수 있도록 '점심 특가'나 '테이크아웃 할인'처럼 "
        "짧고 명확한 문구로 구성하는 것을 추천합니다.\n\n"
        "**보행 방향 동선 고려 · 양방향 시선 유도 입간판 및 배너 배치 추천**  \n"
        "보행로를 상향/하향으로 지나는 보행자 동선이 모두 관측(각 50.0% 비중)되었습니다. "
        "매장 입구 전면의 입간판 및 현수막은 한쪽 방향이 아닌 양방향 보행자 시선에서 동시에 "
        "눈에 띌 수 있도록 V자형 배치나 양면 배치를 권장합니다. 또한 보행자 이동 방향에 맞춰 "
        "'오시는 길 10m 앞'과 같은 화살표 시선 유도 문구를 적용하면 노출 효과를 높일 수 있습니다.\n\n"
        "**매장 앞 관측구역 · 보행로와 계단 진입로 동시 고려**  \n"
        "노란 관측구역은 매장 앞 보행로와 계단 진입로를 함께 포함합니다. 안내물은 "
        "두 동선에서 모두 확인하기 쉬운 위치에 배치하고, 문구는 짧게 줄이되 글자 크기는 "
        "멀리서도 읽힐 만큼 크게 구성하는 것이 좋습니다.\n\n"
        "**성과 연결 · POS 데이터와 함께 판단**  \n"
        "이번 관측만으로 매출 효과를 단정할 수는 없습니다. 실제 적용 시에는 POS 주문 수, "
        "쿠폰 사용량, 시간대별 객단가를 함께 비교해 관측량과 매출 반응의 관계를 "
        "확인해야 합니다.\n\n"
        "**향후 실제 적용 · 연속 촬영과 반복 날짜 확인**  \n"
        "실제 고객 매장에서는 영업시간 전체에 가까운 연속 촬영과 여러 날짜의 반복 측정이 "
        "확보된 뒤에 운영 변경 여부를 판단하는 것이 적절합니다."
    )

    st.divider()
    st.subheader("8. 분석 범위와 활용 기준")
    st.markdown(
        f"- 본 결과는 {facts['clip_count']}개 영상, 총 {facts['analysis_minutes']}분의 "
        "관측 표본을 분석한 결과입니다.\n"
        "- 같은 사람이 여러 분석 장면에 반복해서 보일 수 있어 고유 방문자 수가 아닙니다.\n"
        "- 하루 전체 연속 촬영이 아니므로 일일 총 통행량이나 일평균 유동인구를 산출하지 않습니다.\n"
        "- 성별·연령·이동 방향·매장 입장·구매 전환·매출은 이번 분석 범위에 포함하지 않습니다.\n"
        "- 실제 고객 매장에 적용할 경우 영업시간 연속 촬영, 반복 날짜 측정, POS·프로모션 반응 데이터가 함께 필요합니다."
    )


def render_video_validation(
    analysis: dict[str, Any],
    results_dir: Path,
) -> None:
    st.subheader("3. 실제 영상에서 구역 기준 확인")
    st.caption(
        "노란 선으로 나뉜 24칸이 아래 히트맵의 24칸과 같은 기준입니다. "
        "영상은 탐지 품질과 구역 기준을 눈으로 확인하기 위한 대표 피크 구간입니다."
    )

    source_videos = source_video_paths(analysis)
    if not source_videos:
        st.warning("analysis.json에서 원본 mp4 경로를 찾지 못했습니다.")
        return

    previews = preview_video_by_source_stem(results_dir)
    preview_source_stems = set(previews)
    selectable_videos = [
        video_path
        for video_path in source_videos
        if video_path.stem in preview_source_stems
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
            "scripts/archive/visitor_flow/L2/visitor_flow_l2_render_preview.py \\\n"
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
        with st.expander("6x4 Grid 보행 관측 검증 영상 (L2 디버깅용)", expanded=False):
            st.video(str(preview_video), format="video/webm")
            st.caption(f"검증 영상 artifact: {preview_video}")

    st.info(
        "영상 속 초록 박스는 YOLO가 사람으로 탐지한 위치입니다. "
        "노란 grid id는 내부 검증용이며, 아래 히트맵에서는 같은 위치를 쉬운 구역명으로 바꿔 보여줍니다."
    )


def render_operator_roi_video(
    source_analysis: dict[str, Any],
    roi_analysis: dict[str, Any],
    config: dict[str, Any],
    results_dir: Path,
    privacy_summary: dict[str, Any],
    masked_video_path: Path,
) -> None:
    st.markdown("#### 운영자용 ROI 마스킹 연속 영상 검수")
    st.caption(
        f"수동 ROI `{config.get('primary_roi_id', '-')}`가 연속 프레임에서도 같은 "
        "위치에 유지되고 bbox bottom-center 판정이 의도대로 동작하는지 확인하는 "
        "내부 QA 화면입니다. 기본 재생 영상은 L3-2 개인정보 보호 미디어입니다."
    )

    if masked_video_path.is_file():
        st.video(str(masked_video_path), format=video_format(masked_video_path))
        results = privacy_summary.get("results", {})
        settings = privacy_summary.get("settings", {})
        st.caption(
            "마스킹 영상: "
            f"{int(results.get('processed_frames', 0))} frames · "
            f"{float(results.get('source_fps', 0.0)):.1f} FPS · "
            f"masked regions {int(results.get('masked_region_observations', 0))}건 · "
            f"mask {settings.get('mask_method', 'unknown')}"
        )
    else:
        st.error(f"L3-2 마스킹 MP4를 찾지 못했습니다: {masked_video_path}")

    source_videos = source_video_paths(source_analysis)
    if not source_videos:
        st.warning("analysis.json에서 원본 mp4 경로를 찾지 못했습니다.")
        return

    previews = preview_video_by_source_stem(results_dir)
    preview_source_stems = set(previews)
    preferred_video_id = str(roi_analysis.get("preview", {}).get("video_id", ""))
    selectable_videos = [
        video_path
        for video_path in source_videos
        if video_path.stem in preview_source_stems
    ]
    if not selectable_videos:
        selectable_videos = source_videos

    default_index = next(
        (
            index
            for index, video_path in enumerate(selectable_videos)
            if video_path.stem == preferred_video_id
            or video_path.stem in preview_source_stems
        ),
        0,
    )
    if len(selectable_videos) == 1:
        selected_video = selectable_videos[0]
        st.markdown(f"**ROI 검증 clip:** `{selected_video.stem}`")
    else:
        selected_video = st.selectbox(
            "ROI 검증 clip 선택",
            options=selectable_videos,
            index=default_index,
            format_func=lambda path: path.stem,
            key="roi_validation_clip",
        )

    preview_video = previews.get(selected_video.stem)
    if preview_video is None:
        st.info(
            "선택한 clip의 ROI 검증 영상이 아직 없습니다. 아래 명령으로 오프라인 "
            "artifact를 만든 뒤 대시보드를 새로고침하세요."
        )
        confidence = float(source_analysis.get("confidence_threshold", 0.50))
        grid = source_analysis.get("grid", {})
        model_path = str(source_analysis.get("model", "/path/to/yolo.pt"))
        preview_timestamp_sec = float(
            roi_analysis.get("preview", {}).get("timestamp_ms", 0)
        ) / 1000.0
        start_sec = max(0, round(preview_timestamp_sec - 20))
        output_name = (
            f"{selected_video.stem}_yolo_conf_{confidence:.2f}_roi_start_{start_sec}s"
            .replace(".", "p")
            + ".webm"
        )
        command = (
            "/home/imella0707/miniconda3/envs/ssakda/bin/python "
            "scripts/archive/visitor_flow/L2/visitor_flow_l2_render_preview.py \\\n"
            f"  --video {selected_video} \\\n"
            f"  --model {model_path} \\\n"
            "  --device 0 \\\n"
            f"  --imgsz {int(source_analysis.get('imgsz', 960))} \\\n"
            f"  --conf {confidence:.2f} \\\n"
            f"  --grid-cols {int(grid.get('cols', 6))} \\\n"
            f"  --grid-rows {int(grid.get('rows', 4))} \\\n"
            f"  --roi-config {results_dir / 'roi_config.json'} \\\n"
            "  --hide-grid \\\n"
            f"  --start-sec {start_sec} \\\n"
            "  --max-seconds 60 \\\n"
            f"  --output {results_dir / 'preview_videos' / output_name}"
        )
        with st.expander("비마스킹 ROI QA 영상 생성 명령", expanded=False):
            st.code(command, language="bash")
    else:
        with st.expander("비마스킹 ROI QA 영상 경로", expanded=False):
            st.caption("필요한 디버깅 때만 내부 운영자가 확인합니다. 기본 화면에는 재생하지 않습니다.")
            st.code(str(preview_video), language="text")

    st.warning(
        "운영자 화면도 기본적으로 L3-2 마스킹 미디어만 표시합니다. "
        "비마스킹 ROI WebM과 원본 frame은 내부 디버깅 경로로만 관리하고, "
        "고객 PDF에는 L3-2 마스킹 대표 이미지만 허용합니다."
    )


def render_operator_integrated_qa(
    tracking_summary: dict[str, Any] | None,
    tracking_video_path: Path | None,
    track_events_path: Path | None,
    tracking_qa_dir: Path,
    missing_tracking_files: list[Path],
    crossing_summary: dict[str, Any] | None,
    crossing_video_path: Path | None,
    crossing_events_path: Path | None,
    crossing_dir: Path,
    missing_crossing_files: list[Path],
) -> None:
    st.markdown("#### 운영자용 ROI · 개인정보 마스킹 · Tracking · Line Crossing 통합 QA")
    st.caption(
        "L3-4/L3-5 통합 QA입니다. ROI, 개인정보 마스킹, 연속 frame track ID, 수동 기준선(Line Crossing) 통과 이벤트를 "
        "단일 비디오 플레이어로 함께 검수합니다. (고유 방문자 수나 매장 입장객 수를 의미하지 않습니다)"
    )

    # 1개의 통합 비디오 플레이어: L3-5 비디오(ROI + 마스킹 + Tracking + Line Crossing + 카운터)를 최우선 재생
    primary_video_path = None
    video_title = ""
    if crossing_video_path is not None and crossing_video_path.is_file():
        primary_video_path = crossing_video_path
        video_title = "L3-5 Line Crossing & Tracking 통합 영상"
    elif tracking_video_path is not None and tracking_video_path.is_file():
        primary_video_path = tracking_video_path
        video_title = "L3-4 Tracking QA 영상"

    if primary_video_path is not None:
        st.video(str(primary_video_path), format=video_format(primary_video_path))
        st.caption(f"통합 QA 비디오 ({video_title}): {primary_video_path}")
    else:
        st.warning("통합 QA 비디오 산출물(L3-4 / L3-5)이 아직 없거나 로드되지 않았습니다.")
        if missing_crossing_files:
            st.code("\n".join(str(path) for path in missing_crossing_files), language="text")

    # Line Crossing 지표 카드
    if crossing_summary is not None:
        st.markdown("##### 1. L3-5 Line Crossing 보행 방향 지표")
        results = crossing_summary.get("results", {})
        direction_counts = results.get("direction_event_counts", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "총 crossing 이벤트",
            f"{int(results.get('total_crossing_events', 0))}건",
        )
        c2.metric(
            "화면 하향 (downward)",
            f"{int(direction_counts.get('screen_downward_event', 0))}건",
        )
        c3.metric(
            "화면 상향 (upward)",
            f"{int(direction_counts.get('screen_upward_event', 0))}건",
        )
        c4.metric(
            "통과 track ID 수",
            f"{int(results.get('unique_track_ids_crossed', 0))}개",
        )

    # Tracking 지표 카드
    if tracking_summary is not None:
        st.markdown("##### 2. L3-4 Person Tracking 추적 지표")
        t_results = tracking_summary.get("results", {})
        t_settings = tracking_summary.get("settings", {})
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("처리 frame", f"{int(t_results.get('processed_frames', 0))}장")
        t2.metric(
            "활성 track 최대",
            f"{int(t_results.get('max_active_tracks_per_frame', 0))}",
        )
        t3.metric(
            "clip-local track ID",
            f"{int(t_results.get('unique_clip_track_ids', 0))}개",
        )
        t4.metric(
            "fragment 후보",
            f"{int(t_results.get('fragmentation_gap_count', 0))}건",
        )
        st.caption(
            "tracking 설정: "
            f"{float(t_results.get('source_fps', 0.0)):.1f} FPS · "
            f"tracker {t_settings.get('tracker', '-')} · "
            f"privacy mask {'on' if t_settings.get('privacy_mask_enabled') else 'off'}"
        )

    # 로그 상세
    if crossing_events_path is not None and crossing_events_path.is_file():
        with st.expander("L3-5 Crossing Event 상세 로그 (CSV)", expanded=False):
            try:
                crossing_df = pd.read_csv(crossing_events_path)
                st.dataframe(crossing_df, hide_index=True, use_container_width=True)
            except Exception as err:
                st.warning(f"Crossing CSV 읽기 실패: {err}")

    if track_events_path is not None and track_events_path.is_file():
        with st.expander("L3-4 Track Event 로그 샘플 (CSV)", expanded=False):
            try:
                track_events = pd.read_csv(track_events_path)
                st.dataframe(track_events.head(50), hide_index=True, use_container_width=True)
            except Exception as err:
                st.warning(f"Track events CSV 읽기 실패: {err}")

    with st.expander("QA Summary JSON 탐색기 (L3-4 & L3-5)", expanded=False):
        j_col1, j_col2 = st.columns(2)
        with j_col1:
            st.markdown("**L3-4 Tracking QA Summary**")
            st.json(tracking_summary or {})
        with j_col2:
            st.markdown("**L3-5 Crossing Summary**")
            st.json(crossing_summary or {})


def render_operator_tracking_qa(
    tracking_summary: dict[str, Any] | None,
    tracking_video_path: Path | None,
    track_events_path: Path | None,
    tracking_qa_dir: Path,
    missing_files: list[Path],
) -> None:
    render_operator_integrated_qa(
        tracking_summary=tracking_summary,
        tracking_video_path=tracking_video_path,
        track_events_path=track_events_path,
        tracking_qa_dir=tracking_qa_dir,
        missing_tracking_files=missing_files,
        crossing_summary=None,
        crossing_video_path=None,
        crossing_events_path=None,
        crossing_dir=tracking_qa_dir,
        missing_crossing_files=[],
    )


def render_operator_crossing_qa(
    crossing_summary: dict[str, Any] | None,
    crossing_video_path: Path | None,
    crossing_events_path: Path | None,
    crossing_dir: Path,
    missing_files: list[Path],
) -> None:
    render_operator_integrated_qa(
        tracking_summary=None,
        tracking_video_path=None,
        track_events_path=None,
        tracking_qa_dir=crossing_dir,
        missing_tracking_files=[],
        crossing_summary=crossing_summary,
        crossing_video_path=crossing_video_path,
        crossing_events_path=crossing_events_path,
        crossing_dir=crossing_dir,
        missing_crossing_files=missing_files,
    )


def render_scope_notice() -> None:
    st.warning(
        "이 화면은 CCTV 화면에서 사람이 얼마나 자주 보였는지 비교하는 POC입니다. "
        "표시 값은 정확한 방문객 수가 아니라, 시간대별 붐빔 정도를 보는 관측량입니다. "
        "ROI와 화면 구역 정보는 원근 보정 전의 화면 좌표 기준 관측 분포입니다."
    )


def render_metric_cards(
    analysis: dict[str, Any],
    *,
    show_validation_details: bool = True,
) -> None:
    st.subheader("1. 분석 범위 및 정량 지표 개요")

    peak_bucket = analysis.get("peak_time_bucket", {})
    clip_count = int(analysis.get("clip_count", 0))
    sampled_frames = int(analysis.get("sampled_frames", 0))

    if show_validation_details:
        val_m1, val_m2, val_m3, val_m4 = st.columns(4)
        val_m1.metric("분석 영상 수", f"{clip_count}개 clips")
        val_m2.metric("총 sampled frame", f"{sampled_frames}장")
        val_m3.metric("sampling 간격", f"{analysis.get('sample_every_sec', 10.0)}초")
        val_m4.metric(
            "총 person observations",
            f"{int(analysis.get('person_detection_observations', 0))}건",
        )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "분석 장면당 평균 관측",
        f"{analysis.get('mean_persons_per_sampled_frame', 0.0):.3f}명",
    )
    m2.metric(
        "피크 시간대 (10분 기준)",
        str(peak_bucket.get("time_bucket", "-")),
    )
    m3.metric(
        "피크 장면당 관측",
        f"{peak_bucket.get('mean_persons_per_sampled_frame', 0.0):.3f}명",
    )
    m4.metric(
        "단일 장면 최대 관측",
        f"{int(analysis.get('max_persons_in_single_sampled_frame', 0))}명",
    )

    st.caption(
        "※ 프레임당 관측 인원은 0명 frame을 포함한 평균입니다. 피크 시간대는 10초 간격 "
        "sampled frame 기준 프레임당 평균 관측 인원이 가장 높은 시간대입니다."
    )


def render_time_trend(dashboard_summary: pd.DataFrame) -> None:
    st.subheader("3. 시간대별 보행 관측 추이 및 날짜 비교")

    dates = sorted(dashboard_summary["date_id"].unique())
    selected_metric = st.radio(
        "비교 지표",
        options=["mean_persons_per_sampled_frame", "person_observations"],
        format_func=lambda value: (
            "프레임당 평균 관측 인원 (0명 frame 포함)"
            if value == "mean_persons_per_sampled_frame"
            else "총 observation 수 (단순 합계)"
        ),
        horizontal=True,
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("#### 시간대별 관측 추이")
        pivot_df = dashboard_summary.pivot(
            index="time_bucket",
            columns="date_id",
            values=selected_metric,
        )
        pivot_df.index = [
            t.split(" ")[1][:5] if isinstance(t, str) and " " in t else str(t)
            for t in pivot_df.index
        ]
        st.line_chart(pivot_df, use_container_width=True)

    with col2:
        st.markdown("#### 날짜별 비교 요약")
        for date_id in dates:
            date_df = dashboard_summary[dashboard_summary["date_id"] == date_id]
            avg_val = date_df["mean_persons_per_sampled_frame"].mean()
            max_val = date_df["mean_persons_per_sampled_frame"].max()
            st.metric(
                f"{date_id} 평균",
                f"{avg_val:.3f}명",
                delta=f"최대 {max_val:.3f}명",
            )


def render_video_validation(analysis: dict[str, Any], results_dir: Path) -> None:
    st.subheader("4. 영상별 분석 결과 검증")

    clip_summaries = analysis.get("clip_summaries", [])
    if not clip_summaries:
        st.info("clip summary 정보가 없습니다.")
        return

    df_clips = pd.DataFrame(clip_summaries)

    if "video_path" in df_clips.columns:
        df_clips["clip_name"] = df_clips["video_path"].apply(
            lambda value: Path(str(value)).name
        )

    cols_to_show = [
        col
        for col in [
            "clip_name",
            "time_bucket",
            "sampled_frames",
            "person_observations",
            "mean_persons_per_sampled_frame",
            "max_persons_in_sampled_frame",
        ]
        if col in df_clips.columns
    ]

    st.dataframe(
        df_clips[cols_to_show],
        use_container_width=True,
        hide_index=True,
    )


def render_grid_heatmap(
    analysis: dict[str, Any],
    summary: pd.DataFrame,
    dashboard_summary: pd.DataFrame,
) -> None:
    st.subheader("5. 화면 구역별 (6x4 Grid) 관측 분포")

    st.caption(
        "CCTV 화면을 6열 x 4행(총 24개 구역)으로 분할하여, "
        "어느 구역에 사람 bbox가 가장 자주 보였는지 상대적 비중을 나타냅니다."
    )

    grid_info = analysis.get("grid_heatmap_summary", {})
    total_obs = grid_info.get("total_observations", 0)
    top_zone = grid_info.get("top_zone", {})

    if top_zone:
        st.info(
            f"가장 붐비는 구역: **{format_zone_id(top_zone.get('zone_id', ''))}** "
            f"(관측 비중: {top_zone.get('observation_share', 0.0) * 100:.1f}%, "
            f"총 {top_zone.get('observation_count', 0)}건)"
        )


def render_raw_tables(
    analysis: dict[str, Any],
    frames: pd.DataFrame,
    events: pd.DataFrame,
    summary: pd.DataFrame,
    results_dir: Path,
) -> None:
    st.subheader("6. 개발/검증용 원본 artifact")
    with st.expander("analysis.json", expanded=False):
        st.json(analysis)
    with st.expander("summary.parquet sample", expanded=False):
        st.dataframe(summary.head(50), hide_index=True, width="stretch")
    with st.expander("frames.parquet sample", expanded=False):
        st.dataframe(frames.head(50), hide_index=True, width="stretch")
    with st.expander("events.parquet sample", expanded=False):
        st.dataframe(events.head(50), hide_index=True, width="stretch")
    st.caption(f"현재 읽는 L2 결과 폴더: {results_dir}")


def render_scope_notice() -> None:
    st.warning(
        "이 화면은 CCTV 화면에서 사람이 얼마나 자주 보였는지 비교하는 POC입니다. "
        "표시 값은 정확한 방문객 수가 아니라, 시간대별 붐빔 정도를 보는 관측량입니다. "
        "ROI와 화면 구역 정보는 원근 보정 전의 화면 좌표 기준 관측 분포입니다."
    )


def render_metric_cards(
    analysis: dict[str, Any],
    *,
    show_validation_details: bool = True,
) -> None:
    first, second, third, fourth = st.columns(4)
    peak_bucket = str(analysis.get("peak_time_bucket", ""))
    peak_date_id = str(analysis.get("peak_date_id", ""))
    top_zone_id = str(analysis.get("top_zone_id", "-"))
    peak_time_label = peak_bucket[11:16] if len(peak_bucket) >= 16 else "-"
    if peak_date_id:
        peak_time_label = f"{peak_date_id} {peak_time_label}"
    first.metric("상대 피크 시간대", peak_time_label)
    second.metric(
        "프레임당 평균 관측",
        f"{float(analysis.get('peak_mean_persons_per_sampled_frame', 0.0)):.3f}",
    )
    third.caption("화면 기준 최다 관측 구역")
    third.markdown(f"### {format_zone_for_owner(top_zone_id, compact=True)}")
    fourth.metric("분석한 CCTV 영상", f"{int(analysis['clip_count'])}개")

    st.info(
        "관측량은 CCTV 화면에서 사람으로 탐지된 횟수이며, 방문자 수나 통행량을 의미하지 않습니다. "
        "같은 사람이 여러 장면에 보이면 여러 번 잡힐 수 있으므로, 실제 방문객 수로 해석하면 안 됩니다. "
        "최다 관측 구역은 실제 지면의 가장 붐비는 장소가 아니라 화면 기준으로 사람이 많이 잡힌 칸입니다."
    )

    if not show_validation_details:
        return

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
                    "항목": "peak p95",
                    "값": (
                        f"{float(analysis.get('peak_p95_persons_per_sampled_frame', 0.0)):.3f}"
                    ),
                    "의미": "피크 시간대 sampled frame별 관측 count의 95 percentile",
                },
                {
                    "항목": "peak max",
                    "값": f"{int(analysis.get('peak_max_persons_per_sampled_frame', 0))}",
                    "의미": "피크 시간대 단일 sampled frame에서 가장 많이 잡힌 관측량",
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


def render_roi_analysis(
    source_analysis: dict[str, Any],
    analysis: dict[str, Any],
    config: dict[str, Any],
    summary: pd.DataFrame,
    frames: pd.DataFrame,
    events: pd.DataFrame,
    results_dir: Path,
    privacy_summary: dict[str, Any],
    masked_image_path: Path,
    masked_video_path: Path,
    *,
    show_operator_debug: bool = True,
) -> None:
    st.subheader("1. 매장 전면 ROI 관측량")
    st.caption("수동 normalized polygon · bbox bottom-center 판정 · 10초 sampled frame")

    peak_bucket = str(analysis.get("peak_time_bucket", ""))
    peak_label = peak_bucket[:16] if len(peak_bucket) >= 16 else "-"
    first, second, third, fourth = st.columns(4)
    first.metric("ROI 내부 관측", f"{int(analysis.get('roi_observations', 0))}건")
    second.metric(
        "전체 관측 중 ROI 비중",
        f"{float(analysis.get('roi_observation_share', 0.0)) * 100:.1f}%",
    )
    third.metric("ROI 상대 피크", peak_label)
    fourth.metric(
        "피크 프레임당 평균",
        f"{float(analysis.get('peak_mean_roi_observations_per_sampled_frame', 0.0)):.3f}",
    )
    st.info(
        "ROI 내부 관측은 빨간 bbox 하단 중심점이 노란 polygon 안에 들어온 sampled "
        "observation입니다. 같은 사람이 여러 frame에 나타날 수 있어 통행량이나 고유 방문자 수가 아닙니다."
    )

    overlay_path_text = str(analysis.get("preview", {}).get("path", ""))
    overlay_path = resolve_repo_path(overlay_path_text) if overlay_path_text else None
    image_column, chart_column = st.columns([1.15, 1])
    with image_column:
        if masked_image_path.is_file():
            st.image(
                str(masked_image_path),
                caption=(
                    "L3-2 마스킹 대표 이미지 · 노란색: 수동 ROI · "
                    "초록색: ROI 내부 bbox · 빨간 점: bbox bottom-center"
                ),
                width="stretch",
            )
        else:
            st.warning(f"L3-2 마스킹 대표 이미지를 찾지 못했습니다: {masked_image_path}")
        with st.expander("비마스킹 ROI overlay 경로", expanded=False):
            if overlay_path is not None and overlay_path.is_file():
                st.code(str(overlay_path), language="text")
            else:
                st.warning(f"비마스킹 ROI overlay를 찾지 못했습니다: {overlay_path_text}")

    with chart_column:
        chart = summary.copy()
        chart["time_label"] = pd.to_datetime(chart["time_bucket"]).dt.strftime("%H:%M")
        hour_counts = chart.groupby("time_label")["date_id"].nunique()
        comparable_hours = sorted(hour_counts[hour_counts >= 2].index.tolist())
        chart = chart.pivot_table(
            index="time_label",
            columns="date_id",
            values="mean_roi_observations_per_sampled_frame",
            aggfunc="first",
        ).sort_index()
        st.bar_chart(chart, height=360)
        st.caption(
            "시간대별 ROI 내부 관측의 sampled frame당 평균. "
            "두 날짜가 모두 있는 직접 비교 시간대: "
            f"{', '.join(comparable_hours) if comparable_hours else '없음'}"
        )
        if comparable_hours and len(comparable_hours) < len(chart):
            st.warning(
                "일부 시간대는 한 날짜에만 존재합니다. 날짜 편차 검증은 겹치는 "
                "시간대만 기준으로 보고, 나머지는 각 날짜의 표본 내 피크 후보로만 해석하세요."
            )

    display = summary.copy()
    display["time_bucket"] = pd.to_datetime(display["time_bucket"]).dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    display["roi_observation_share_pct"] = display["roi_observation_share"] * 100
    st.dataframe(
        display[
            [
                "date_id",
                "time_bucket",
                "sampled_frame_count",
                "roi_observations",
                "mean_roi_observations_per_sampled_frame",
                "p95_roi_observations_per_sampled_frame",
                "max_roi_observations_per_sampled_frame",
                "roi_observation_share_pct",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "date_id": "날짜",
            "time_bucket": "시간대",
            "sampled_frame_count": "sampled frame",
            "roi_observations": "ROI 관측 합계",
            "mean_roi_observations_per_sampled_frame": st.column_config.NumberColumn(
                "ROI 프레임당 평균",
                format="%.3f",
            ),
            "p95_roi_observations_per_sampled_frame": st.column_config.NumberColumn(
                "ROI p95",
                format="%.3f",
            ),
            "max_roi_observations_per_sampled_frame": "ROI max",
            "roi_observation_share_pct": st.column_config.NumberColumn(
                "전체 관측 중 ROI 비중",
                format="%.1f%%",
            ),
        },
    )
    overlap = summary.copy()
    overlap["hour"] = pd.to_datetime(overlap["time_bucket"]).dt.strftime("%H:%M")
    overlap_hours = (
        overlap.groupby("hour")["date_id"].nunique().loc[lambda count: count >= 2].index
    )
    overlap = overlap[overlap["hour"].isin(overlap_hours)]
    if not overlap.empty:
        overlap_chart = overlap.pivot_table(
            index="hour",
            columns="date_id",
            values="mean_roi_observations_per_sampled_frame",
            aggfunc="first",
        ).sort_index()
        st.caption("날짜 편차 직접 비교: 두 날짜가 모두 있는 시간대만 표시")
        st.dataframe(
            overlap_chart,
            width="stretch",
            column_config={
                column: st.column_config.NumberColumn(column, format="%.3f")
                for column in overlap_chart.columns
            },
        )
    if show_operator_debug:
        render_operator_roi_video(
            source_analysis=source_analysis,
            roi_analysis=analysis,
            config=config,
            results_dir=results_dir,
            privacy_summary=privacy_summary,
            masked_video_path=masked_video_path,
        )
        with st.expander("ROI 설정과 판정 artifact", expanded=False):
            st.json(config)
            st.dataframe(frames.head(30), hide_index=True, width="stretch")
            st.dataframe(events.head(30), hide_index=True, width="stretch")
            st.caption(f"현재 읽는 L3-1 결과 폴더: {results_dir}")


def render_time_trend(
    dashboard_summary: pd.DataFrame,
    *,
    show_validation_details: bool = True,
) -> None:
    st.subheader("2. 전체 화면 시간대별 프레임 정규화 관측량")
    chart = dashboard_summary.copy()
    chart["time_label"] = pd.to_datetime(chart["time_bucket"]).dt.strftime("%H:%M")
    if "date_id" in chart.columns:
        hour_counts = chart.groupby("time_label")["date_id"].nunique()
        comparable_hours = sorted(hour_counts[hour_counts >= 2].index.tolist())
        chart = chart.pivot_table(
            index="time_label",
            columns="date_id",
            values="mean_persons_per_sampled_frame",
            aggfunc="first",
        ).sort_index()
    else:
        comparable_hours = []
        chart = chart.set_index("time_label")[["mean_persons_per_sampled_frame"]]
    st.bar_chart(chart, height=320)
    st.caption(
        "두 날짜가 모두 있는 직접 비교 시간대: "
        f"{', '.join(comparable_hours) if comparable_hours else '없음'}. "
        "겹치지 않는 시간대는 날짜 간 차이가 아니라 해당 날짜 표본의 관측 결과입니다."
    )

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
                "date_id",
                "time_bucket",
                "sampled_frame_count",
                "total_person_detection_observations",
                "mean_persons_per_sampled_frame",
                "p95_persons_per_sampled_frame",
                "max_persons_per_sampled_frame",
                "relative_crowding_score",
                "marketing_signal_label",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "date_id": "날짜",
            "time_bucket": "시간대",
            "sampled_frame_count": "sampled frame",
            "total_person_detection_observations": "관측 합계",
            "mean_persons_per_sampled_frame": st.column_config.NumberColumn(
                "프레임당 평균",
                format="%.3f",
            ),
            "p95_persons_per_sampled_frame": st.column_config.NumberColumn(
                "p95",
                format="%.3f",
            ),
            "max_persons_per_sampled_frame": "max",
            "relative_crowding_score": st.column_config.NumberColumn(
                "상대 붐빔",
                format="%.3f",
            ),
            "marketing_signal_label": "시간대 해석 후보",
        },
    )
    if not show_validation_details:
        return

    with st.expander("검증용 시간대별 화면 구역 보기", expanded=False):
        st.dataframe(
            display[
                [
                    "date_id",
                    "time_bucket",
                    "top_zone_label",
                    "top_zone_observations",
                    "top_zone_mean_persons_per_sampled_frame",
                ]
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "date_id": "날짜",
                "time_bucket": "시간대",
                "top_zone_label": "화면 기준 최다 관측 구역",
                "top_zone_observations": "구역 관측량",
                "top_zone_mean_persons_per_sampled_frame": (
                    st.column_config.NumberColumn(
                        "구역 프레임당 평균",
                        format="%.3f",
                    )
                ),
            },
        )


def grid_labels(rows: int, cols: int) -> list[str]:
    return [f"r{row}_c{col}" for row in range(rows) for col in range(cols)]


def build_heatmap_table(
    summary: pd.DataFrame,
    selected_bucket_key: str,
    grid_rows: int,
    grid_cols: int,
) -> pd.DataFrame:
    if selected_bucket_key == ALL_TIME_BUCKET:
        selected = summary.groupby("zone_id", as_index=False)[
            "person_detection_observations"
        ].sum()
    else:
        selected_date_id, selected_time_bucket = selected_bucket_key.split("|", 1)
        selected = summary.loc[
            (summary["date_id"].astype(str) == selected_date_id)
            & (summary["time_bucket"].astype(str) == selected_time_bucket)
        ]
    counts = {zone_id: 0 for zone_id in grid_labels(rows=grid_rows, cols=grid_cols)}
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
    st.subheader("4. 화면 구역별 관측량 분포")
    st.caption("화면 기준 · 원근 미보정 · 실제 지면 밀집도 아님")
    st.info(
        "아래 24칸은 검증 영상에 보이는 노란 6x4 grid와 같은 기준입니다. "
        "각 칸의 숫자는 선택한 시간대에 그 화면 구역에서 사람이 보인 관측량이고, "
        "색이 연하면 적게 보인 구역, 빨갛게 진하면 자주 보인 구역입니다. "
        "화면 상단의 먼 보행로는 원근 때문에 좁은 구역에 압축되어 보일 수 있으므로, "
        "이 표를 입간판 설치 위치나 실제 면적당 밀집도로 해석하면 안 됩니다."
    )

    bucket_rows = dashboard_summary[["date_id", "time_bucket"]].drop_duplicates()
    bucket_rows = bucket_rows.sort_values(["date_id", "time_bucket"])
    bucket_labels = {
        f"{row.date_id}|{row.time_bucket}": (
            f"{row.date_id} {pd.to_datetime(row.time_bucket).strftime('%H:%M')}"
        )
        for row in bucket_rows.itertuples(index=False)
    }
    bucket_options = [ALL_TIME_BUCKET] + list(bucket_labels)
    selected_bucket_key = st.selectbox(
        "확인할 날짜/시간대",
        options=bucket_options,
        index=0,
        format_func=lambda value: (
            "전체 날짜/시간대"
            if value == ALL_TIME_BUCKET
            else bucket_labels.get(value, value)
        ),
    )
    st.caption(
        "시간대 목록은 입력 clip의 시작 시각을 1시간 단위로 묶은 결과입니다. "
        "같은 날짜의 여러 clip이 같은 hour bucket에 있으면 합산됩니다."
    )

    grid = analysis.get("grid", {})
    grid_cols = int(grid.get("cols", 6))
    grid_rows = int(grid.get("rows", 4))
    heatmap = build_heatmap_table(
        summary=summary,
        selected_bucket_key=selected_bucket_key,
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
        summary.groupby("zone_id", as_index=False).agg(
            person_detection_observations=(
                "person_detection_observations",
                "sum",
            ),
            density_score=("density_score", "max"),
            hotspot_rank=("hotspot_rank", "min"),
            marketing_signal=("marketing_signal", "first"),
        )
        if selected_bucket_key == ALL_TIME_BUCKET
        else summary.loc[
            (summary["date_id"].astype(str) == selected_bucket_key.split("|", 1)[0])
            & (
                summary["time_bucket"].astype(str)
                == selected_bucket_key.split("|", 1)[1]
            )
        ]
        .sort_values("person_detection_observations", ascending=False)
        .reset_index(drop=True)
    )
    if selected_bucket_key == ALL_TIME_BUCKET:
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
                "person_detection_observations": "관측량",
                "density_score": st.column_config.NumberColumn(
                    "상대 관측 강도",
                    format="%.3f",
                ),
                "hotspot_rank": "관측 순위",
            },
        )


def render_marketing_interpretation(dashboard_summary: pd.DataFrame) -> None:
    st.subheader("5. 마케팅 해석 후보")
    peak = dashboard_summary.sort_values(
        "mean_persons_per_sampled_frame",
        ascending=False,
    ).iloc[0]
    peak_time = pd.to_datetime(peak["time_bucket"]).strftime("%H:%M")
    st.info(
        f"이 데이터에서는 {peak['date_id']} {peak_time}의 프레임당 평균 관측이 가장 높았습니다. "
        f"평균은 {float(peak['mean_persons_per_sampled_frame']):.3f}명/frame이고, "
        f"관측 합계는 {int(peak['total_person_detection_observations'])}건입니다. "
        "주지표는 sampled frame 수 차이를 보정한 값이며, 실제 방문객 수가 아닙니다."
    )
    st.markdown(
        "- 오전 시간대 관측량이 높으면 아침 판촉 후보로 볼 수 있습니다.\n"
        "- 점심/오후 시간대 관측량은 매장 전면 노출이 커질 수 있는 시간대 후보로 볼 수 있습니다.\n"
        "- 늦은 저녁 관측량은 테이크아웃, 배달 픽업 후보 시간대로 볼 수 있습니다.\n"
        "- 매장 전면 ROI 관측이 높은 시간대는 짧은 쇼윈도·입간판 문구 테스트 후보입니다.\n"
        "- 현재 마케팅 후보는 규칙 기반 가설이며 매출 상승 검증 결과가 아닙니다."
    )


def render_raw_tables(
    analysis: dict[str, Any],
    frames: pd.DataFrame,
    events: pd.DataFrame,
    summary: pd.DataFrame,
    results_dir: Path,
) -> None:
    st.subheader("6. 개발/검증용 원본 artifact")
    with st.expander("analysis.json", expanded=False):
        st.json(analysis)
    with st.expander("summary.parquet sample", expanded=False):
        st.dataframe(summary.head(50), hide_index=True, width="stretch")
    with st.expander("frames.parquet sample", expanded=False):
        st.dataframe(frames.head(50), hide_index=True, width="stretch")
    with st.expander("events.parquet sample", expanded=False):
        st.dataframe(events.head(50), hide_index=True, width="stretch")
    st.caption(f"현재 읽는 L2 결과 폴더: {results_dir}")


def main() -> None:
    st.set_page_config(
        page_title="Visitor Flow L3 Dashboard",
        layout="wide",
    )
    st.title("BrandMate 상권분석 리포트 스튜디오")
    st.caption(
        "내부 운영자용 리포트 미리보기 · 분석 QA · 개발 artifact"
    )

    with st.sidebar:
        st.header("데이터 경로")
        results_path_text = st.text_input(
            "L2 결과 폴더",
            value=str(DEFAULT_RESULTS_DIR.relative_to(REPO_ROOT)),
        )
        roi_results_path_text = st.text_input(
            "L3-1 ROI 결과 폴더",
            value=str(DEFAULT_ROI_RESULTS_DIR.relative_to(REPO_ROOT)),
        )
        privacy_media_path_text = st.text_input(
            "L3-2 개인정보 보호 미디어 폴더",
            value=str(DEFAULT_PRIVACY_MEDIA_DIR.relative_to(REPO_ROOT)),
        )
        tracking_qa_path_text = st.text_input(
            "L3-4 tracking QA 폴더",
            value=str(DEFAULT_TRACKING_QA_DIR.relative_to(REPO_ROOT)),
        )
        crossing_path_text = st.text_input(
            "L3-5 line crossing 폴더",
            value=str(DEFAULT_CROSSING_RESULTS_DIR.relative_to(REPO_ROOT)),
        )
        st.caption("절대 경로 또는 저장소 루트 기준 상대 경로를 사용할 수 있습니다.")
        st.divider()
        st.header("고객 보고서 정보")
        report_store_name = st.text_input(
            "매장명",
            value=DEFAULT_REPORT_STORE_NAME,
        )
        report_location = st.text_input(
            "조사 위치",
            value=DEFAULT_REPORT_LOCATION,
        )
        report_number = st.text_input(
            "보고서 번호",
            value=DEFAULT_REPORT_NUMBER,
        )

    results_dir = resolve_results_dir(results_path_text)
    missing_files = validate_results_dir(results_dir)
    if missing_files:
        st.error("필수 L2 산출물을 찾지 못했습니다.")
        st.code("\n".join(str(path) for path in missing_files))
        st.stop()

    try:
        analysis, dashboard_summary, summary, frames, events = load_l2_artifacts(
            results_dir
        )
    except (json.JSONDecodeError, OSError, KeyError, pd.errors.ParserError) as error:
        st.error(f"L2 산출물을 읽지 못했습니다: {error}")
        st.stop()

    roi_results_dir = resolve_results_dir(roi_results_path_text)
    missing_roi_files = validate_roi_results_dir(roi_results_dir)
    if missing_roi_files:
        st.error("필수 L3-1 ROI 산출물을 찾지 못했습니다.")
        st.code("\n".join(str(path) for path in missing_roi_files))
        st.stop()
    try:
        roi_analysis, roi_config, roi_summary, roi_frames, roi_events = (
            load_roi_artifacts(roi_results_dir)
        )
    except (json.JSONDecodeError, OSError, KeyError, pd.errors.ParserError) as error:
        st.error(f"L3-1 ROI 산출물을 읽지 못했습니다: {error}")
        st.stop()
    if roi_analysis.get("source_analysis_id") != analysis.get("analysis_id"):
        st.error("L2와 L3-1 ROI 산출물의 source_analysis_id가 일치하지 않습니다.")
        st.stop()

    privacy_media_dir = resolve_results_dir(privacy_media_path_text)
    missing_privacy_files = validate_privacy_media_dir(privacy_media_dir)
    if missing_privacy_files:
        st.error("필수 L3-2 개인정보 보호 미디어 산출물을 찾지 못했습니다.")
        st.code("\n".join(str(path) for path in missing_privacy_files))
        st.stop()
    try:
        privacy_summary, masked_image_path, masked_video_path = load_privacy_media(
            privacy_media_dir
        )
    except (json.JSONDecodeError, OSError, KeyError) as error:
        st.error(f"L3-2 개인정보 보호 미디어 산출물을 읽지 못했습니다: {error}")
        st.stop()

    tracking_qa_dir = resolve_results_dir(tracking_qa_path_text)
    missing_tracking_files = validate_tracking_qa_dir(tracking_qa_dir)
    tracking_summary: dict[str, Any] | None = None
    tracking_video_path: Path | None = None
    track_events_path: Path | None = None
    if not missing_tracking_files:
        try:
            tracking_summary, tracking_video_path, track_events_path = load_tracking_qa(
                tracking_qa_dir
            )
        except (json.JSONDecodeError, OSError, KeyError) as error:
            st.warning(f"L3-4 tracking QA 산출물을 읽지 못했습니다: {error}")
            missing_tracking_files = [tracking_qa_dir / "qa" / "tracking_qa_summary.json"]

    crossing_dir = resolve_results_dir(crossing_path_text)
    missing_crossing_files = validate_crossing_dir(crossing_dir)
    crossing_summary: dict[str, Any] | None = None
    crossing_video_path: Path | None = None
    crossing_events_path: Path | None = None
    if not missing_crossing_files:
        try:
            crossing_summary, crossing_video_path, crossing_events_path = (
                load_crossing_results(crossing_dir)
            )
        except (json.JSONDecodeError, OSError, KeyError) as error:
            st.warning(f"L3-5 line crossing 산출물을 읽지 못했습니다: {error}")
            missing_crossing_files = [crossing_dir / "qa" / "crossing_summary.json"]

    report_tab, operator_tab, artifact_tab = st.tabs(
        ["고객 PDF 리포트", "운영 QA", "개발 artifact"]
    )

    with report_tab:
        render_customer_report(
            analysis,
            dashboard_summary,
            roi_analysis,
            roi_summary,
            masked_image_path,
            crossing_summary=crossing_summary,
            store_name=report_store_name,
            survey_location=report_location,
            report_number=report_number,
        )

    with operator_tab:
        st.subheader("운영 QA")
        st.caption(
            "내부 담당자가 ROI, 마스킹 미디어, 탐지 품질, grid 해석을 검수하는 화면입니다. "
            "고객에게 직접 공유하지 않습니다."
        )
        render_scope_notice()
        render_metric_cards(analysis)
        st.divider()
        render_roi_analysis(
            analysis,
            roi_analysis,
            roi_config,
            roi_summary,
            roi_frames,
            roi_events,
            roi_results_dir,
            privacy_summary,
            masked_image_path,
            masked_video_path,
            show_operator_debug=False,
        )
        st.divider()
        render_operator_integrated_qa(
            tracking_summary=tracking_summary,
            tracking_video_path=tracking_video_path,
            track_events_path=track_events_path,
            tracking_qa_dir=tracking_qa_dir,
            missing_tracking_files=missing_tracking_files,
            crossing_summary=crossing_summary,
            crossing_video_path=crossing_video_path,
            crossing_events_path=crossing_events_path,
            crossing_dir=crossing_dir,
            missing_crossing_files=missing_crossing_files,
        )
        st.divider()
        render_time_trend(dashboard_summary)
        st.divider()
        render_video_validation(analysis, results_dir)
        st.divider()
        render_grid_heatmap(analysis, summary, dashboard_summary)

    with artifact_tab:
        render_raw_tables(analysis, frames, events, summary, results_dir)


if __name__ == "__main__":
    main()
