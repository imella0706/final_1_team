from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any

import requests
import streamlit as st

# Add gather_data to sys.path so we can import review_queue domain logic
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATHER_DATA_DIR = PROJECT_ROOT / "gather_data"
if str(GATHER_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(GATHER_DATA_DIR))

from review_queue.contracts import (  # noqa: E402
    DecisionValidationError,
    ReviewDecisionError,
    ReviewDecisionRecord,
)
from review_queue.decisions import (  # noqa: E402
    load_review_decisions,
    save_review_decisions,
    validate_review_decisions,
)

# Constants
CURATED_ROOT = PROJECT_ROOT / "data" / "curated" / "sns_trend" / "v3"
QUEUE_ROOT = CURATED_ROOT / "review_queue"
DECISIONS_ROOT = CURATED_ROOT / "review_decisions"
TOP_K_CUTOFF = 100
DEFAULT_TOP_COUNT = 20

st.set_page_config(
    page_title="BrandMate SNS TrendCard Review Dashboard",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern UI
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #FF4B4B 0%, #FF8F00 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.0rem;
        color: #888888;
        margin-bottom: 1.5rem;
    }
    .metric-container {
        background-color: #1E1E2F;
        border-radius: 10px;
        padding: 12px 18px;
        border: 1px solid #33334B;
    }
    .candidate-card {
        background-color: #161625;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 16px;
        border-left: 5px solid #FF4B4B;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .candidate-card-accepted {
        border-left: 5px solid #00C853 !important;
    }
    .candidate-card-rejected {
        border-left: 5px solid #D50000 !important;
    }
    .candidate-card-held {
        border-left: 5px solid #FFD600 !important;
    }
    .badge-accept {
        background-color: #1b5e20;
        color: #81c784;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .badge-reject {
        background-color: #b71c1c;
        color: #ef9a9a;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .badge-hold {
        background-color: #f57f17;
        color: #fff59d;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .badge-pending {
        background-color: #424242;
        color: #e0e0e0;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .badge-naver {
        background-color: #03cf5d;
        color: #ffffff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.75rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def discover_available_weeks() -> list[str]:
    if not QUEUE_ROOT.exists():
        return []
    weeks = [d.name.replace("week=", "") for d in QUEUE_ROOT.glob("week=*") if d.is_dir()]
    return sorted(weeks, reverse=True)


def discover_runs_for_week(week: str) -> list[str]:
    week_dir = QUEUE_ROOT / f"week={week}"
    if not week_dir.exists():
        return []
    runs = [d.name.replace("run_id=", "") for d in week_dir.glob("run_id=*") if d.is_dir()]
    return sorted(runs, reverse=True)


def load_queue_file(week: str, run_id: str) -> tuple[dict[str, Any], Path | None]:
    target_dir = QUEUE_ROOT / f"week={week}" / f"run_id={run_id}"
    json_file = target_dir / "sns_trend_review_queue.json"
    if not json_file.exists():
        return {}, None
    with json_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload, json_file


def init_session_state(week: str) -> None:
    if "reviewer_name" not in st.session_state:
        st.session_state["reviewer_name"] = os.getenv("USER", "reviewer_1")

    decisions_file = DECISIONS_ROOT / f"week={week}" / "sns_trend_review_decisions.json"
    if "loaded_week" not in st.session_state or st.session_state["loaded_week"] != week:
        st.session_state["loaded_week"] = week
        st.session_state["decisions"] = {}

        if decisions_file.exists():
            try:
                existing = load_review_decisions(decisions_file)
                for item in existing:
                    st.session_state["decisions"][item.candidate_id] = item.to_dict()
            except Exception as e:
                st.sidebar.error(f"기존 decision 파일 로드 경고: {e}")


def main() -> None:
    st.markdown('<div class="main-title">🔥 BrandMate SNS TrendCard Review Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Phase 5-6: Cross-Platform Review Queue & Human Approval Gate (Top 100 Cut-off & 2-Tier Review)</div>', unsafe_allow_html=True)

    # Sidebar setup
    st.sidebar.header("⚙️ Context & Dataset Selector")

    weeks = discover_available_weeks()
    if not weeks:
        st.error(f"리뷰 큐 데이터가 존재하지 않습니다: `{QUEUE_ROOT}`")
        st.info("Airflow `sns_trend_review_queue_build` 또는 `build_review_queue.py`를 먼저 실행하세요.")
        return

    selected_week = st.sidebar.selectbox("📅 ISO Week", weeks, index=0)
    init_session_state(selected_week)

    runs = discover_runs_for_week(selected_week)
    if not runs:
        st.error(f"주차 `{selected_week}`에 대한 run이 없습니다.")
        return

    selected_run_id = st.sidebar.selectbox("🚀 Airflow / CLI Run ID", runs, index=0)

    st.sidebar.markdown("---")
    st.sidebar.subheader("👤 Reviewer Metadata")
    reviewer_name = st.sidebar.text_input("Reviewer Name", value=st.session_state.get("reviewer_name", "reviewer_1"))
    st.session_state["reviewer_name"] = reviewer_name

    # Load Queue Data
    queue_payload, _ = load_queue_file(selected_week, selected_run_id)
    if not queue_payload:
        st.error("리뷰 큐 JSON을 불러오지 못했습니다.")
        return

    raw_candidates = queue_payload.get("candidates", [])
    # Apply Top-100 Cutoff for safety net & noise reduction
    top_100_candidates = raw_candidates[:TOP_K_CUTOFF]

    # Metrics Calculations
    decisions_map = st.session_state.get("decisions", {})
    accepted_ids = [cid for cid, d in decisions_map.items() if d.get("review_decision") == "accept"]
    rejected_ids = [cid for cid, d in decisions_map.items() if d.get("review_decision") == "reject"]
    held_ids = [cid for cid, d in decisions_map.items() if d.get("review_decision") == "hold"]
    pending_count = max(0, len(top_100_candidates) - len(decisions_map))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Top Cut-off Queue", f"{len(top_100_candidates)} / {len(raw_candidates)}")
    m2.metric("Accepted (승인)", f"{len(accepted_ids)}", delta=f"{len(accepted_ids)} selected", delta_color="normal")
    m3.metric("Rejected (반려)", f"{len(rejected_ids)}")
    m4.metric("Held (보류)", f"{len(held_ids)}")
    m5.metric("Pending (미검수)", f"{pending_count}")

    st.markdown("---")

    # 2-Tier Review Tabs
    tab1, tab2, tab3 = st.tabs([
        "⚡ Top 20 Default Review (3분 빠른 검수)",
        "🔍 Top 100 Candidate Search & Filter (컷오프 탐색)",
        "🚀 Release & Persistence Gate",
    ])

    # Tab 1: Top 20 Default View
    with tab1:
        st.info("💡 **시스템 추천 Top 20 카드**입니다. 주간 트렌드 신호가 가장 강력한 항목이며, 3분 이내로 빠르게 검수를 진행할 수 있습니다.")
        top_20_candidates = top_100_candidates[:DEFAULT_TOP_COUNT]
        render_candidate_list(top_20_candidates, selected_week, key_prefix="top20")

    # Tab 2: Top 100 Candidate Search & Filter
    with tab2:
        st.subheader("🔍 Top 100 컷오프 후보 탐색 & 검색")
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            search_query = st.text_input("🔎 키워드/후보명 검색", value="", placeholder="예: 위고비, 버리지않아")
        with c2:
            sources_filter = st.multiselect(
                "📡 Source Filter",
                ["youtube", "gogumafarm", "careet", "naver"],
                default=["youtube", "gogumafarm", "careet", "naver"],
            )
        with c3:
            max_score = max([c.get("rank", 100) for c in top_100_candidates], default=100)
            max_rank_filter = st.slider("📊 Max Rank (순위 범위)", 1, max(20, max_score), value=TOP_K_CUTOFF)

        # Filter logic
        filtered = []
        for cand in top_100_candidates:
            if cand.get("rank", 999) > max_rank_filter:
                continue
            term_match = not search_query or (
                search_query.casefold() in cand.get("term", "").casefold()
                or search_query.casefold() in cand.get("display_term", "").casefold()
            )
            source_match = any(sf in sources_filter for sf in cand.get("source_families", []))
            if term_match and source_match:
                filtered.append(cand)

        st.caption(f"검색 조건 만족 후보: **{len(filtered)}** 건 (Top {TOP_K_CUTOFF} 컷오프 대상)")
        render_candidate_list(filtered, selected_week, key_prefix="search")

    # Tab 3: Release & Persistence Gate
    with tab3:
        st.subheader("💾 Review Decisions Persistence & Processed Release")
        st.write("대시보드에서 선택한 검수 결과(`accept/reject/hold`)를 저장하고, Processed Release DAG를 트리거합니다.")

        col_save, col_trigger = st.columns(2)

        with col_save:
            st.markdown("### 1. Decisions 저장")
            if st.button("💾 Save Review Decisions to Artifacts", type="primary", use_container_width=True):
                save_and_validate_decisions(selected_week, top_100_candidates)

        with col_trigger:
            st.markdown("### 2. Airflow Event-Driven Trigger")
            if st.button("🚀 Trigger Airflow Processed Release DAG", use_container_width=True):
                trigger_airflow_release_dag(selected_week)


def render_candidate_list(candidates: list[dict[str, Any]], week: str, key_prefix: str) -> None:
    if not candidates:
        st.warning("조건에 부합하는 후보가 없습니다.")
        return

    decisions_map = st.session_state.get("decisions", {})

    for cand in candidates:
        cand_id = cand["candidate_id"]
        rank = cand.get("rank", "-")
        display_term = cand.get("display_term", cand.get("term", ""))
        eligible = cand.get("eligible_for_processed", True)
        usage_policy = cand.get("usage_policy", "candidate")
        sources = cand.get("source_families", [])

        current_decision = decisions_map.get(cand_id, {}).get("review_decision", "pending")

        # Card container class
        card_class = "candidate-card"
        if current_decision == "accept":
            card_class += " candidate-card-accepted"
            badge_html = '<span class="badge-accept">ACCEPTED</span>'
        elif current_decision == "reject":
            card_class += " candidate-card-rejected"
            badge_html = '<span class="badge-reject">REJECTED</span>'
        elif current_decision == "hold":
            card_class += " candidate-card-held"
            badge_html = '<span class="badge-hold">HELD</span>'
        else:
            badge_html = '<span class="badge-pending">PENDING</span>'

        with st.container():
            st.markdown(
                f"""
                <div class="{card_class}">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 1.25rem; font-weight: 700;">Rank #{rank} | {display_term}</span>
                        <div>
                            {badge_html}
                            <span style="background-color: #333; color: #aaa; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-left: 6px;">ID: {cand_id}</span>
                        </div>
                    </div>
                    <div style="margin-top: 6px; font-size: 0.85rem; color: #aaa;">
                        <b>Sources:</b> {', '.join(sources)} | <b>Policy:</b> {usage_policy} | <b>Processed Eligible:</b> {'✅ Yes' if eligible else '❌ No (Reference-only)'}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Interactive decision form for candidate
            col_form, col_meta = st.columns([3, 2])
            with col_form:
                opts = ["pending", "accept", "reject", "hold"]
                current_idx = opts.index(current_decision) if current_decision in opts else 0
                new_decision = st.radio(
                    f"Decision for {cand_id}",
                    ["pending", "accept", "reject", "hold"],
                    index=current_idx,
                    key=f"{key_prefix}_decision_{cand_id}",
                    horizontal=True,
                    label_visibility="collapsed",
                )

                if not eligible or usage_policy == "reference_only":
                    if new_decision == "accept":
                        st.error("⚠️ Naver-only / Reference-only 후보는 `accept`할 수 없습니다 (P5-5 Validator 규칙).")

                review_note = st.text_input(
                    "Review Note",
                    value=decisions_map.get(cand_id, {}).get("review_note", ""),
                    key=f"{key_prefix}_note_{cand_id}",
                    placeholder="검수 메모 작성 (선택)",
                )

            with col_meta:
                with st.expander("📊 Score Breakdown & Lineage"):
                    score_breakdown = cand.get("score_breakdown", {})
                    st.json(score_breakdown)
                    if cand.get("evidence_urls"):
                        st.markdown("**Evidence URLs:**")
                        for url in cand["evidence_urls"]:
                            st.markdown(f"- [{url}]({url})")

            # Update session state if decision changed
            if new_decision != "pending":
                st.session_state["decisions"][cand_id] = {
                    "candidate_id": cand_id,
                    "review_decision": new_decision,
                    "reviewer": st.session_state.get("reviewer_name", "reviewer_1"),
                    "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "review_note": review_note,
                    "decision_source": "streamlit",
                }
            elif cand_id in st.session_state["decisions"] and new_decision == "pending":
                del st.session_state["decisions"][cand_id]

            st.markdown("---")


def save_and_validate_decisions(week: str, queue_candidates: list[dict[str, Any]]) -> None:
    raw_decisions_map = st.session_state.get("decisions", {})
    if not raw_decisions_map:
        st.warning("저장할 검수 내역이 없습니다.")
        return

    decision_records: list[ReviewDecisionRecord] = []
    for d_dict in raw_decisions_map.values():
        try:
            record = ReviewDecisionRecord.from_dict(d_dict)
            decision_records.append(record)
        except ReviewDecisionError as e:
            st.error(f"결정 객체 변환 오류: {e}")
            return

    # Validate decisions against queue candidates
    try:
        summary = validate_review_decisions(decision_records, queue_candidates)
    except DecisionValidationError as ve:
        st.error(f"❌ P5-5 Decision Validator 검증 실패: {ve}")
        return

    out_dir = DECISIONS_ROOT / f"week={week}"
    json_path = out_dir / "sns_trend_review_decisions.json"
    csv_path = out_dir / "sns_trend_review_decisions.csv"

    save_paths = save_review_decisions(decision_records, json_path, csv_path)
    st.success(f"✅ 검수 내역 저장 및 P5-5 Validator 통과 완료!\n- JSON: `{save_paths['json_path']}`\n- CSV: `{save_paths['csv_path']}`")
    st.json(summary)


def trigger_airflow_release_dag(week: str) -> None:
    airflow_url = os.getenv("AIRFLOW_URL", "http://localhost:8080")
    dag_id = "sns_trend_processed_release"
    endpoint = f"{airflow_url}/api/v1/dags/{dag_id}/dagRuns"

    st.info(f"Airflow REST API 호출 시도: `POST {endpoint}`")
    payload = {
        "conf": {
            "week": week,
            "triggered_by": "streamlit_dashboard",
        }
    }

    try:
        response = requests.post(
            endpoint,
            json=payload,
            auth=("admin", os.getenv("AIRFLOW_ADMIN_PASSWORD", "admin")),
            timeout=5,
        )
        if response.status_code in (200, 201):
            st.success(f"🎉 Processed Release DAG 트리거 성공! (HTTP {response.status_code})")
            st.json(response.json())
        else:
            st.warning(f"Airflow 응답 상태 코드: {response.status_code}")
            st.code(response.text)
    except Exception as err:
        st.warning(f"Airflow 연결 실패 (로컬 개발 모드 또는 Airflow 미기동): {err}")
        st.info(f"💡 CLI 수동 트리거 명령예시: `PYTHONPATH=gather_data python -m review_queue.release_cli --week {week}`")


if __name__ == "__main__":
    main()
