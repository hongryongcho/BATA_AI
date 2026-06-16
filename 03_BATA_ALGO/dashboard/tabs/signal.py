"""
오늘의 신호 탭 — RSI(2) + F&G 필터 + QQQ Crash Guard 현황
"""
from __future__ import annotations

import streamlit as st
from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import (
    load_qqq_guard_signals, load_qqq_guard_sheet_meta,
    load_qqq_realtime_change,
    load_realtime_price, compute_rsi, load_price_history,
    load_fear_greed,
)
from charts import plot_gauge


def render():
    st.subheader("오늘의 신호")

    col1, col2, col3, col4 = st.columns(4)

    # ── QQQ 당일 변화율 ──────────────────────────────────────────
    with col1:
        qqq = load_qqq_realtime_change()
        qqq_chg = qqq.get("change_pct", 0.0)
        qqq_px  = qqq.get("price")

        gauge_val  = max(-10.0, min(10.0, qqq_chg))
        gauge_norm = (gauge_val + 10.0) / 20.0 * 100.0

        st.plotly_chart(
            plot_gauge(gauge_norm, "QQQ 당일 변화율",
                       danger_low=25,
                       danger_high=75),
            use_container_width=True
        )

        chg_str = f"{qqq_chg:+.2f}%"
        px_str  = f"  (${qqq_px:.2f})" if qqq_px else ""
        if qqq_chg <= -5.0:
            st.error(f"🚨 QQQ {chg_str}{px_str}\n\n**Crash Guard 발동** — 강제 매도 + 10일 매수 금지")
        elif qqq_chg <= -3.0:
            st.warning(f"⚠️ QQQ {chg_str}{px_str}\n\n시장 급락 주의 (-5% 미만이면 가드 발동)")
        elif qqq_chg >= 0:
            st.success(f"✅ QQQ {chg_str}{px_str}\n\n정상 구간")
        else:
            st.info(f"QQQ {chg_str}{px_str}")

    # ── Fear & Greed ──────────────────────────────────────────────
    with col2:
        fng_data = load_fear_greed()
        fng_error = fng_data.get("error", False)
        fng_val  = fng_data.get("value", 50)
        fng_lbl  = fng_data.get("label", "중립")

        st.plotly_chart(
            plot_gauge(fng_val, "Fear & Greed",
                       danger_low=25,
                       danger_high=90),
            use_container_width=True
        )

        if fng_error:
            st.warning("⚠️ CNN F&G 불러오기 실패\n\n중앙값 **50 (중립)** 으로 대체 중 — 실제 값이 아님")
        elif fng_val >= 90:
            st.error(f"🚫 F&G {fng_val} ({fng_lbl})\n\n**매수 차단** — F&G ≥ 90 (극도 탐욕)")
        elif fng_val <= 25:
            st.warning(f"⏸️ F&G {fng_val} ({fng_lbl})\n\n**매도 보류** — F&G ≤ 25 (극도 공포)")
        elif fng_val >= 75:
            st.warning(f"⚠️ F&G {fng_val} ({fng_lbl})\n\n탐욕 구간 (90 이상이면 매수 차단)")
        else:
            st.success(f"✅ F&G {fng_val} ({fng_lbl})\n\n정상 구간")

    # ── RSI(2) TQQQ ──────────────────────────────────────────────
    with col3:
        _render_rsi_gauge("TQQQ")

    # ── RSI(2) SOXL ──────────────────────────────────────────────
    with col4:
        _render_rsi_gauge("SOXL")

    st.divider()

    # ── 현재가 카드 ──────────────────────────────────────────────
    st.markdown("#### 현재가")
    pcols = st.columns(5)
    for i, ticker in enumerate(["TQQQ", "SOXL", "QQQ", "SPY", "UPRO"]):
        with pcols[i]:
            info  = load_realtime_price(ticker)
            price = info.get("price")
            chg   = info.get("change_pct", 0.0)
            if price:
                st.metric(ticker, f"${price:.2f}", f"{chg:+.2f}%",
                          delta_color="normal" if chg >= 0 else "inverse")
            else:
                st.metric(ticker, "N/A", "")

    st.divider()

    # ── 신호 카드 ────────────────────────────────────────────────
    # 다음 미국 거래일 계산 (ET 기준 16:00 이후면 다음날로)
    try:
        from zoneinfo import ZoneInfo
        _et = ZoneInfo("America/New_York")
    except ImportError:
        from datetime import timezone
        _et = timezone.utc
    _now_et = datetime.now(_et)
    _day_names = ["월", "화", "수", "목", "금", "토", "일"]
    _next = _now_et if _now_et.hour < 16 else _now_et + timedelta(days=1)
    while _next.weekday() >= 5:
        _next += timedelta(days=1)
    _next_label = f"{_next.month}/{_next.day:02d}({_day_names[_next.weekday()]})"

    st.markdown(f"#### 📋 다음 거래일 {_next_label} 예약 주문 (RSI(2) + F&G 필터 + QQQ Crash Guard 기준)")
    with st.spinner("신호 로딩 중..."):
        signals = load_qqq_guard_signals()
        sheet_meta = load_qqq_guard_sheet_meta()

    # ── 시트 데이터 신선도 체크 ──────────────────────────────────
    _sheet_updated_at = sheet_meta.get("updated_at")
    _sheet_stale = False
    if _sheet_updated_at is None:
        st.error("⚠️ 데이터 업데이트 실패 — 시트 정보를 불러올 수 없습니다. 스케줄러를 확인하세요.")
        _sheet_stale = True
    else:
        _age_h = (datetime.now() - _sheet_updated_at).total_seconds() / 3600
        if _age_h > 30:
            st.error(
                f"⚠️ 데이터 업데이트 실패 — 시트가 {_age_h:.0f}시간 전 기준 데이터입니다 "
                f"(최종 갱신: {_sheet_updated_at.strftime('%m/%d %H:%M')}). "
                "스케줄러를 확인하세요."
            )
            _sheet_stale = True
        else:
            st.caption(
                f"📊 시트 최종 갱신: {_sheet_updated_at.strftime('%Y-%m-%d %H:%M:%S')} "
                f"({_age_h:.0f}시간 전) — 아래 데이터는 해당 시점 기준"
            )

    if not signals:
        st.info("신호를 불러오지 못했습니다.\n"
                "`python3 create_qqq_guard_daily.py` 실행 후 확인하세요.")
    elif _sheet_stale:
        st.warning("시트 데이터가 오래됐습니다. 위 경고를 확인하고 스케줄러 상태를 점검하세요.")
    else:
        for sig in signals:
            ticker      = sig.get("ticker", "")
            state       = sig.get("current_state", "")
            next_action = sig.get("next_action", "")
            rsi_val     = sig.get("rsi", "")
            cooldown    = sig.get("cooldown_days", "0")
            buy_lim     = sig.get("buy_limit", "")
            sell_lim    = sig.get("sell_limit", "")

            try:
                cd_int = int(float(cooldown)) if cooldown else 0
            except (ValueError, TypeError):
                cd_int = 0

            if cd_int > 0:
                icon = "🟡"
            elif "BUY" in next_action.upper() or "매수" in next_action:
                icon = "🟢"
            elif "SELL" in next_action.upper() or "매도" in next_action:
                icon = "🔴"
            elif "차단" in next_action or "보류" in next_action:
                icon = "🟠"
            else:
                icon = "⚪"

            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 2, 3])
                with c1:
                    st.markdown(f"### {icon} **{ticker}**")
                    st.caption(f"RSI(2): {rsi_val}")
                    fng_display = f"{fng_val} ({fng_lbl})" + (" ⚠️대체값" if fng_error else "")
                    st.caption(f"F&G: {fng_display}")
                with c2:
                    st.markdown(f"**현재 상태:** {state}")
                    if cd_int > 0:
                        st.error(f"🔒 QQQ 쿨다운: {cd_int}일 남음")
                    elif fng_val >= 90:
                        st.error("🚫 F&G 극도 탐욕 — 매수 차단")
                    elif fng_val <= 25:
                        st.warning("⏸️ F&G 극도 공포 — 매도 보류")
                    elif "보유중" in state:
                        st.success("📦 주식 보유")
                    else:
                        st.info("💵 현금 보유")
                    if buy_lim:
                        st.caption(f"매수 예약가: ${buy_lim}")
                    if sell_lim:
                        st.caption(f"매도 예약가: ${sell_lim}")
                with c3:
                    st.markdown("**다음 액션:**")
                    st.markdown(f"#### `{next_action}`")

    # ── 알고리즘 안내 ──────────────────────────────────────────────
    with st.expander("ℹ️ RSI(2) + F&G 필터 + QQQ Crash Guard 알고리즘 설명"):
        st.markdown("""
**세 가지 조건 동시 적용**

| 조건 | TQQQ | SOXL |
|------|------|------|
| **매수** | RSI(2) < 15 **& F&G < 90** | RSI(2) < 15 **& F&G < 90** |
| **매도** | RSI(2) > 75 **& F&G > 25** | RSI(2) > 90 **& F&G > 25** |
| **QQQ Guard** | QQQ 당일 -5% 이하 → 즉시 강제 매도 + 10일 매수 금지 ||

**F&G 필터 역할:**
- F&G ≥ 90 (극도 탐욕): 매수 신호가 나와도 **매수 차단**
- F&G ≤ 25 (극도 공포): 매도 신호가 나와도 **매도 보류**

**QQQ Crash Guard 역할:**
- QQQ 당일 -5% 이하: F&G·RSI 조건 무시하고 **강제 매도** + 10일 냉각기
""")

    st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (1분 캐시)")


_RSI_BUY_THRESHOLD  = 15   # TQQQ/SOXL 공통
_RSI_SELL_THRESHOLD = {"TQQQ": 75, "SOXL": 90}


def _render_rsi_gauge(ticker: str):
    with st.spinner(f"{ticker} RSI 계산 중..."):
        df = load_price_history(ticker, period="1y")
    if df.empty:
        st.warning(f"{ticker} 데이터 없음")
        return
    rsi = compute_rsi(df["close"], period=2)
    rsi_val = float(rsi.iloc[-1]) if not rsi.empty else 50.0

    sell_thr = _RSI_SELL_THRESHOLD.get(ticker, 85)
    st.plotly_chart(
        plot_gauge(rsi_val, f"RSI(2) — {ticker}",
                   danger_low=_RSI_BUY_THRESHOLD,
                   danger_high=sell_thr),
        use_container_width=True
    )
    if rsi_val < _RSI_BUY_THRESHOLD:
        st.success(f"📉 RSI {rsi_val:.1f} — **매수 신호**")
    elif rsi_val > sell_thr:
        st.error(f"📈 RSI {rsi_val:.1f} — **매도 신호** (>{sell_thr})")
    else:
        st.info(f"RSI {rsi_val:.1f} — 중립")
