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
V2_PROCESSED_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "sns_trend"
    / "v2"
    / "cross_platform_signal_top_candidates"
    / "cross_platform_signal_top_candidates.json"
)

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
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .metric-container {
        background-color: #F8F9FA;
        border-radius: 10px;
        padding: 12px 18px;
        border: 1px solid #E9ECEF;
        color: #1F2937;
    }
    .candidate-card {
        background-color: #FFFFFF;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 16px;
        border: 1px solid #E5E7EB;
        border-left: 6px solid #FF4B4B;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        color: #1F2937;
    }
    .candidate-card-accepted {
        border-left: 6px solid #16A34A !important;
        background-color: #F0FDF4 !important;
    }
    .candidate-card-rejected {
        border-left: 6px solid #DC2626 !important;
        background-color: #FEF2F2 !important;
    }
    .candidate-card-held {
        border-left: 6px solid #D97706 !important;
        background-color: #FFFBEB !important;
    }
    .badge-accept {
        background-color: #DCFCE7;
        color: #15803D;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.8rem;
        border: 1px solid #86EFAC;
    }
    .badge-reject {
        background-color: #FEE2E2;
        color: #B91C1C;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.8rem;
        border: 1px solid #FCA5A5;
    }
    .badge-hold {
        background-color: #FEF3C7;
        color: #B45309;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.8rem;
        border: 1px solid #FDE047;
    }
    .badge-pending {
        background-color: #F3F4F6;
        color: #4B5563;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.8rem;
        border: 1px solid #E5E7EB;
    }
    .badge-naver {
        background-color: #E8F5E9;
        color: #2E7D32;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.75rem;
        border: 1px solid #A5D6A7;
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
    st.markdown(
        '<div class="sub-title">크로스 플랫폼 트렌드 검수 대기열 & 브랜드 마케터 승인 게이트 (Top 100 컷오프 & 2단계 빠른 검수)</div>',
        unsafe_allow_html=True,
    )

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

    # Synchronize session_state decisions with widget inputs before metrics & rendering
    for k, v in list(st.session_state.items()):
        if "_decision_" in k:
            cand_id = k.rsplit("_decision_", 1)[-1]
            existing_record = st.session_state.get("decisions", {}).get(cand_id, {})
            existing_note = existing_record.get("review_note", "")

            # Scan any widget note key matching cand_id in session_state
            typed_notes = [
                str(st.session_state[nk]).strip()
                for nk in st.session_state
                if nk.endswith(f"_note_{cand_id}") and isinstance(st.session_state[nk], str) and str(st.session_state[nk]).strip()
            ]

            if typed_notes:
                note_val = typed_notes[-1]
            else:
                note_val = existing_note

            if v != "pending":
                st.session_state["decisions"][cand_id] = {
                    "candidate_id": cand_id,
                    "review_decision": v,
                    "reviewer": st.session_state.get("reviewer_name", "reviewer_1"),
                    "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "review_note": note_val,
                    "decision_source": "streamlit",
                }
            elif cand_id in st.session_state["decisions"] and v == "pending":
                del st.session_state["decisions"][cand_id]

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

    # 2-Tier Review Tabs + User Guide + v2 Baseline Reference Tab
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "⚡ Top 20 Default Review (3분 빠른 검수)",
        "🔍 Top 100 Candidate Search & Filter (컷오프 탐색)",
        "🚀 Release & Persistence Gate",
        "📖 검수 매뉴얼 & 사용 가이드 (SOP)",
        "📌 v2 Baseline 참조 (채빈 님 20개 카드)",
    ])

    # Tab 1: Top 20 Default View
    with tab1:
        col_info, col_save = st.columns([3, 1])
        with col_info:
            st.info("💡 **시스템 추천 Top 20 카드**입니다. 3분 이내로 빠르게 검수를 진행하고 우측 버튼으로 영구 저장하세요.")
        with col_save:
            if st.button("💾 검수 내역 영구 저장", type="primary", key="quick_save_top20", use_container_width=True):
                save_and_validate_decisions(selected_week, raw_candidates)

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

        col_save, col_reset, col_trigger = st.columns(3)

        with col_save:
            st.markdown("### 1. Decisions 저장")
            if st.button("💾 Save Review Decisions to Artifacts", type="primary", use_container_width=True):
                save_and_validate_decisions(selected_week, raw_candidates)

        with col_reset:
            st.markdown("### 2. Decisions 삭제/초기화")
            if st.button("🗑️ Reset All Decisions", type="secondary", use_container_width=True):
                reset_review_decisions(selected_week)

        with col_trigger:
            st.markdown("### 3. Airflow Event-Driven Trigger")
            if st.button("🚀 Trigger Airflow Processed Release DAG", use_container_width=True):
                trigger_airflow_release_dag(selected_week, selected_run_id)

    # Tab 4: User Manual & SOP
    with tab4:
        st.markdown(
            """
            ### 📖 BrandMate 대시보드 검수 매뉴얼 

            #### 1. 2단계 검수 아키텍처 
            - **⚡ Top 20 Default Review**: Scoring 알고리즘이 선정한 최상위 20개 트렌드 후보입니다. 주간 3분 이내로 빠르게 검수를 완료하는 기본 추천 탭입니다.
            - **🔍 Top 100 Search & Filter**: 1,975개 전체 수집 데이터 중 상위 100개 컷오프 내에서 키워드/플랫폼별로 탐색하는 안전망 탭입니다.

            ---

            #### 2. 검수 메모 (`Review Note`) 작성 가이드 [★ 중요]
            `Review Note`는 단순 메모가 아니라 **후속 LLM AI 광고 생성의 품질을 결정짓는 핵심 가이드**입니다.

            - **승인 (`accept`) 시**:
              - 여기서 입력한 `Review Note`는 최종 **TrendCard의 공식 `meaning` (유래/의미/마케팅 활용법)** 필드로 자동 승격됩니다.
              -  **좋은 작성 예시**: *"좋아하는 대상을 먼저 부르고 '니가 좋아'라고 고백한 뒤 특징을 나열하는 SNS 바이럴 밈. 대표 상품명과 입력 특징을 좋아하는 이유로 연결하는 카피 생성에 적합."*
              -  **잘못된 작성 예시**: *"Good meme"*, *"좋음"*
            - **반려 (`reject`) 시**:
              - 팀원 간 공유를 위해 반려 사유를 남깁니다. (예: *"저작권/인물 패러디 위험"*, *"유행이 지난 밈"*, *"브랜드 톤앤매너 불일치"*)
            - **보류 (`hold`) 시**:
              - 보류 사유를 남깁니다. (예: *"네이버 블로그 검색량 추이 주중 재검토 필요"*)

            ---

            #### 3. 검수 완료 및 릴리스 배포 흐름
            1. **`💾 Save Review Decisions` 클릭**: 작성한 검수 결과가 `review_decisions.json`에 안전하게 저장을 완료합니다.
            2. **`🚀 Trigger Airflow Processed Release DAG` 클릭**: 승인된 카드들을 최종 `processed/v3/` 패키지로 변환하고 Airflow 무결성 검증을 거쳐 방출합니다.

            ---

            #### 4. 버저닝 정책 참고 (`Dataset Version` vs `Schema Version`)
            - **Dataset Release Version (`version: "v3"`)**: Phase 5 대시보드/릴리스 시스템이 방출하는 데이터셋 위치입니다 (`data/processed/sns_trend/v3/`).
            - **Schema Version (`schema_version: "2.0"`)**: 후속 AI 광고 생성기(LLM API)가 호환성을 갖고 읽어들이는 개별 카드 포맷 버전입니다. 하위 호환을 위해 2.0으로 기재됩니다.
            """
        )

    # Tab 5: v2 Baseline Reference (Chaebin's 20 Cards)
    with tab5:
        st.info("📌 **채빈 님이 수동으로 검수 및 작성했던 v2 Processed Baseline 20개 트렌드 카드**입니다. v3 검수 시 마케팅 가이드로 자유롭게 참조할 수 있습니다.")
        render_v2_baseline_reference()


def render_v2_baseline_reference() -> None:
    if not V2_PROCESSED_PATH.exists():
        st.warning(f"v2 Baseline 데이터셋이 존재하지 않습니다: `{V2_PROCESSED_PATH}`")
        return

    try:
        with V2_PROCESSED_PATH.open("r", encoding="utf-8") as f:
            v2_payload = json.load(f)
    except Exception as e:
        st.error(f"v2 Baseline 데이터 읽기 실패: {e}")
        return

    cards = v2_payload.get("cards", [])
    st.markdown(f"총 **{len(cards)}개**의 v2 Baseline 트렌드 카드가 등록되어 있습니다.")

    search_query = st.text_input("🔍 v2 Baseline 카드 키워드 검색", "", key="v2_search")
    filtered_cards = cards
    if search_query.strip():
        q = search_query.strip().casefold()
        filtered_cards = [
            c for c in cards
            if q in c.get("display_name", "").casefold()
            or q in c.get("meaning", "").casefold()
            or q in c.get("meme_id", "").casefold()
        ]

    for idx, card in enumerate(filtered_cards, start=1):
        display_name = card.get("display_name", "")
        meme_id = card.get("meme_id", "")
        meaning = card.get("meaning", "")
        sources = card.get("trend_meta", {}).get("sources", [])
        collected_week = card.get("trend_meta", {}).get("collected_week", "")
        patterns = card.get("text_patterns", [])
        copy_markers = card.get("copy_markers", [])

        with st.container():
            st.markdown(
                f"""
                <div class="candidate-card candidate-card-accepted">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 1.25rem; font-weight: 700; color: #111827;">#{idx} | {display_name}</span>
                        <div>
                            <span class="badge-accept">v2 BASELINE</span>
                            <span style="background-color: #E5E7EB; color: #374151; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; margin-left: 6px; font-weight: 600;">ID: {meme_id}</span>
                        </div>
                    </div>
                    <div style="margin-top: 8px; font-size: 0.9rem; color: #1F2937;">
                        <b>밈 의미/해설:</b> {meaning}
                    </div>
                    <div style="margin-top: 6px; font-size: 0.85rem; color: #4B5563;">
                        <b>Sources:</b> {', '.join(sources)} | <b>Collected Week:</b> {collected_week} | <b>Markers:</b> {', '.join(copy_markers)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander(f"📋 '{display_name}' 카피 패턴 및 세부 규칙"):
                st.markdown("**Text Patterns:**")
                for p in patterns:
                    st.code(p, language="text")
                if card.get("usage_rules"):
                    st.markdown("**Usage Rules:**")
                    for rule in card["usage_rules"]:
                        st.markdown(f"- {rule}")
                if card.get("prohibited_usage"):
                    st.markdown("**Prohibited Usage:**")
                    for prob in card["prohibited_usage"]:
                        st.markdown(f"- ❌ {prob}")
            st.markdown("---")


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

        radio_key = f"{key_prefix}_decision_{cand_id}"
        current_decision = st.session_state.get(
            radio_key, decisions_map.get(cand_id, {}).get("review_decision", "pending")
        )

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
                        <span style="font-size: 1.25rem; font-weight: 700; color: #111827;">Rank #{rank} | {display_term}</span>
                        <div>
                            {badge_html}
                            <span style="background-color: #E5E7EB; color: #374151; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; margin-left: 6px; font-weight: 600;">ID: {cand_id}</span>
                        </div>
                    </div>
                    <div style="margin-top: 8px; font-size: 0.88rem; color: #4B5563;">
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

                existing_note = decisions_map.get(cand_id, {}).get("review_note", "")
                note_key = f"{key_prefix}_note_{cand_id}"
                if note_key not in st.session_state:
                    st.session_state[note_key] = existing_note

                review_note = st.text_input(
                    "Review Note",
                    key=note_key,
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
                final_note = review_note if review_note else existing_note
                st.session_state["decisions"][cand_id] = {
                    "candidate_id": cand_id,
                    "review_decision": new_decision,
                    "reviewer": st.session_state.get("reviewer_name", "reviewer_1"),
                    "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "review_note": final_note,
                    "decision_source": "streamlit",
                }
            elif cand_id in st.session_state["decisions"] and new_decision == "pending":
                del st.session_state["decisions"][cand_id]

            st.markdown("---")


def sync_all_widget_decisions_to_session() -> None:
    """Scans all Streamlit widget state keys and ensures st.session_state['decisions'] is 100% up-to-date."""
    if "decisions" not in st.session_state:
        st.session_state["decisions"] = {}

    cand_decisions: dict[str, str] = {}
    cand_notes: dict[str, str] = {}

    # Aggregate widget keys by candidate_id, prioritizing non-pending decisions
    for k, v in list(st.session_state.items()):
        if "_decision_" in k:
            cand_id = k.rsplit("_decision_", 1)[-1]
            if v != "pending" or cand_id not in cand_decisions:
                cand_decisions[cand_id] = v
        elif "_note_" in k:
            cand_id = k.rsplit("_note_", 1)[-1]
            note_str = str(v).strip()
            if note_str:
                cand_notes[cand_id] = note_str

    for cand_id, decision_val in cand_decisions.items():
        existing_record = st.session_state["decisions"].get(cand_id, {})
        existing_note = existing_record.get("review_note", "")

        note_val = cand_notes.get(cand_id, existing_note)

        if decision_val != "pending":
            st.session_state["decisions"][cand_id] = {
                "candidate_id": cand_id,
                "review_decision": decision_val,
                "reviewer": st.session_state.get("reviewer_name", "reviewer_1"),
                "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "review_note": note_val,
                "decision_source": "streamlit",
            }
        elif cand_id in st.session_state["decisions"] and decision_val == "pending":
            # Only remove if decision is truly pending across all widget keys
            active_decisions = [
                st.session_state[wk] for wk in st.session_state
                if wk.endswith(f"_decision_{cand_id}") and st.session_state[wk] != "pending"
            ]
            if not active_decisions:
                st.session_state["decisions"].pop(cand_id, None)


def save_and_validate_decisions(week: str, queue_candidates: list[dict[str, Any]]) -> None:
    # Always force sync all widget states in session_state before validation and disk save
    sync_all_widget_decisions_to_session()

    raw_decisions_map = st.session_state.get("decisions", {})
    if not raw_decisions_map:
        st.warning("저장할 검수 내역이 없습니다.")
        return

    valid_ids = {c["candidate_id"] for c in queue_candidates}
    decision_records: list[ReviewDecisionRecord] = []
    
    # Clean and filter decisions to only include candidates existing in the current queue payload
    cleaned_decisions = {}
    for cand_id, d_dict in raw_decisions_map.items():
        if cand_id in valid_ids:
            cleaned_decisions[cand_id] = d_dict
            try:
                record = ReviewDecisionRecord.from_dict(d_dict)
                decision_records.append(record)
            except ReviewDecisionError as e:
                st.error(f"결정 객체 변환 오류: {e}")
                return
    
    st.session_state["decisions"] = cleaned_decisions

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


def trigger_airflow_release_dag(week: str, run_id: str = "") -> None:
    airflow_url = os.getenv("AIRFLOW_URL", "http://localhost:8080")
    dag_id = "sns_trend_processed_release"
    auth = ("admin", os.getenv("AIRFLOW_ADMIN_PASSWORD", "admin"))

    # 1. Unpause DAG automatically via PATCH API if it's currently paused
    unpause_endpoint = f"{airflow_url}/api/v1/dags/{dag_id}"
    try:
        requests.patch(
            unpause_endpoint,
            json={"is_paused": False},
            auth=auth,
            timeout=5,
        )
    except Exception as e:
        st.caption(f"Unpause API 시도 경고: {e}")

    # 2. Trigger DAG via POST API
    endpoint = f"{airflow_url}/api/v1/dags/{dag_id}/dagRuns"
    st.info(f"Airflow REST API 호출 시도: `POST {endpoint}`")
    payload = {
        "conf": {
            "week": week,
            "run_id": run_id,
            "triggered_by": "streamlit_dashboard",
        }
    }

    try:
        response = requests.post(
            endpoint,
            json=payload,
            auth=auth,
            timeout=5,
        )
        if response.status_code in (200, 201):
            st.success(f"🎉 Processed Release DAG 자동 활성화(Unpause) 및 트리거 성공! (HTTP {response.status_code})")
            st.json(response.json())
        else:
            st.warning(f"Airflow 응답 상태 코드: {response.status_code}")
            st.code(response.text)
    except Exception as err:
        st.warning(f"Airflow 연결 실패 (로컬 개발 모드 또는 Airflow 미기동): {err}")
        st.info(f"💡 CLI 수동 트리거 명령예시: `PYTHONPATH=gather_data python -m review_queue.release_cli --week {week}`")


def reset_review_decisions(week: str) -> None:
    """Resets all decisions in session state and removes saved decision files on disk."""
    st.session_state["decisions"] = {}

    for k in list(st.session_state.keys()):
        if "_decision_" in k or k.startswith("decision_"):
            st.session_state[k] = "pending"
        elif "_note_" in k or k.startswith("note_"):
            st.session_state[k] = ""

    out_dir = DECISIONS_ROOT / f"week={week}"
    json_path = out_dir / "sns_trend_review_decisions.json"
    csv_path = out_dir / "sns_trend_review_decisions.csv"

    if json_path.exists():
        json_path.unlink()
    if csv_path.exists():
        csv_path.unlink()

    st.success("🗑️ 검수 내역이 성공적으로 초기화되었습니다! (디스크 파일 및 세션 리셋 완료)")
    st.rerun()


if __name__ == "__main__":
    main()
