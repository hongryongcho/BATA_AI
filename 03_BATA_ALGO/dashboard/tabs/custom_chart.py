"""
커스텀 차트 탭 — 최대 3개 시리즈 선택, 정규화/원본값 토글
"""
from __future__ import annotations

import streamlit as st
from datetime import datetime, timedelta
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import build_series
from charts import plot_custom_chart

AVAILABLE_SERIES = [
    "TQQQ", "SOXL", "SPY", "UPRO", "QLD",
    "잔고($)", "수익률(%)",
    "RSI(2)", "RSI(14)", "Fear&Greed",
]


def render():
    st.subheader("커스텀 차트")
    st.caption("최대 3개 데이터를 선택하여 비교할 수 있습니다.")

    # ── 컨트롤 패널 ──────────────────────────────────────────────
    with st.container(border=True):
        col1, col2 = st.columns([2, 1])

        with col1:
            selected = st.multiselect(
                "데이터 선택 (최대 3개)",
                AVAILABLE_SERIES,
                default=["TQQQ", "수익률(%)"],
                max_selections=3,
                help="포트폴리오, 종가, RSI, Fear&Greed 중에서 선택"
            )

        with col2:
            normalize = st.toggle("% 변화율로 정규화", value=True,
                                  help="ON: 시작일 기준 % 변화율  /  OFF: 원본값 (다중 Y축)")

        # 날짜 범위
        date_col1, date_col2, date_col3 = st.columns([2, 1, 1])
        with date_col1:
            preset = st.radio("기간", ["1M", "3M", "1Y", "3Y", "ALL"],
                              horizontal=True, index=2)
        today = datetime.today()
        preset_map = {
            "1M": today - timedelta(days=30),
            "3M": today - timedelta(days=90),
            "1Y": today - timedelta(days=365),
            "3Y": today - timedelta(days=365 * 3),
            "ALL": datetime(2019, 1, 1),
        }
        default_start = preset_map[preset]

        with date_col2:
            start_date = st.date_input("시작일", value=default_start.date())
        with date_col3:
            end_date = st.date_input("종료일", value=today.date())

    # ── 차트 렌더링 ──────────────────────────────────────────────
    if not selected:
        st.info("데이터를 1개 이상 선택하세요.")
        return

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    with st.spinner("데이터 로딩 중..."):
        series_dict = {}
        for name in selected:
            s = build_series(name, start_dt, end_dt)
            if s is not None and not s.empty:
                series_dict[name] = s
            else:
                st.warning(f"'{name}' 데이터를 불러오지 못했습니다.")

    if not series_dict:
        st.error("선택한 기간에 데이터가 없습니다.")
        return

    fig = plot_custom_chart(series_dict, normalize=normalize)
    st.plotly_chart(fig, use_container_width=True)

    # ── 기간 통계 ────────────────────────────────────────────────
    with st.expander("기간 통계"):
        cols = st.columns(len(series_dict))
        for i, (name, s) in enumerate(series_dict.items()):
            with cols[i]:
                if normalize:
                    first, last = s.iloc[0], s.iloc[-1]
                    chg = (last / first - 1) * 100 if first != 0 else 0.0
                    st.metric(name, f"{chg:+.2f}%",
                              f"{s.index[0].strftime('%Y-%m-%d')} ~ {s.index[-1].strftime('%Y-%m-%d')}")
                else:
                    st.metric(name, f"{s.iloc[-1]:.2f}",
                              f"최소: {s.min():.2f} / 최대: {s.max():.2f}")
