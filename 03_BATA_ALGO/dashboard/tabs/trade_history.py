"""
거래 내역 탭 — 계좌 필터, 매매/현금 이력 테이블, CSV 내보내기
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import get_current_user
from db import get_trades, get_accounts, delete_trade

CASH_ACTIONS = {"DEPOSIT", "WITHDRAWAL", "TRANSFER"}

ACTION_KO = {
    "BUY": "매수",
    "SELL": "매도",
    "DEPOSIT": "입금",
    "WITHDRAWAL": "출금",
    "TRANSFER": "이체",
}


def render():
    user = get_current_user()
    if user is None:
        st.info("로그인이 필요합니다.")
        return

    st.subheader("거래 내역")

    # ── 계좌 선택 ─────────────────────────────────────────────────
    accounts = get_accounts(user["id"])
    acc_map = {a["name"]: a["id"] for a in accounts}

    sel_acc_name = st.selectbox("계좌", ["전체"] + list(acc_map.keys()), key="hist_account")
    sel_account_id = acc_map.get(sel_acc_name) if sel_acc_name != "전체" else None

    with st.spinner("거래 내역 로딩 중..."):
        trades = get_trades(user["id"], account_id=sel_account_id)

    if not trades:
        st.info("거래 내역이 없습니다.")
        return

    df = pd.DataFrame(trades)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0)
    df["거래금액($)"] = df.apply(
        lambda r: r["price"] if r["action"] in CASH_ACTIONS else r["shares"] * r["price"],
        axis=1
    )

    # ── 필터 ─────────────────────────────────────────────────────
    with st.expander("🔍 필터", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            tickers = ["전체"] + sorted(df["ticker"].unique().tolist())
            sel_ticker = st.selectbox("종목", tickers, key="hist_ticker")
        with fc2:
            actions = ["전체"] + sorted(df["action"].unique().tolist())
            sel_action = st.selectbox("구분", actions, key="hist_action")
        with fc3:
            min_date = df["trade_date"].min().date()
            max_date = df["trade_date"].max().date()
            date_range = st.date_input("기간", value=(min_date, max_date), key="hist_dates")

    filtered = df.copy()
    if sel_ticker != "전체":
        filtered = filtered[filtered["ticker"] == sel_ticker]
    if sel_action != "전체":
        filtered = filtered[filtered["action"] == sel_action]
    if len(date_range) == 2:
        filtered = filtered[
            (filtered["trade_date"].dt.date >= date_range[0]) &
            (filtered["trade_date"].dt.date <= date_range[1])
        ]

    # ── 요약 ─────────────────────────────────────────────────────
    buys = filtered[filtered["action"] == "BUY"]
    sells = filtered[filtered["action"] == "SELL"]
    deposits = filtered[filtered["action"] == "DEPOSIT"]
    withdrawals = filtered[filtered["action"] == "WITHDRAWAL"]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("총 거래", f"{len(filtered)}건")
    with c2:
        st.metric("매수", f"{len(buys)}건", f"${buys['거래금액($)'].sum():,.0f}")
    with c3:
        st.metric("매도", f"{len(sells)}건", f"${sells['거래금액($)'].sum():,.0f}")
    with c4:
        net_cash = deposits["거래금액($)"].sum() - withdrawals["거래금액($)"].sum()
        st.metric("입금 - 출금", f"${net_cash:,.0f}")

    # ── 테이블 ───────────────────────────────────────────────────
    display = filtered[["trade_date", "ticker", "action", "shares",
                         "price", "거래금액($)"]].copy()
    display["구분(한글)"] = display["action"].map(ACTION_KO).fillna(display["action"])
    display["trade_date"] = display["trade_date"].dt.strftime("%Y-%m-%d")

    # notes 컬럼 있으면 추가
    if "notes" in filtered.columns:
        display["메모"] = filtered["notes"].fillna("")
        show_cols = ["trade_date", "ticker", "구분(한글)", "shares", "price", "거래금액($)", "메모"]
        col_names = ["거래일", "종목", "구분", "수량", "단가($)", "거래금액($)", "메모"]
    else:
        show_cols = ["trade_date", "ticker", "구분(한글)", "shares", "price", "거래금액($)"]
        col_names = ["거래일", "종목", "구분", "수량", "단가($)", "거래금액($)"]

    display = display[show_cols].copy()
    display.columns = col_names

    def _color_action(v):
        if v == "매수":
            return "color: #2ca02c"
        if v == "매도":
            return "color: #d62728"
        if v == "입금":
            return "color: #1f77b4"
        if v in ("출금", "이체"):
            return "color: #ff7f0e"
        return ""

    fmt = {"단가($)": "${:,.2f}", "거래금액($)": "${:,.0f}", "수량": "{:.2f}"}
    st.dataframe(
        display.style.format(fmt).map(_color_action, subset=["구분"]),
        hide_index=True, width="stretch", height=420
    )

    # ── CSV 내보내기 ─────────────────────────────────────────────
    csv = display.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV 내보내기",
        data=csv,
        file_name=f"trades_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

    # ── 삭제 ─────────────────────────────────────────────────────
    with st.expander("🗑️ 거래 삭제"):
        st.warning("삭제된 거래는 복구할 수 없습니다.")
        trade_ids = filtered["id"].tolist()
        trade_labels = [
            f"{r['거래일']} {r['종목']} {r['구분']} {r.get('수량', 0):.2f}"
            for _, r in display.iterrows()
        ]
        if trade_ids:
            sel_label = st.selectbox("삭제할 거래 선택", trade_labels, key="del_trade")
            sel_idx = trade_labels.index(sel_label)
            if st.button("삭제", type="secondary", key="del_btn"):
                if delete_trade(trade_ids[sel_idx]):
                    st.success("삭제 완료")
                    st.rerun()
