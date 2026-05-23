"""
Supabase 인증 모듈
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_PARENT = Path(__file__).parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from _env_loader import load_env_config


def _get_supabase_client():
    """Supabase 클라이언트 반환. 미설정 시 None"""
    env = load_env_config()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_ANON_KEY", "")
    if not url or not key or url.startswith("https://your"):
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def is_supabase_configured() -> bool:
    return _get_supabase_client() is not None


def login(email: str, password: str) -> tuple[bool, str]:
    """로그인. (성공여부, 에러메시지) 반환"""
    client = _get_supabase_client()
    if client is None:
        return False, "Supabase가 설정되지 않았습니다."
    try:
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
        if resp.user:
            st.session_state["user"] = {
                "id": resp.user.id,
                "email": resp.user.email,
            }
            st.session_state["access_token"] = resp.session.access_token
            return True, ""
        return False, "로그인 실패"
    except Exception as e:
        msg = str(e)
        if "Invalid login credentials" in msg:
            return False, "이메일 또는 비밀번호가 올바르지 않습니다."
        return False, f"로그인 오류: {msg}"


def logout():
    st.session_state.pop("user", None)
    st.session_state.pop("access_token", None)


def get_current_user() -> dict | None:
    return st.session_state.get("user")


def is_logged_in() -> bool:
    return "user" in st.session_state


def render_login_form():
    """로그인 폼 렌더링. 로그인 성공 시 True 반환"""
    if not is_supabase_configured():
        st.warning("⚠️ Supabase가 설정되지 않았습니다.")
        st.info("""
**설정 방법:**
1. [Supabase](https://supabase.com)에서 프로젝트 생성
2. Project Settings → API에서 URL과 anon key 복사
3. `.env` 파일에 아래 항목 추가:
```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
```
4. Supabase SQL Editor에서 아래 스키마 실행:
```sql
CREATE TABLE trades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users,
  trade_date DATE NOT NULL,
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,
  shares NUMERIC NOT NULL,
  price NUMERIC NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE journal (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users,
  entry_date DATE NOT NULL,
  strategy TEXT,
  resolution TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, entry_date)
);

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users own trades" ON trades FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "users own journal" ON journal FOR ALL USING (auth.uid() = user_id);
```
        """)
        return False

    with st.form("login_form"):
        st.subheader("로그인")
        email = st.text_input("이메일")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if submitted:
        if not email or not password:
            st.error("이메일과 비밀번호를 입력하세요.")
            return False
        ok, msg = login(email, password)
        if ok:
            st.success("로그인 성공!")
            st.rerun()
            return True
        else:
            st.error(msg)
    return False
