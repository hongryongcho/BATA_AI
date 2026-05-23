"""
내 포지션 탭 — 계좌 선택, 현금 잔고, 보유 현황, 미실현/실현 손익, 양도세 추정
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import get_current_user
from db import get_trades, get_accounts
from data_loader import load_realtime_price
from charts import plot_portfolio_pie

TAX_RATE = 0.22
TAX_EXEMPTION_USD = 1_900.0  # 약 250만원

CASH_ACTIONS = {"DEPOSIT", "WITHDRAWAL", "TRANSFER"}


def render():
    user = get_current_user()
    if user is None:
        st.info("로그인이 필요합니다.")
        return

    # ── 계좌 선택 ─────────────────────────────────────────────────
    accounts = get_accounts(user["id"])

    if not accounts:
        st.info("등록된 계좌가 없습니다. '계좌 관리' 탭에서 계좌를 추가하세요.")
        return

    acc_map = {a["name"]: a for a in accounts}
    sel_name = st.selectbox("계좌 선택", ["전체"] + list(acc_map.keys()), key="pos_account")

    if sel_name == "전체":
        trades_raw = get_trades(user["id"])
        initial_cash = sum(float(a.get("initial_cash") or 0) for a in accounts)
    else:
        sel_acc = acc_map[sel_name]
        trades_raw = get_trades(user["id"], account_id=sel_acc["id"])
        initial_cash = float(sel_acc.get("initial_cash") or 0)

    if not trades_raw:
        st.info("거래 내역이 없습니다. '매매 입력' 탭에서 거래를 추가하세요.")
        return

    df = pd.DataFrame(trades_raw)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0)

    positions, realized_pnl, cash_balance = _calc_positions(df, initial_cash)

    # ── 요약 메트릭 ───────────────────────────────────────────────
    st.markdown("#### 계좌 현황")
    pos_df = pd.DataFrame(positions) if positions else pd.DataFrame()

    total_market_value = pos_df["market_value"].sum() if not pos_df.empty else 0.0
    total_cost = pos_df["cost_basis"].sum() if not pos_df.empty else 0.0
    total_unrealized = pos_df["unrealized_pnl"].sum() if not pos_df.empty else 0.0
    total_assets = total_market_value + cash_balance

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("총 자산", f"${total_assets:,.0f}")
    with c2:
        st.metric("주식 평가금액", f"${total_market_value:,.0f}")
    with c3:
        st.metric("현금 잔고", f"${cash_balance:,.0f}")
    with c4:
        delta_color = "normal" if total_unrealized >= 0 else "inverse"
        pct = (total_unrealized / total_cost * 100) if total_cost > 0 else 0.0
        st.metric("미실현 손익", f"${total_unrealized:+,.0f}",
                  f"{pct:+.2f}%", delta_color=delta_color)
    with c5:
        st.metric("실현 손익", f"${realized_pnl:+,.0f}")

    st.divider()

    # ── 포지션 테이블 ─────────────────────────────────────────────
    st.markdown("#### 보유 포지션")
    if positions:
        col_chart, col_table = st.columns([1, 2])
        with col_chart:
            fig = plot_portfolio_pie(positions)
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            display_df = pos_df[["ticker", "shares", "avg_price", "current_price",
                                  "market_value", "unrealized_pnl", "unrealized_pct"]].copy()
            display_df.columns = ["종목", "수량", "평균단가($)", "현재가($)",
                                   "평가금액($)", "미실현손익($)", "수익률(%)"]
            st.dataframe(
                display_df.style
                .format({
                    "평균단가($)": "${:,.2f}", "현재가($)": "${:,.2f}",
                    "평가금액($)": "${:,.0f}", "미실현손익($)": "${:+,.0f}",
                    "수익률(%)": "{:+.2f}%"
                })
                .applymap(lambda v: "color: #2ca02c" if isinstance(v, str) and v.startswith("+") else
                          ("color: #d62728" if isinstance(v, str) and v.startswith("-") else ""),
                          subset=["미실현손익($)", "수익률(%)"]),
                hide_index=True, use_container_width=True
            )
    else:
        st.info("현재 보유 포지션이 없습니다.")

    # ── 세금 추정 ─────────────────────────────────────────────────
    st.divider()
    st.markdown("#### 세금 추정")
    taxable = max(0.0, realized_pnl - TAX_EXEMPTION_USD)
    tax_est = taxable * TAX_RATE if taxable > 0 else 0.0

    t1, t2, t3 = st.columns(3)
    with t1:
        st.metric("실현 손익 (연간)", f"${realized_pnl:+,.0f}")
    with t2:
        st.metric("과세 대상 금액", f"${taxable:,.0f}",
                  f"공제 ${TAX_EXEMPTION_USD:,.0f} 적용")
    with t3:
        st.metric("예상 양도세 (22%)", f"${tax_est:,.0f}")

    st.caption("⚠️ 양도세 추정은 참고용입니다. 실제 납부세액은 회계사와 상담하세요.")


def _calc_positions(df: pd.DataFrame,
                    initial_cash: float) -> tuple[list[dict], float, float]:
    """포지션, 실현손익, 현금잔고 계산 (FIFO 방식).

    현금 잔고 = initial_cash
               + DEPOSIT
               - WITHDRAWAL
               +/- TRANSFER (notes에 'to:' 면 출금, 'from:' 면 입금)
               - BUY 금액
               + SELL 금액
    """
    buy_queues: dict[str, list] = {}
    realized_pnl = 0.0
    cash = initial_cash

    for _, row in df.sort_values("trade_date").iterrows():
        action = str(row.get("action", "")).upper()
        shares = float(row["shares"])
        price = float(row["price"])
        ticker = str(row.get("ticker", ""))

        if action == "DEPOSIT":
            cash += price
        elif action == "WITHDRAWAL":
            cash -= price
        elif action == "TRANSFER":
            notes = str(row.get("notes") or "").lower()
            if notes.startswith("to:"):
                cash -= price
            else:
                cash += price
        elif action == "BUY":
            cash -= shares * price
            if ticker not in buy_queues:
                buy_queues[ticker] = []
            buy_queues[ticker].append([shares, price])
        elif action == "SELL":
            cash += shares * price
            remaining = shares
            cost_of_sold = 0.0
            queue = buy_queues.get(ticker, [])
            while remaining > 0 and queue:
                lot_shares, lot_price = queue[0]
                if lot_shares <= remaining:
                    cost_of_sold += lot_shares * lot_price
                    remaining -= lot_shares
                    queue.pop(0)
                else:
                    cost_of_sold += remaining * lot_price
                    queue[0][0] -= remaining
                    remaining = 0
            realized_pnl += shares * price - cost_of_sold

    # 현재 보유 포지션 계산
    result = []
    for ticker, queue in buy_queues.items():
        total_shares = sum(s for s, _ in queue)
        if total_shares <= 0:
            continue
        total_cost = sum(s * p for s, p in queue)
        avg_price = total_cost / total_shares

        info = load_realtime_price(ticker)
        current_price = info.get("price") or avg_price
        market_value = total_shares * current_price
        unrealized_pnl = market_value - total_cost
        unrealized_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0.0

        result.append({
            "ticker": ticker,
            "shares": total_shares,
            "avg_price": avg_price,
            "current_price": current_price,
            "cost_basis": total_cost,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pct": unrealized_pct,
        })

    return result, realized_pnl, cash
