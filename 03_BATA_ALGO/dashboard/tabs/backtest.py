"""
백테스트 탭 — TQQQ/SOXL 종목 선택, 종가/RSI/낙폭 차트, 사이클 현황
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import load_backtest_data, load_qqq_guard_backtest_data, extract_cycles
from charts import plot_backtest_price
from auth import is_logged_in


def render():
    st.subheader("백테스트 성과")

    # ── 알고리즘 + 종목 선택 ──────────────────────────────────────
    c_algo, c_ticker = st.columns(2)
    with c_algo:
        algo = st.radio(
            "알고리즘",
            ["RSI(2)+F&G+QQQ가드 (현재)", "RSI(2)+F&G (기존)"],
            horizontal=True, key="bt_algo"
        )
    with c_ticker:
        ticker = st.radio("종목 선택", ["TQQQ", "SOXL"], horizontal=True, key="bt_ticker")

    use_guard = algo.startswith("RSI(2)+F&G+QQQ가드")

    with st.spinner(f"{ticker} 백테스트 데이터 로딩 중..."):
        if use_guard:
            df, summary = load_qqq_guard_backtest_data(ticker)
        else:
            df, summary = load_backtest_data(ticker)

    if df.empty:
        src = "QQQ Guard" if use_guard else "F&G"
        st.error(
            f"'{ticker}_매매기준가' ({src}) 시트 데이터를 불러오지 못했습니다.\n"
            "Google Sheets 연결 및 시트명을 확인하세요."
        )
        return

    # ── 전체 사이클 추출 (기간 필터 전 원본 df 기준) ──────────────
    all_cycles = extract_cycles(df)

    # ── 성과 요약 KPI 카드 ────────────────────────────────────────
    _render_kpi_cards(summary, df, all_cycles)

    st.divider()

    # ── 차트 기간 필터 ────────────────────────────────────────────
    period = st.radio(
        "기간", ["1Y", "3Y", "5Y", "전체"],
        horizontal=True, index=3, key="bt_period"
    )

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

    # 화면에 보이는 기간에 걸치는 사이클만 음영 처리
    visible_cycles = [
        c for c in all_cycles
        if c["_end"] >= dff["날짜"].min() and c["_start"] <= dff["날짜"].max()
    ]

    # ── 메인 차트 ─────────────────────────────────────────────────
    st.markdown(f"#### 📈 {ticker} 종가 / RSI(2) / 전고점낙폭")
    st.caption("🟩 녹색 음영 = 보유 기간 (매수 → 매도), 🟧 주황 = 현재 보유 중")
    fig = plot_backtest_price(dff, ticker, cycles=visible_cycles)
    st.plotly_chart(fig, use_container_width=True)

    # ── 사이클 현황 ───────────────────────────────────────────────
    _render_cycle_section(all_cycles)

    # ── 최근 30일 데이터 테이블 ───────────────────────────────────
    with st.expander("📋 최근 30일 데이터"):
        recent = dff.tail(30).sort_values("날짜", ascending=False).copy()
        recent["날짜"] = recent["날짜"].dt.strftime("%Y-%m-%d")
        if use_guard:
            show_cols = [c for c in ["날짜", "close", "rsi2", "fng", "qqq_chg_pct",
                                      "cooldown_days", "fng_blocked",
                                      "buy_limit_expected_px", "sell_limit_expected_px"]
                         if c in recent.columns]
            rename_map = {
                "close": "종가($)", "rsi2": "RSI(2)", "fng": "F&G",
                "qqq_chg_pct": "QQQ변화%", "cooldown_days": "쿨다운(일)",
                "fng_blocked": "차단사유",
                "buy_limit_expected_px": "매수예상가($)",
                "sell_limit_expected_px": "매도예상가($)",
            }
        else:
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
        for col in ["RSI(2)", "F&G", "낙폭(%)", "QQQ변화%"]:
            if col in recent.columns:
                fmt[col] = "{:.1f}"
        st.dataframe(recent.style.format(fmt, na_rep="—"), hide_index=True, use_container_width=True)

    algo_label = "F&G+QQQ가드" if use_guard else "F&G"
    st.caption(f"데이터 출처: Google Sheets {ticker}_매매기준가 탭 ({algo_label}, 5분 캐시)")

    # ── 로그인 시 Google Sheets 원본 링크 표시 ────────────────────
    if is_logged_in():
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from _env_loader import get_qqq_guard_spreadsheet_id, get_spreadsheet_id
            sheet_id = get_qqq_guard_spreadsheet_id() if use_guard else get_spreadsheet_id()
            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            st.divider()
            st.markdown(
                f"📊 **백테스트 원본 시트** ({algo_label} / {ticker}): "
                f"[Google Sheets에서 열기 ↗]({sheet_url})"
            )
        except Exception:
            pass


# ── 사이클 현황 섹션 ─────────────────────────────────────────────

def _render_cycle_section(cycles: list[dict]):
    with st.expander("📊 사이클 현황 (전체)", expanded=True):
        if not cycles:
            st.info("사이클 데이터가 없습니다.")
            return

        done = [c for c in cycles if c["상태"] == "완료"]
        active = [c for c in cycles if c["상태"] == "보유중"]

        # ── 현재 보유 중 배너 ──────────────────────────────────
        if active:
            ac = active[0]
            ret_str = (f"{ac['수익률(%)']:+.1f}%"
                       if ac.get("수익률(%)") is not None else "—")
            st.info(
                f"🟡 **현재 보유 중** — 사이클 {ac['사이클']}  |  "
                f"매수일 {ac['매수일'].strftime('%Y-%m-%d')}  |  "
                f"매수가 ${ac['매수가($)']:,.2f}  |  "
                f"{ac['보유기간(일)']}일 경과  |  "
                f"미실현 {ret_str}"
            )

        # ── 요약 메트릭 ────────────────────────────────────────
        if done:
            returns = [c["수익률(%)"] for c in done]
            wins = [r for r in returns if r > 0]
            hold_days = [c["보유기간(일)"] for c in done]

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("완료 사이클", f"{len(done)}회")
            with c2:
                win_rate = len(wins) / len(returns) * 100
                st.metric("승률", f"{win_rate:.0f}%  ({len(wins)}/{len(returns)})")
            with c3:
                avg_ret = sum(returns) / len(returns)
                delta_color = "normal" if avg_ret >= 0 else "inverse"
                st.metric("평균 수익률", f"{avg_ret:+.2f}%")
            with c4:
                avg_days = sum(hold_days) / len(hold_days)
                st.metric("평균 보유기간", f"{avg_days:.0f}일")

        st.divider()

        # ── 사이클 테이블 (최신순) ─────────────────────────────
        rows = []
        for c in reversed(cycles):
            rows.append({
                "#": c["사이클"],
                "매수일": c["매수일"].strftime("%Y-%m-%d") if c["매수일"] else "",
                "매수가($)": c["매수가($)"],
                "매도일": c["매도일"].strftime("%Y-%m-%d") if c["매도일"] else "진행중",
                "매도가($)": c["매도가($)"],
                "보유(일)": c["보유기간(일)"],
                "수익률(%)": c["수익률(%)"],
                "상태": "🟡" if c["상태"] == "보유중" else "✅",
            })
        cdf = pd.DataFrame(rows)

        def _color_ret(val):
            try:
                v = float(val)
                if v > 0:
                    return "color: #2ca02c; font-weight: bold"
                if v < 0:
                    return "color: #d62728; font-weight: bold"
            except (TypeError, ValueError):
                pass
            return ""

        fmt = {
            "매수가($)": "${:.2f}",
            "매도가($)": "${:.2f}",
            "수익률(%)": "{:+.1f}%",
        }
        try:
            styled = cdf.style.format(fmt, na_rep="—").map(_color_ret, subset=["수익률(%)"])
        except AttributeError:
            styled = cdf.style.format(fmt, na_rep="—").applymap(_color_ret, subset=["수익률(%)"])
        st.dataframe(styled, hide_index=True, use_container_width=True, height=420)


# ── 성과 요약 KPI 카드 ────────────────────────────────────────────

def _render_kpi_cards(summary: dict, df: pd.DataFrame, cycles: list[dict]):
    done = [c for c in cycles if c["상태"] == "완료"]
    returns = [c["수익률(%)"] for c in done] if done else []

    # total_assets로 전체 수익률 계산
    ta_col = "total_assets"
    initial_assets = final_assets = None
    if ta_col in df.columns:
        ta = pd.to_numeric(df[ta_col], errors="coerce").dropna()
        if len(ta) >= 2:
            initial_assets = ta.iloc[0]
            final_assets = ta.dropna().iloc[-1]

    total_ret = (final_assets / initial_assets - 1) * 100 if initial_assets and final_assets else 0.0

    # 기간 (연수)
    if len(df) >= 2:
        years = (df["날짜"].max() - df["날짜"].min()).days / 365.25
        cagr = ((final_assets / initial_assets) ** (1 / years) - 1) * 100 if years > 0 and initial_assets else 0.0
    else:
        cagr = 0.0

    # MDD (chg_pct 컬럼이 있으면 그것, 없으면 total_assets 낙폭)
    mdd = 0.0
    if "chg_pct" in df.columns:
        mdd_series = pd.to_numeric(df["chg_pct"], errors="coerce").dropna()
        if not mdd_series.empty:
            mdd = mdd_series.min()

    win_rate = len([r for r in returns if r > 0]) / len(returns) * 100 if returns else 0.0

    cols = st.columns(5)
    metrics = [
        ("총 수익률", f"{total_ret:+.1f}%" if total_ret else "—"),
        ("CAGR", f"{cagr:.1f}%" if cagr else "—"),
        ("MDD", f"{mdd:.1f}%" if mdd else "—"),
        ("최종 자산($)", f"${final_assets:,.0f}" if final_assets else "—"),
        ("승률", f"{win_rate:.0f}% ({len([r for r in returns if r>0])}/{len(returns)})" if returns else "—"),
    ]
    for col, (lbl, val) in zip(cols, metrics):
        with col:
            st.metric(lbl, val)
