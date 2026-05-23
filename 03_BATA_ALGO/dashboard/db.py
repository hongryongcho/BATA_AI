"""
Supabase DB CRUD 모듈 (accounts, trades, journal)
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

import streamlit as st

_PARENT = Path(__file__).parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from _env_loader import load_env_config


def _client():
    env = load_env_config()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        client = create_client(url, key)
        token = st.session_state.get("access_token")
        if token:
            client.auth.set_session(token, token)
        return client
    except Exception:
        return None


# ── 계좌 관리 ────────────────────────────────────────────────────

def get_accounts(user_id: str) -> list[dict]:
    c = _client()
    if c is None:
        return []
    try:
        resp = (c.table("accounts")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at")
                .execute())
        return resp.data or []
    except Exception as e:
        st.error(f"계좌 조회 실패: {e}")
        return []


def upsert_account(user_id: str, name: str, broker: str = "",
                   initial_cash: float = 0.0,
                   account_id: str | None = None) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        data = {
            "user_id": user_id,
            "name": name,
            "broker": broker,
            "initial_cash": initial_cash,
        }
        if account_id:
            c.table("accounts").update(data).eq("id", account_id).execute()
        else:
            c.table("accounts").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"계좌 저장 실패: {e}")
        return False


def delete_account(account_id: str) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        c.table("accounts").delete().eq("id", account_id).execute()
        return True
    except Exception as e:
        st.error(f"계좌 삭제 실패: {e}")
        return False


# ── 거래 내역 ────────────────────────────────────────────────────

def get_trades(user_id: str, account_id: str | None = None) -> list[dict]:
    """account_id 지정 시 해당 계좌 거래만 반환"""
    c = _client()
    if c is None:
        return []
    try:
        q = (c.table("trades")
             .select("*")
             .eq("user_id", user_id)
             .order("trade_date", desc=True))
        if account_id:
            q = q.eq("account_id", account_id)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        st.error(f"거래 조회 실패: {e}")
        return []


def add_trade(user_id: str, trade_date: date, ticker: str,
              action: str, shares: float, price: float,
              account_id: str | None = None,
              notes: str = "") -> bool:
    """BUY/SELL/DEPOSIT/WITHDRAWAL/TRANSFER 거래 저장.
    현금 거래(DEPOSIT/WITHDRAWAL/TRANSFER) 시 ticker='CASH', shares=0.
    """
    c = _client()
    if c is None:
        return False
    try:
        data: dict = {
            "user_id": user_id,
            "trade_date": trade_date.isoformat(),
            "ticker": ticker,
            "action": action,
            "shares": shares,
            "price": price,
        }
        if account_id:
            data["account_id"] = account_id
        if notes:
            data["notes"] = notes
        c.table("trades").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"거래 저장 실패: {e}")
        return False


def delete_trade(trade_id: str) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        c.table("trades").delete().eq("id", trade_id).execute()
        return True
    except Exception as e:
        st.error(f"거래 삭제 실패: {e}")
        return False


# ── 투자 일지 ────────────────────────────────────────────────────

def get_journal(user_id: str, limit: int = 30) -> list[dict]:
    c = _client()
    if c is None:
        return []
    try:
        resp = (c.table("journal")
                .select("*")
                .eq("user_id", user_id)
                .order("entry_date", desc=True)
                .limit(limit)
                .execute())
        return resp.data or []
    except Exception as e:
        st.error(f"일지 조회 실패: {e}")
        return []


def upsert_journal(user_id: str, entry_date: date,
                   strategy: str, resolution: str) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        c.table("journal").upsert({
            "user_id": user_id,
            "entry_date": entry_date.isoformat(),
            "strategy": strategy,
            "resolution": resolution,
            "updated_at": "now()",
        }, on_conflict="user_id,entry_date").execute()
        return True
    except Exception as e:
        st.error(f"일지 저장 실패: {e}")
        return False


def get_journal_by_date(user_id: str, entry_date: date) -> dict | None:
    c = _client()
    if c is None:
        return None
    try:
        resp = (c.table("journal")
                .select("*")
                .eq("user_id", user_id)
                .eq("entry_date", entry_date.isoformat())
                .execute())
        data = resp.data
        return data[0] if data else None
    except Exception:
        return None
