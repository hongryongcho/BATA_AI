"""
계좌 관리 탭 — 증권 계좌 등록/수정/삭제 (최대 10개)
"""
from __future__ import annotations

import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import get_current_user
from db import get_accounts, upsert_account, delete_account

MAX_ACCOUNTS = 10


def render():
    user = get_current_user()
    if user is None:
        st.info("로그인이 필요합니다.")
        return

    st.subheader("계좌 관리")

    with st.spinner("계좌 목록 로딩 중..."):
        accounts = get_accounts(user["id"])

    # ── 계좌 목록 ─────────────────────────────────────────────────
    if accounts:
        st.markdown(f"#### 등록된 계좌 ({len(accounts)}/{MAX_ACCOUNTS})")
        for acc in accounts:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                with c1:
                    st.markdown(f"**{acc['name']}**")
                with c2:
                    st.caption(acc.get("broker") or "증권사 미입력")
                with c3:
                    st.caption(f"초기현금: ${acc.get('initial_cash', 0):,.0f}")
                with c4:
                    if st.button("삭제", key=f"del_{acc['id']}", type="secondary"):
                        if delete_account(acc["id"]):
                            st.success(f"'{acc['name']}' 삭제 완료")
                            st.rerun()
    else:
        st.info("등록된 계좌가 없습니다. 아래에서 추가하세요.")

    st.divider()

    # ── 계좌 추가 폼 ─────────────────────────────────────────────
    if len(accounts) >= MAX_ACCOUNTS:
        st.warning(f"최대 {MAX_ACCOUNTS}개 계좌까지 등록 가능합니다.")
        return

    st.markdown("#### 계좌 추가")
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input("계좌명 *", placeholder="예: 키움 메인, 미래에셋 IRP")
            new_broker = st.text_input("증권사", placeholder="예: 키움증권, 미래에셋")
        with col2:
            new_cash = st.number_input(
                "초기 현금 ($)",
                min_value=0.0, step=100.0, format="%.0f",
                help="계좌 시작 시점의 현금 잔고를 입력하세요. 이후 입출금은 거래 내역에서 관리됩니다."
            )

        if st.button("계좌 추가", type="primary", use_container_width=True):
            if not new_name.strip():
                st.error("계좌명을 입력하세요.")
            elif any(a["name"] == new_name.strip() for a in accounts):
                st.error("이미 동일한 이름의 계좌가 있습니다.")
            else:
                ok = upsert_account(
                    user_id=user["id"],
                    name=new_name.strip(),
                    broker=new_broker.strip(),
                    initial_cash=new_cash,
                )
                if ok:
                    st.success(f"✅ '{new_name}' 계좌 추가 완료!")
                    st.rerun()

    # ── 계좌 수정 ─────────────────────────────────────────────────
    if accounts:
        st.divider()
        st.markdown("#### 계좌 수정")
        with st.container(border=True):
            acc_options = {a["name"]: a for a in accounts}
            sel_name = st.selectbox("수정할 계좌", list(acc_options.keys()))
            sel_acc = acc_options[sel_name]

            ec1, ec2 = st.columns(2)
            with ec1:
                edit_broker = st.text_input(
                    "증권사", value=sel_acc.get("broker") or "", key="edit_broker"
                )
            with ec2:
                edit_cash = st.number_input(
                    "초기 현금 ($)",
                    value=float(sel_acc.get("initial_cash") or 0),
                    min_value=0.0, step=100.0, format="%.0f",
                    key="edit_cash"
                )

            if st.button("수정 저장", type="primary"):
                ok = upsert_account(
                    user_id=user["id"],
                    name=sel_name,
                    broker=edit_broker.strip(),
                    initial_cash=edit_cash,
                    account_id=sel_acc["id"],
                )
                if ok:
                    st.success(f"✅ '{sel_name}' 수정 완료!")
                    st.rerun()
