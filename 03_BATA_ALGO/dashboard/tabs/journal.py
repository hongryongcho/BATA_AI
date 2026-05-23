"""
투자 일지 탭 — 내일의 투자 전략 + 오늘의 투자 다짐
"""
from __future__ import annotations

import streamlit as st
from datetime import date
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import get_current_user
from db import get_journal, upsert_journal, get_journal_by_date


def render():
    user = get_current_user()
    if user is None:
        st.info("로그인이 필요합니다.")
        return

    st.subheader("투자 일지")

    tab_write, tab_history = st.tabs(["✏️ 오늘 작성", "📚 지난 일지"])

    # ── 작성 탭 ──────────────────────────────────────────────────
    with tab_write:
        entry_date = st.date_input("날짜", value=date.today())

        # 기존 데이터 로드 (날짜 변경 시 반영)
        existing = get_journal_by_date(user["id"], entry_date)
        default_strategy = existing.get("strategy", "") if existing else ""
        default_resolution = existing.get("resolution", "") if existing else ""

        with st.container(border=True):
            st.markdown("#### 📌 내일의 투자 전략")
            strategy = st.text_area(
                "내일 예상 시나리오와 대응 전략을 작성하세요",
                value=default_strategy,
                height=160,
                placeholder="예: TQQQ RSI(2)가 15 이하 접근 중. 내일 장 초반 가격 확인 후 1분할 매수 고려.\n"
                            "F&G가 30 이하이면 적극 매수, 50 이상이면 관망.",
                label_visibility="collapsed"
            )

        with st.container(border=True):
            st.markdown("#### 💪 오늘의 투자 다짐")
            resolution = st.text_area(
                "오늘의 투자 원칙과 다짐",
                value=default_resolution,
                height=120,
                placeholder="예: 알고리즘 신호를 믿고 감정적 매매를 하지 않는다.\n"
                            "목표 수익률 도달 시 반드시 분할 매도한다.",
                label_visibility="collapsed"
            )

        if st.button("저장", type="primary", use_container_width=True):
            if not strategy.strip() and not resolution.strip():
                st.warning("전략 또는 다짐을 입력하세요.")
            else:
                ok = upsert_journal(user["id"], entry_date, strategy, resolution)
                if ok:
                    st.success(f"✅ {entry_date} 일지 저장 완료!")
                    st.cache_data.clear()

    # ── 히스토리 탭 ──────────────────────────────────────────────
    with tab_history:
        search_date = st.date_input("날짜 검색", value=None, key="journal_search")

        if search_date:
            entries = [get_journal_by_date(user["id"], search_date)]
            entries = [e for e in entries if e]
        else:
            with st.spinner("일지 로딩 중..."):
                entries = get_journal(user["id"], limit=30)

        if not entries:
            st.info("작성된 일지가 없습니다.")
        else:
            for entry in entries:
                entry_dt = entry.get("entry_date", "")
                strategy_text = entry.get("strategy", "")
                resolution_text = entry.get("resolution", "")
                updated = entry.get("updated_at", "")[:10] if entry.get("updated_at") else ""

                with st.expander(f"📅 {entry_dt}  *(수정: {updated})*", expanded=(entry_dt == str(date.today()))):
                    if strategy_text:
                        st.markdown("**📌 내일의 투자 전략**")
                        st.markdown(f"> {strategy_text.replace(chr(10), chr(10) + '> ')}")
                    if resolution_text:
                        st.markdown("**💪 오늘의 투자 다짐**")
                        st.markdown(f"> {resolution_text.replace(chr(10), chr(10) + '> ')}")
