"""
FnG RSI(2) 투자 대시보드
메인 진입점 — 탭 라우팅 및 인증 사이드바
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import streamlit as st

# 부모 경로 추가
_PARENT = Path(__file__).parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# ── 페이지 설정 (최상단에서 호출) ──────────────────────────────
st.set_page_config(
    page_title="FnG RSI(2) Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from auth import is_logged_in, get_current_user, logout, render_login_form, is_supabase_configured
from tabs import signal, backtest, custom_chart, position, trade_entry, trade_history, journal, account_mgmt, admin
from session_tracker import record_visit, record_login, get_stats, is_admin


# ── QR 코드 생성 ────────────────────────────────────────────────

def _make_qr_bytes(url: str) -> bytes:
    import qrcode
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _public_url() -> str:
    """공개 URL: 환경변수 DASHBOARD_PUBLIC_URL 우선, 없으면 localhost"""
    return os.environ.get("DASHBOARD_PUBLIC_URL", "http://localhost:8502")


# ── 사이드바 ────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.title("📊 FnG RSI(2)")
        st.caption("TQQQ / SOXL 알고리즘 대시보드")
        st.divider()

        if is_logged_in():
            user = get_current_user()
            st.success(f"👤 {user['email']}")
            if st.button("로그아웃", use_container_width=True):
                logout()
                st.rerun()

            # ── 관리자 전용: 누적 접속 현황 ───────────────────────
            if is_admin(user.get("email")):
                stats = get_stats()
                st.divider()
                st.caption("**👑 누적 현황**")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("총 접속", f"{stats['total_visits']:,}회")
                with col_b:
                    st.metric("총 로그인", f"{stats['total_logins']:,}회")
        else:
            render_login_form()
            st.info(
                "계정이 없으신 분은 관리자에게\n"
                "계정 생성을 요청하세요.",
            )

        st.divider()

        # ── QR 코드 ──────────────────────────────────────────────
        pub_url = _public_url()
        st.caption("**접속 QR**")
        try:
            qr_bytes = _make_qr_bytes(pub_url)
            st.image(qr_bytes, use_container_width=True)
        except Exception:
            pass
        st.caption(f"`{pub_url}`")

        st.divider()
        st.caption("**데이터 소스**")
        st.caption("• Google Sheets (백테스트)")
        st.caption("• yfinance (실시간 가격)")
        st.caption("• CNN / Alternative.me (F&G)")
        if is_supabase_configured():
            st.caption("• Supabase (개인 거래 DB)")
        else:
            st.caption("• Supabase: ⚠️ 미설정")


# ── 메인 ────────────────────────────────────────────────────────

def main():
    # ── 신규 세션 감지 → 방문 카운트 ───────────────────────────────
    if "session_id" not in st.session_state:
        import uuid
        st.session_state["session_id"] = str(uuid.uuid4())
        record_visit()

    # ── 로그인 감지 → 로그인 카운트 (세션당 1회) ─────────────────
    user = get_current_user()
    if user and not st.session_state.get("_login_recorded"):
        record_login(user["email"])
        st.session_state["_login_recorded"] = True

    render_sidebar()

    tabs = st.tabs([
        "📡 오늘의 신호",
        "📈 백테스트",
        "🔧 커스텀 차트",
        "💼 내 포지션",
        "📝 매매 입력",
        "📋 거래 내역",
        "📓 투자 일지",
        "🏦 계좌 관리",
        "👑 관리자",
    ])

    with tabs[0]:
        signal.render()

    with tabs[1]:
        backtest.render()

    with tabs[2]:
        custom_chart.render()

    def _require_login(render_fn):
        if is_logged_in():
            render_fn()
        else:
            st.info("이 탭은 로그인이 필요합니다. 사이드바에서 로그인하세요.")

    with tabs[3]:
        _require_login(position.render)

    with tabs[4]:
        _require_login(trade_entry.render)

    with tabs[5]:
        _require_login(trade_history.render)

    with tabs[6]:
        _require_login(journal.render)

    with tabs[7]:
        _require_login(account_mgmt.render)

    with tabs[8]:
        _require_login(admin.render)


if __name__ == "__main__":
    main()
