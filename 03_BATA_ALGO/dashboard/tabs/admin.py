"""
관리자 탭 — 누적 접속/로그인 현황 (hongryong.cho@gmail.com 전용)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import get_current_user
from session_tracker import get_stats, is_admin, ADMIN_EMAIL


def render():
    user = get_current_user()
    if user is None or not is_admin(user.get("email")):
        st.info("이 탭은 관리자만 접근할 수 있습니다.")
        return

    st.subheader("👑 관리자 — 접속 현황")

    if st.button("🔄 새로고침", key="admin_refresh"):
        st.rerun()

    stats = get_stats()

    # ── 누적 핵심 지표 ────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("누적 접속 횟수", f"{stats['total_visits']:,}회",
                  help="새 브라우저 탭/창으로 앱을 열 때마다 1회 카운트")
    with c2:
        st.metric("누적 로그인 횟수", f"{stats['total_logins']:,}회",
                  help="로그인 버튼을 눌러 인증 성공한 횟수")
    with c3:
        st.metric("누적 유저 수", f"{stats['unique_user_count']:,}명",
                  help="지금까지 로그인한 고유 이메일 수")

    st.divider()

    # ── 유저별 마지막 로그인 ──────────────────────────────────────
    st.markdown("**유저별 마지막 로그인**")
    if stats["last_by_user"]:
        user_rows = []
        for email, ts in sorted(stats["last_by_user"].items(),
                                key=lambda x: x[1], reverse=True):
            user_rows.append({"이메일": email, "마지막 로그인": ts})
        udf = pd.DataFrame(user_rows)
        st.dataframe(udf, hide_index=True, use_container_width=True)
    else:
        st.info("아직 로그인 기록이 없습니다.")

    st.divider()

    # ── 로그인 이력 (최근 100건) ──────────────────────────────────
    st.markdown("**로그인 이력 (최신순)**")
    events = stats["login_events"][:100]
    if events:
        edf = pd.DataFrame(events).rename(columns={
            "email": "이메일",
            "timestamp": "로그인 시각",
        })
        st.dataframe(edf, hide_index=True, use_container_width=True, height=380)
    else:
        st.info("로그인 이력이 없습니다.")

    st.caption(f"관리자: {ADMIN_EMAIL}  |  데이터 저장: visit_stats.json")
