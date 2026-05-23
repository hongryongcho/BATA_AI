"""
백테스트 탭 — TQQQ/SOXL 종목 선택, 종가/RSI/낙폭 차트, 성과 요약
"""
from __future__ import annotations

import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import load_backtest_data
from charts import plot_backtest_price


def render():
    st.subheader("백테스트 성과")

    # ── 종목 선택 ─────────────────────────────────────────────────
    ticker = st.radio("종목 선택", ["TQQQ", "SOXL"], horizontal=True, key="bt_ticker")

    with st.spinner(f"{ticker} 백테스트 데이터 로딩 중..."):
        df, summary = load_backtest_data(ticker)

    if df.empty:
        st.error(
            f"'{ticker}_매매기준가' 시트 데이터를 불러오지 못했습니다.\n"
            "Google Sheets 연결 및 시트명을 확인하세요."
        )
        return

    # ── 성과 요약 KPI 카드 ────────────────────────────────────────
    _render_kpi_cards(summary, df)

    st.divider()

    # ── 차트 기간 필터 ────────────────────────────────────────────
    period = st.radio(
        "기간", ["1Y", "3Y", "5Y", "전체"],
        horizontal=True, index=2, key="bt_period"
    )

    import pandas as pd
    last_date = df["날짜"].max()
    if period == "1Y":
        start = last_date - pd.DateOffset(years=1)
    elif period == "3Y":
        start = last_date - pd.DateOffset(years=3)
    elif period == "5Y":
        start = last_date - pd.DateOffset(years=5)
    else:
        start = df["날짜"].min()

    dff = df[df["날짜"] >= start].copy()

    # ── 메인 차트 ─────────────────────────────────────────────────
    st.markdown(f"#### 📈 {ticker} 종가 / RSI(2) / 전고점낙폭")
    fig = plot_backtest_price(dff, ticker)
    st.plotly_chart(fig, use_container_width=True)

    # ── 최근 데이터 테이블 ────────────────────────────────────────
    with st.expander("📋 최근 30일 데이터"):
        recent = dff.tail(30).sort_values("날짜", ascending=False).copy()
        recent["날짜"] = recent["날짜"].dt.strftime("%Y-%m-%d")
        show_cols = [c for c in ["날짜", "close", "rsi2", "fng", "chg_pct",
                                  "buy_limit_expected_px", "sell_limit_expected_px"]
                     if c in recent.columns]
        rename_map = {
            "close": "종가($)", "rsi2": "RSI(2)", "fng": "F&G",
            "chg_pct": "낙폭(%)",
            "buy_limit_expected_px": "매수예상가($)",
            "sell_limit_expected_px": "매도예상가($)",
        }
        recent = recent[show_cols].rename(columns=rename_map)
        fmt = {}
        for col in ["종가($)", "매수예상가($)", "매도예상가($)"]:
            if col in recent.columns:
                fmt[col] = "${:,.2f}"
        for col in ["RSI(2)", "F&G", "낙폭(%)"]:
            if col in recent.columns:
                fmt[col] = "{:.1f}"
        st.dataframe(recent.style.format(fmt), hide_index=True, use_container_width=True)

    st.caption(f"데이터 출처: Google Sheets {ticker}_매매기준가 탭 (5분 캐시)")


def _render_kpi_cards(summary: dict, df):
    """시트 rows 0~3에서 파싱된 성과 지표 카드"""
    if not summary and df.empty:
        return

    def _num(key: str, default=0.0) -> float:
        v = summary.get(key, "")
        try:
            return float(str(v).replace(",", "").replace("%", "").strip())
        except (ValueError, TypeError):
            return default

    total_ret = _num("총수익률") or _num("총수익률(%)")
    cagr = _num("CAGR") or _num("연평균수익률") or _num("연평균수익률CAGR(%)")
    mdd = _num("MDD") or _num("최대낙폭") or _num("최대낙폭(%)")
    final_asset = _num("최종자산") or _num("최종자산($)")

    # summary에 값 없으면 df에서 직접 계산
    if total_ret == 0.0 and "close" in df.columns and len(df) > 1:
        total_ret = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    if mdd == 0.0 and "chg_pct" in df.columns:
        mdd = df["chg_pct"].min()

    cols = st.columns(4)
    labels = ["총 수익률", "CAGR", "MDD", "최종 자산($)"]
    values_fmt = [
        f"{total_ret:.1f}%" if total_ret else "—",
        f"{cagr:.1f}%" if cagr else "—",
        f"{mdd:.1f}%" if mdd else "—",
        f"${final_asset:,.0f}" if final_asset else "—",
    ]
    # summary 원본 텍스트 우선 표시
    raw_vals = [
        summary.get("총수익률") or summary.get("총수익률(%)") or values_fmt[0],
        summary.get("CAGR") or summary.get("연평균수익률CAGR(%)") or values_fmt[1],
        summary.get("MDD") or summary.get("최대낙폭(%)") or values_fmt[2],
        summary.get("최종자산") or summary.get("최종자산($)") or values_fmt[3],
    ]
    for col, lbl, val in zip(cols, labels, raw_vals):
        with col:
            st.metric(lbl, val)

    if summary:
        remaining = {k: v for k, v in summary.items()
                     if k not in {"총수익률", "총수익률(%)", "CAGR", "연평균수익률",
                                  "연평균수익률CAGR(%)", "MDD", "최대낙폭", "최대낙폭(%)",
                                  "최종자산", "최종자산($)"}}
        if remaining:
            extra_cols = st.columns(len(remaining))
            for col, (k, v) in zip(extra_cols, remaining.items()):
                with col:
                    st.metric(k, v)
