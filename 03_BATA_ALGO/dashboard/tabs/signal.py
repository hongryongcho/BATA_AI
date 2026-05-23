"""
오늘의 신호 탭 — RSI(2), F&G 현황 카드, 매매 신호
"""
from __future__ import annotations

import streamlit as st
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import (
    load_fng_signals, load_fear_greed, load_realtime_price, compute_rsi, load_price_history
)
from charts import plot_gauge


def render():
    st.subheader("오늘의 신호")

    col1, col2, col3 = st.columns(3)

    # ── Fear & Greed ─────────────────────────────────────────────
    with col1:
        with st.spinner("F&G 조회 중..."):
            fng = load_fear_greed()
        fng_val = fng.get("value", 50)
        fng_label = fng.get("label", "Neutral")
        fng_src = fng.get("source", "").upper()

        st.plotly_chart(
            plot_gauge(fng_val, f"Fear & Greed ({fng_src})", danger_low=25, danger_high=75),
            use_container_width=True
        )
        if fng_val <= 25:
            st.success(f"😨 **{fng_label}** — 매수 우호적 구간")
        elif fng_val >= 75:
            st.error(f"🤑 **{fng_label}** — 매도 우호적 구간")
        else:
            st.info(f"😐 **{fng_label}**")

    # ── RSI(2) TQQQ ──────────────────────────────────────────────
    with col2:
        _render_rsi_gauge("TQQQ")

    # ── RSI(2) SOXL ──────────────────────────────────────────────
    with col3:
        _render_rsi_gauge("SOXL")

    st.divider()

    # ── 현재가 카드 ──────────────────────────────────────────────
    st.markdown("#### 현재가")
    pcols = st.columns(5)
    for i, ticker in enumerate(["TQQQ", "SOXL", "SPY", "UPRO", "QLD"]):
        with pcols[i]:
            info = load_realtime_price(ticker)
            price = info.get("price")
            chg = info.get("change_pct", 0.0)
            if price:
                color = "green" if chg >= 0 else "red"
                sign = "+" if chg >= 0 else ""
                st.metric(ticker, f"${price:.2f}", f"{sign}{chg:.2f}%",
                          delta_color="normal" if chg >= 0 else "inverse")
            else:
                st.metric(ticker, "N/A", "")

    st.divider()

    # ── 매매 신호 ────────────────────────────────────────────────
    st.markdown("#### 📋 다음날 예약 주문 (RSI2+F&G 기준)")
    with st.spinner("신호 로딩 중..."):
        signals = load_fng_signals()

    if not signals:
        st.info("Google Sheets에서 신호를 불러오지 못했습니다. (Summary 탭 확인 필요)")
    else:
        for sig in signals:
            ticker = sig.get("ticker", "")
            state = sig.get("current_state", "")
            next_action = sig.get("next_action", "")
            strategy = sig.get("strategy", "")

            if "BUY" in next_action.upper() or "매수" in next_action:
                icon, color = "🟢", "green"
            elif "SELL" in next_action.upper() or "매도" in next_action:
                icon, color = "🔴", "red"
            else:
                icon, color = "⚪", "gray"

            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 2, 2])
                with c1:
                    st.markdown(f"### {icon} **{ticker}**")
                with c2:
                    st.markdown(f"**현재 상태:** {state}")
                    st.markdown(f"**전략:** {strategy}")
                with c3:
                    st.markdown(f"**다음 액션:**")
                    st.markdown(f"#### `{next_action}`")

    st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (5분 캐시)")


def _render_rsi_gauge(ticker: str):
    with st.spinner(f"{ticker} RSI 계산 중..."):
        df = load_price_history(ticker, period="1y")
    if df.empty:
        st.warning(f"{ticker} 데이터 없음")
        return
    rsi = compute_rsi(df["close"], period=2)
    rsi_val = float(rsi.iloc[-1]) if not rsi.empty else 50.0

    st.plotly_chart(
        plot_gauge(rsi_val, f"RSI(2) — {ticker}", danger_low=15, danger_high=85),
        use_container_width=True
    )
    if rsi_val < 15:
        st.success(f"📉 RSI {rsi_val:.1f} — **매수 신호**")
    elif rsi_val > 85:
        st.error(f"📈 RSI {rsi_val:.1f} — **매도 신호**")
    else:
        st.info(f"RSI {rsi_val:.1f} — 중립")
