"""
매매 입력 탭 — 주식 매매 + 현금 입출금/이체 입력 폼
"""
from __future__ import annotations

import streamlit as st
from datetime import date
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import get_current_user
from db import add_trade, get_accounts
from data_loader import load_realtime_price

STOCK_TICKERS = ["TQQQ", "SOXL", "SPY", "UPRO", "QLD", "기타"]

ACTION_OPTIONS = {
    "BUY (매수)": "BUY",
    "SELL (매도)": "SELL",
    "DEPOSIT (입금)": "DEPOSIT",
    "WITHDRAWAL (출금)": "WITHDRAWAL",
    "TRANSFER (이체)": "TRANSFER",
}

CASH_ACTIONS = {"DEPOSIT", "WITHDRAWAL", "TRANSFER"}


def render():
    user = get_current_user()
    if user is None:
        st.info("로그인이 필요합니다.")
        return

    st.subheader("매매 입력")

    # ── 계좌 선택 ─────────────────────────────────────────────────
    accounts = get_accounts(user["id"])
    if not accounts:
        st.warning("등록된 계좌가 없습니다. '계좌 관리' 탭에서 계좌를 먼저 추가하세요.")
        return

    acc_map = {"(계좌 없음)": None} if not accounts else {a["name"]: a["id"] for a in accounts}
    sel_acc_name = st.selectbox("계좌 선택", list(acc_map.keys()), key="entry_account")
    sel_account_id = acc_map[sel_acc_name]

    st.divider()

    # ── 거래 유형 선택 ────────────────────────────────────────────
    with st.container(border=True):
        action_label = st.radio(
            "거래 유형",
            list(ACTION_OPTIONS.keys()),
            horizontal=True,
            key="entry_action"
        )
        action_code = ACTION_OPTIONS[action_label]

        col1, col2 = st.columns(2)

        with col1:
            trade_date = st.date_input("거래일", value=date.today(), key="entry_date")

        is_cash = action_code in CASH_ACTIONS

        if not is_cash:
            # 주식 거래 (BUY/SELL)
            with col1:
                ticker = st.selectbox("종목", STOCK_TICKERS, key="entry_ticker")
                if ticker == "기타":
                    ticker = st.text_input("종목 직접 입력", key="entry_ticker_custom").upper().strip()

            with col2:
                if ticker and ticker not in ("기타", ""):
                    info = load_realtime_price(ticker)
                    ref_price = info.get("price")
                    hint = f"현재가: ${ref_price:.2f}" if ref_price else ""
                else:
                    hint = ""

                shares = st.number_input("수량 (주)", min_value=0.0, step=1.0,
                                         format="%.2f", key="entry_shares")
                price = st.number_input(f"체결가격 ($)  {hint}", min_value=0.0,
                                        step=0.01, format="%.2f", key="entry_price")
                notes = ""

            if shares > 0 and price > 0:
                total = shares * price
                st.info(f"총 거래금액: **${total:,.2f}** ({shares:.2f}주 × ${price:.2f})")

        else:
            # 현금 거래 (DEPOSIT / WITHDRAWAL / TRANSFER)
            ticker = "CASH"
            shares = 0.0
            with col2:
                price = st.number_input("금액 ($)", min_value=0.0, step=100.0,
                                        format="%.0f", key="entry_cash_amount")

            notes = ""
            if action_code == "TRANSFER":
                other_accounts = [a["name"] for a in accounts if a["name"] != sel_acc_name]
                direction = st.radio("이체 방향", ["다른 계좌로 출금", "다른 계좌에서 입금"],
                                     horizontal=True, key="transfer_dir")
                if other_accounts:
                    partner = st.selectbox("상대 계좌", other_accounts, key="transfer_partner")
                else:
                    partner = st.text_input("상대 계좌명", key="transfer_partner_text")
                if direction == "다른 계좌로 출금":
                    notes = f"to:{partner}"
                else:
                    notes = f"from:{partner}"

            if price > 0:
                st.info(f"현금 {action_code}: **${price:,.0f}**")

        submitted = st.button("저장", type="primary", use_container_width=True, key="entry_submit")

    if submitted:
        if not is_cash and not ticker:
            st.error("종목을 입력하세요.")
            return
        if price <= 0:
            st.error("금액 또는 가격을 올바르게 입력하세요.")
            return
        if not is_cash and shares <= 0:
            st.error("수량을 올바르게 입력하세요.")
            return

        ok = add_trade(
            user_id=user["id"],
            trade_date=trade_date,
            ticker=ticker,
            action=action_code,
            shares=shares,
            price=price,
            account_id=sel_account_id,
            notes=notes,
        )
        if ok:
            if is_cash:
                st.success(f"✅ {action_label} ${price:,.0f} 저장 완료!")
            else:
                st.success(f"✅ {action_code} {ticker} {shares}주 @ ${price:.2f} 저장 완료!")
            st.balloons()
        else:
            st.error("저장 실패. 다시 시도하세요.")
