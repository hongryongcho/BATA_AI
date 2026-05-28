"""
데이터 로딩 모듈
- Google Sheets: 백테스트 결과, FnG 신호
- yfinance: 실시간/히스토리 가격, RSI 계산
- fear_greed.py: F&G 지수
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

# 부모 디렉토리(03_BATA_ALGO)를 sys.path에 추가하여 기존 모듈 재사용
_PARENT = Path(__file__).parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from _env_loader import load_env_config, get_spreadsheet_id, get_qqq_guard_spreadsheet_id
from fear_greed import fetch_fear_greed


# ── Google Sheets 인증 ──────────────────────────────────────────

def _get_sheets_client():
    import pickle
    import gspread
    from google.oauth2.credentials import Credentials as OAuthCredentials
    from google.auth.transport.requests import Request

    env = load_env_config()
    token_rel = env.get("GOOGLE_TOKEN_PATH", "../02_BATA_MQTT/config/algo_token.json")
    token_path = (_PARENT / token_rel).resolve()

    if not token_path.exists():
        raise FileNotFoundError(f"Google 인증 토큰 없음: {token_path}\n03_BATA_ALGO에서 setup_auth.py를 먼저 실행하세요.")

    with open(token_path, "rb") as f:
        creds = pickle.load(f)

    if hasattr(creds, "expired") and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return gspread.authorize(creds)


# ── FnG 신호 (Summary 탭) ───────────────────────────────────────

@st.cache_data(ttl=300)
def load_fng_signals() -> list[dict]:
    """Summary 탭에서 현재 사이클 & 다음날 예약주문 읽기"""
    try:
        spreadsheet_id = get_spreadsheet_id()
        gc = _get_sheets_client()
        ss = gc.open_by_key(spreadsheet_id)
        ws = ss.worksheet("Summary")
        values = ws.get_all_values()

        section_title = "[ 현재 사이클 & 다음날 예약 주문 (RSI2+F&G 기준) ]"
        section_idx = None
        for i, row in enumerate(values):
            if row and row[0].strip() == section_title:
                section_idx = i
                break

        if section_idx is None:
            return []

        rows = []
        for r in values[section_idx + 2:]:
            if not r or not r[0].strip():
                break
            ticker = r[0].strip()
            if ticker not in {"TQQQ", "SOXL"}:
                continue
            rows.append({
                "ticker": ticker,
                "strategy": r[1].strip() if len(r) > 1 else "",
                "current_state": r[2].strip() if len(r) > 2 else "",
                "next_action": r[9].strip() if len(r) > 9 else "",
            })
        return rows
    except Exception as e:
        st.warning(f"FnG 신호 로딩 실패: {e}")
        return []


# ── 백테스트 데이터 (TQQQ_매매기준가 / SOXL_매매기준가 탭) ────

@st.cache_data(ttl=300)
def load_backtest_data(ticker: str = "TQQQ") -> tuple[pd.DataFrame, dict]:
    """TQQQ_매매기준가 또는 SOXL_매매기준가 탭에서 데이터 읽기.
    Returns: (data_df, summary_dict)
      - summary_dict: rows 0~3의 key-value 성과 요약
      - data_df: row 4 헤더, row 5~ 데이터
        컬럼: 날짜, close, chg_pct, fng, rsi2, fng_blocked,
               buy_limit_expected_px, sell_limit_expected_px
    """
    sheet_name = f"{ticker}_매매기준가"
    try:
        spreadsheet_id = get_spreadsheet_id()
        gc = _get_sheets_client()
        ss = gc.open_by_key(spreadsheet_id)
        ws = ss.worksheet(sheet_name)
        values = ws.get_all_values()

        if len(values) < 6:
            st.warning(f"'{sheet_name}' 시트 데이터 부족 (행 수: {len(values)})")
            return pd.DataFrame(), {}

        # rows 0~3: 성과 요약 key-value 파싱
        summary = {}
        for r in values[:4]:
            if r and len(r) >= 2 and r[0].strip() and r[1].strip():
                summary[r[0].strip()] = r[1].strip()

        # row 4: 헤더
        raw_headers = [h.strip() for h in values[4]]
        data_rows = values[5:]
        df = pd.DataFrame(data_rows, columns=raw_headers)

        # 첫 번째 컬럼(날짜)으로 빈 행 제거
        date_col = raw_headers[0]
        df = df[df[date_col].astype(str).str.strip() != ""].copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df = df.rename(columns={date_col: "날짜"})

        # 숫자 컬럼 변환
        numeric_cols = ["close", "chg_pct", "fng", "rsi2",
                        "buy_limit_expected_px", "sell_limit_expected_px",
                        "total_assets", "return_pct", "cash", "holdings"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", "").str.replace("%", ""),
                    errors="coerce"
                )

        if "fng_blocked" in df.columns:
            df["fng_blocked"] = (df["fng_blocked"].astype(str)
                                 .str.upper().isin(["TRUE", "1", "YES", "Y"]))

        df = df.sort_values("날짜").reset_index(drop=True)
        return df, summary

    except Exception as e:
        st.warning(f"백테스트 데이터 로딩 실패 ({sheet_name}): {e}")
        return pd.DataFrame(), {}


# ── yfinance: 실시간 가격 ────────────────────────────────────────

@st.cache_data(ttl=60)
def load_realtime_price(ticker: str) -> dict:
    """현재가, 전일종가, 변동률 반환"""
    try:
        info = yf.Ticker(ticker).fast_info
        current = getattr(info, "last_price", None)
        prev_close = getattr(info, "previous_close", None)
        if current and prev_close:
            change_pct = (current - prev_close) / prev_close * 100
        else:
            change_pct = 0.0
        return {"ticker": ticker, "price": current, "prev_close": prev_close, "change_pct": change_pct}
    except Exception:
        return {"ticker": ticker, "price": None, "prev_close": None, "change_pct": 0.0}


# ── yfinance: 히스토리 가격 ─────────────────────────────────────

@st.cache_data(ttl=300)
def load_price_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    """종가 히스토리 반환"""
    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if raw.empty:
            return pd.DataFrame()
        # MultiIndex 컬럼 처리 (yfinance 최신 버전)
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"][ticker]
        else:
            close = raw["Close"]
        df = pd.DataFrame({"close": close})
        df.index = pd.to_datetime(df.index)
        df = df.dropna()
        return df
    except Exception:
        return pd.DataFrame()


# ── RSI 계산 ────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """Wilder EWM 방식 RSI 계산"""
    alpha = 1.0 / period
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=alpha, adjust=False).mean()
    ma_down = down.ewm(alpha=alpha, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


# ── QQQ Guard 백테스트 데이터 ────────────────────────────────────

@st.cache_data(ttl=300)
def load_qqq_guard_backtest_data(ticker: str = "TQQQ") -> tuple[pd.DataFrame, dict]:
    """QQQ Crash Guard 시트에서 TQQQ/SOXL_매매기준가 탭 읽기."""
    sheet_name = f"{ticker}_매매기준가"
    try:
        spreadsheet_id = get_qqq_guard_spreadsheet_id()
        gc = _get_sheets_client()
        ss = gc.open_by_key(spreadsheet_id)
        ws = ss.worksheet(sheet_name)
        values = ws.get_all_values()

        if len(values) < 6:
            st.warning(f"QQQ Guard '{sheet_name}' 시트 데이터 부족")
            return pd.DataFrame(), {}

        summary = {}
        for r in values[:4]:
            if r and len(r) >= 2 and r[0].strip() and r[1].strip():
                summary[r[0].strip()] = r[1].strip()

        raw_headers = [h.strip() for h in values[4]]
        df = pd.DataFrame(values[5:], columns=raw_headers)

        date_col = raw_headers[0]
        df = df[df[date_col].astype(str).str.strip() != ""].copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df = df.rename(columns={date_col: "날짜"})

        numeric_cols = ["close", "chg_pct", "qqq_chg_pct", "fng", "rsi2",
                        "buy_limit_expected_px", "sell_limit_expected_px",
                        "total_assets", "return_pct", "cash", "holdings",
                        "cooldown_days"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", "").str.replace("%", ""),
                    errors="coerce"
                )

        if "fng_blocked" in df.columns:
            pass  # 텍스트 유지

        df = df.sort_values("날짜").reset_index(drop=True)
        return df, summary

    except Exception as e:
        st.warning(f"QQQ Guard 데이터 로딩 실패 ({sheet_name}): {e}")
        return pd.DataFrame(), {}


@st.cache_data(ttl=60)
def load_qqq_guard_signals() -> list[dict]:
    """QQQ Guard Summary 탭에서 오늘의 신호 읽기."""
    try:
        spreadsheet_id = get_qqq_guard_spreadsheet_id()
        gc = _get_sheets_client()
        ss = gc.open_by_key(spreadsheet_id)
        ws = ss.worksheet("Summary")
        values = ws.get_all_values()

        section_title = "[ 현재 사이클 & 다음날 예약 주문 (RSI2+F&G+QQQ가드+GC지연 기준) ]"
        section_idx = None
        for i, row in enumerate(values):
            if row and row[0].strip() == section_title:
                section_idx = i
                break

        if section_idx is None:
            return []

        # Summary 시트 현재 사이클 섹션 컬럼 순서 (create_qqq_guard_daily.py 기준):
        # 0:종목 1:전략명 2:현재상태 3:현재사이클 4:오늘종가 5:RSI(2) 6:QQQ변화%
        # 7:다음장BUY기준가 8:다음장SELL기준가 9:추천예약주문 10:직전사이클정산현금 11:총수익률 12:거래횟수
        import re as _re
        rows = []
        for r in values[section_idx + 2:]:
            if not r or not r[0].strip():
                break
            ticker = r[0].strip()
            if ticker not in {"TQQQ", "SOXL"}:
                continue
            current_state = r[2].strip() if len(r) > 2 else ""
            # cooldown_days는 current_state 문자열에서 직접 파싱
            # (시트 컬럼에 별도 쿨다운 필드 없음 — current_state에 "QQQ쿨다운 N일" 포함)
            cd_match = _re.search(r'QQQ쿨다운 (\d+)일', current_state)
            cooldown_days = cd_match.group(1) if cd_match else "0"
            rows.append({
                "ticker":        ticker,
                "strategy":      r[1].strip()  if len(r) > 1  else "",
                "current_state": current_state,
                "current_cycle": r[3].strip()  if len(r) > 3  else "",
                "today_close":   r[4].strip()  if len(r) > 4  else "",
                "rsi":           r[5].strip()  if len(r) > 5  else "",
                "qqq_chg":       r[6].strip()  if len(r) > 6  else "",
                "buy_limit":     r[7].strip()  if len(r) > 7  else "",
                "sell_limit":    r[8].strip()  if len(r) > 8  else "",
                "next_action":   r[9].strip()  if len(r) > 9  else "",
                "settled_cash":  r[10].strip() if len(r) > 10 else "",
                "total_ret":     r[11].strip() if len(r) > 11 else "",
                "cooldown_days": cooldown_days,
            })
        return rows
    except Exception as e:
        st.warning(f"QQQ Guard 신호 로딩 실패: {e}")
        return []


@st.cache_data(ttl=60)
def load_qqq_realtime_change() -> dict:
    """QQQ 당일 등락률 실시간 조회."""
    try:
        info = yf.Ticker("QQQ").fast_info
        current = getattr(info, "last_price", None)
        prev_close = getattr(info, "previous_close", None)
        if current and prev_close:
            chg = (current - prev_close) / prev_close * 100
        else:
            chg = 0.0
        return {"price": current, "prev_close": prev_close, "change_pct": round(chg, 2)}
    except Exception:
        return {"price": None, "prev_close": None, "change_pct": 0.0}


# ── Fear & Greed ────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_fear_greed() -> dict:
    try:
        return fetch_fear_greed()
    except Exception:
        return {"value": 50, "label": "Neutral", "source": "fallback"}


# ── 백테스트 사이클 추출 ────────────────────────────────────────

def extract_cycles(df: pd.DataFrame) -> list[dict]:
    """BUY/SELL action에서 투자 사이클(보유 기간) 추출"""
    if df.empty or "action" not in df.columns:
        return []

    df = df.copy()
    for col in ["close", "total_assets", "trade_qty"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    cycles: list[dict] = []
    cycle_num = 0
    in_pos = False
    buy_date = buy_close = buy_assets_before = None

    for i, row in df.iterrows():
        action = str(row.get("action", "")).strip().upper()
        if action == "BUY" and not in_pos:
            in_pos = True
            cycle_num += 1
            buy_date = row["날짜"]
            buy_close = row.get("close")
            # 매수 직전 total_assets (이전 행)
            prev_idx = df.index.get_loc(i)
            buy_assets_before = (
                pd.to_numeric(df.iloc[prev_idx - 1]["total_assets"], errors="coerce")
                if prev_idx > 0 else row.get("total_assets")
            )

        elif action == "SELL" and in_pos:
            sell_date = row["날짜"]
            sell_close = row.get("close")
            sell_assets = pd.to_numeric(row.get("total_assets", 0), errors="coerce") or 0
            hold_days = (sell_date - buy_date).days if buy_date else 0

            if buy_close and sell_close and buy_close > 0:
                ret_pct = (sell_close - buy_close) / buy_close * 100
            else:
                ret_pct = 0.0

            cycles.append({
                "사이클": cycle_num,
                "매수일": buy_date,
                "매수가($)": round(float(buy_close), 2) if buy_close else None,
                "매도일": sell_date,
                "매도가($)": round(float(sell_close), 2) if sell_close else None,
                "보유기간(일)": hold_days,
                "수익률(%)": round(ret_pct, 2),
                "총자산($)": round(sell_assets, 0),
                "상태": "완료",
                "_start": buy_date,
                "_end": sell_date,
            })
            in_pos = False

    # 현재 진행 중인 사이클
    if in_pos and buy_date is not None:
        last_close = pd.to_numeric(df.iloc[-1].get("close"), errors="coerce")
        hold_days = (df["날짜"].max() - buy_date).days
        ret_pct = ((last_close - buy_close) / buy_close * 100
                   if buy_close and last_close and buy_close > 0 else None)
        cycles.append({
            "사이클": cycle_num,
            "매수일": buy_date,
            "매수가($)": round(float(buy_close), 2) if buy_close else None,
            "매도일": None,
            "매도가($)": None,
            "보유기간(일)": hold_days,
            "수익률(%)": round(ret_pct, 2) if ret_pct is not None else None,
            "총자산($)": None,
            "상태": "보유중",
            "_start": buy_date,
            "_end": df["날짜"].max(),
        })

    return cycles


# ── 커스텀 차트용 시리즈 조합 ───────────────────────────────────

@st.cache_data(ttl=300)
def build_series(name: str, start: datetime, end: datetime) -> Optional[pd.Series]:
    """선택된 시리즈명에 맞는 데이터 반환 (날짜 인덱스 pd.Series)"""
    tickers = {"TQQQ", "SOXL", "SPY", "UPRO", "QLD"}

    if name in tickers:
        df = load_price_history(name, period="10y")
        if df.empty:
            return None
        s = df["close"]

    elif name in ("잔고($)", "수익률(%)"):
        return None  # 백테스트 시트에 포트폴리오 가치 컬럼 없음

    elif name == "RSI(2)":
        df = load_price_history("TQQQ", period="10y")
        if df.empty:
            return None
        s = compute_rsi(df["close"], period=2)

    elif name == "RSI(14)":
        df = load_price_history("TQQQ", period="10y")
        if df.empty:
            return None
        s = compute_rsi(df["close"], period=14)

    elif name == "Fear&Greed":
        try:
            from fear_greed_history import get_fng_for_dates
            df = load_price_history("TQQQ", period="10y")
            if df.empty:
                return None
            fng_raw = get_fng_for_dates(list(df.index.date))
            s = pd.Series(fng_raw, index=df.index).dropna()
        except Exception:
            return None
    else:
        return None

    # 날짜 필터
    s = s.loc[start:end]
    s = s.dropna()
    return s if not s.empty else None
