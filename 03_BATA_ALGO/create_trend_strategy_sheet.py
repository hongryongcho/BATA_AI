"""
TQQQ SMA200 추세추종 + SOXL 골든크로스(50/200) 전략
- 각각 100,000 USD 시작
- NEW 구글 시트 파일 생성
- 날짜별 일일 레코드 탭 (TQQQ_일별 / SOXL_일별)
- Summary 탭: 마지막 거래일 기준 다음 거래일 매수/매도 구간 정보
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

# ─────────────────────────────────────────────
START_DATE = "2021-01-01"
END_DATE   = "2026-05-16"
CAPITAL    = 100_000.0
NEW_FILE_TITLE = "TQQQ_SOXL_추세전략_SMA200_GoldenCross"
# ─────────────────────────────────────────────


def download_ohlcv(ticker: str) -> pd.DataFrame:
    end_plus = (pd.Timestamp(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START_DATE, end=end_plus, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"주가 데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


# ── SMA200 전략 (TQQQ) ──────────────────────────────────────────
def build_sma200_records(close: pd.Series) -> pd.DataFrame:
    """
    LOC(Limit on Close) 방식: 당일 종가 확인 후 당일 종가에 체결
    - close > SMA200 → 전액 매수 (position=1)
    - close <= SMA200 → 전액 현금 (position=0)
    """
    sma200 = close.rolling(200).mean()
    signal = (close > sma200).astype(int)  # 오늘 신호

    cash      = CAPITAL
    shares    = 0.0
    rows      = []

    for i, (dt, price) in enumerate(close.items()):
        sig     = int(signal.iloc[i])
        sma_val = float(sma200.iloc[i]) if not pd.isna(sma200.iloc[i]) else None
        action    = "HOLD"
        trade_qty = 0.0  # 당일 매매 수량 (+매수 / -매도)

        if sma_val is None:
            # SMA 미형성 구간: 현금 보유
            total = cash
        else:
            if sig == 1 and shares == 0.0:
                # LOC 매수: 종가 확인 → 전액 투입
                bought    = cash / price
                trade_qty = bought
                shares    = bought
                cash      = 0.0
                action    = "BUY"
            elif sig == 0 and shares > 0.0:
                # LOC 매도: 종가 확인 → 전량 청산
                trade_qty = -shares
                cash      = shares * price
                shares    = 0.0
                action    = "SELL"

            total = cash + shares * price

        rows.append({
            "date":        dt.strftime("%Y-%m-%d"),
            "close":       round(price, 4),
            "sma200":      round(sma_val, 4) if sma_val else "",
            "signal":      sig if sma_val else "",
            "position":    "STOCK" if shares > 0 else "CASH",
            "action":      action,
            "trade_qty":   round(trade_qty, 4),   # 당일 매매 수량 (+매수/-매도)
            "holdings":    round(shares, 4),       # 보유 주식 수
            "trade_price": round(price, 4) if action in ("BUY", "SELL") else "",  # 체결 단가
            "trade_amount": round(abs(trade_qty) * price, 2) if action in ("BUY", "SELL") else "",  # 거래 금액
            "cash":        round(cash, 2),
            "total_assets": round(total, 2),
            "return_pct":  round((total / CAPITAL - 1) * 100, 4),
        })

    return pd.DataFrame(rows)


# ── GoldenCross 50/200 전략 (SOXL) ─────────────────────────────
def build_gc_records(close: pd.Series) -> pd.DataFrame:
    """
    LOC(Limit on Close) 방식: 당일 종가 확인 후 당일 종가에 체결
    - SMA50 > SMA200 → 전액 매수 (position=1)
    - SMA50 <= SMA200 → 전액 현금 (position=0)
    """
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    signal = ((sma50 > sma200) & sma50.notna() & sma200.notna()).astype(int)

    cash      = CAPITAL
    shares    = 0.0
    rows      = []

    for i, (dt, price) in enumerate(close.items()):
        sig      = int(signal.iloc[i])
        sma50_v  = float(sma50.iloc[i])  if not pd.isna(sma50.iloc[i])  else None
        sma200_v = float(sma200.iloc[i]) if not pd.isna(sma200.iloc[i]) else None
        action    = "HOLD"
        trade_qty = 0.0  # 당일 매매 수량 (+매수 / -매도)

        if sma50_v is None or sma200_v is None:
            total = cash
        else:
            if sig == 1 and shares == 0.0:
                # LOC 매수: SMA50 > SMA200 확인 → 전액 투입
                bought    = cash / price
                trade_qty = bought
                shares    = bought
                cash      = 0.0
                action    = "BUY"
            elif sig == 0 and shares > 0.0:
                # LOC 매도: SMA50 < SMA200 역전 확인 → 전량 청산
                trade_qty = -shares
                cash      = shares * price
                shares    = 0.0
                action    = "SELL"

            total = cash + shares * price

        rows.append({
            "date":        dt.strftime("%Y-%m-%d"),
            "close":       round(price, 4),
            "sma50":       round(sma50_v, 4)  if sma50_v  else "",
            "sma200":      round(sma200_v, 4) if sma200_v else "",
            "gc_signal":   sig if (sma50_v and sma200_v) else "",
            "position":    "STOCK" if shares > 0 else "CASH",
            "action":      action,
            "trade_qty":   round(trade_qty, 4),   # 당일 매매 수량 (+매수/-매도)
            "holdings":    round(shares, 4),       # 보유 주식 수
            "trade_price": round(price, 4) if action in ("BUY", "SELL") else "",  # 체결 단가
            "trade_amount": round(abs(trade_qty) * price, 2) if action in ("BUY", "SELL") else "",  # 거래 금액
            "cash":        round(cash, 2),
            "total_assets": round(total, 2),
            "return_pct":  round((total / CAPITAL - 1) * 100, 4),
        })

    return pd.DataFrame(rows)


# ── 다음 거래일 매수/매도 구간 분석 ─────────────────────────────
def next_day_signal_info(close: pd.Series, strategy: str) -> dict:
    sma200 = close.rolling(200).mean()
    last_date  = close.index[-1]
    last_close = float(close.iloc[-1])
    last_sma200 = float(sma200.iloc[-1])

    if strategy == "SMA200":
        current_signal = last_close > last_sma200
        position = "STOCK (보유 중)" if current_signal else "CASH (현금 보유 중)"
        buy_zone  = f"종가 > SMA200 (${last_sma200:,.2f}) → 매수 진입"
        sell_zone = f"종가 < SMA200 (${last_sma200:,.2f}) → 전량 매도"
        gap_pct   = (last_close / last_sma200 - 1) * 100

        return {
            "전략":         "TQQQ SMA200 추세추종",
            "마지막거래일":  last_date.strftime("%Y-%m-%d"),
            "현재종가":      f"${last_close:,.2f}",
            "SMA200":       f"${last_sma200:,.2f}",
            "현재포지션":   position,
            "종가_vs_SMA200": f"{gap_pct:+.2f}%",
            "다음거래일_매수구간": buy_zone,
            "다음거래일_매도구간": sell_zone,
            "판단": "매수 유지" if current_signal else "매도 유지 (현금 보유)",
        }

    else:  # GoldenCross50_200
        sma50 = close.rolling(50).mean()
        last_sma50 = float(sma50.iloc[-1])
        current_signal = last_sma50 > last_sma200
        position = "STOCK (보유 중)" if current_signal else "CASH (현금 보유 중)"
        cross_gap = (last_sma50 / last_sma200 - 1) * 100

        # SMA50의 최근 기울기 (5일 변화량)
        sma50_5d_ago = float(sma50.iloc[-6]) if len(sma50) >= 6 else float(sma50.iloc[0])
        sma50_slope  = (last_sma50 - sma50_5d_ago) / 5

        return {
            "전략":         "SOXL 골든크로스 50/200",
            "마지막거래일":  last_date.strftime("%Y-%m-%d"),
            "현재종가":      f"${last_close:,.2f}",
            "SMA50":        f"${last_sma50:,.2f}",
            "SMA200":       f"${last_sma200:,.2f}",
            "현재포지션":   position,
            "SMA50_vs_SMA200": f"{cross_gap:+.2f}%",
            "SMA50_5일기울기": f"${sma50_slope:+.4f}/일",
            "다음거래일_매수구간": f"SMA50(${last_sma50:,.2f}) > SMA200(${last_sma200:,.2f}) 유지 → 매수 보유",
            "다음거래일_매도구간": f"SMA50 < SMA200(${last_sma200:,.2f}) 역전 시 → 전량 매도",
            "판단": "매수 유지" if current_signal else "매도 유지 (현금 보유)",
        }


# ── 구글 시트 쓰기 ────────────────────────────────────────────────
def write_daily_tab(ss, title: str, df: pd.DataFrame, headers: list, ticker: str, strategy_name: str):
    """날짜별 레코드를 시트에 기록한다."""
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1400, len(df) + 20), cols=len(headers))

    meta = [
        [f"{ticker} {strategy_name} 일별 백테스트  [LOC - Limit on Close 기준]"],
        [f"초기자본: ${CAPITAL:,.0f}  |  기간: {START_DATE} ~ {END_DATE}"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        ["trade_qty: 당일 매매 수량(+매수/-매도) | holdings: 보유 주식 수 | trade_amount: 거래금액"],
        headers,
    ]
    ws.update(range_name=f"A1:{chr(64+len(headers))}5", values=meta)

    # 데이터 행 (BUY/SELL 강조를 위해 메모 컬럼 추가)
    values = []
    for _, row in df.iterrows():
        values.append([str(row[h]) if row[h] != "" else "" for h in headers])

    if values:
        col_end = chr(64 + len(headers))
        ws.update(range_name=f"A6:{col_end}{5+len(values)}", values=values)

    print(f"[GoogleSheets] {title} 탭 저장 완료 ({len(df)} 행)")


def write_summary_tab(ss, tqqq_info: dict, soxl_info: dict,
                      tqqq_df: pd.DataFrame, soxl_df: pd.DataFrame):
    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=80, cols=4)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 최종 자산 계산
    tqqq_final = float(tqqq_df["total_assets"].iloc[-1])
    soxl_final = float(soxl_df["total_assets"].iloc[-1])
    tqqq_ret   = float(tqqq_df["return_pct"].iloc[-1])
    soxl_ret   = float(soxl_df["return_pct"].iloc[-1])
    combined   = tqqq_final + soxl_final
    combined_ret = (combined / (CAPITAL * 2) - 1) * 100

    # MDD 계산
    def calc_mdd(assets: pd.Series) -> float:
        eq = assets / CAPITAL
        return float(((eq / eq.cummax()) - 1).min() * 100)

    tqqq_mdd = calc_mdd(tqqq_df["total_assets"])
    soxl_mdd = calc_mdd(soxl_df["total_assets"])

    rows = [
        ["TQQQ SMA200 + SOXL GoldenCross 50/200 전략 요약"],
        [f"생성시간: {now_str}"],
        [f"기간: {START_DATE} ~ {END_DATE}  |  초기자본: TQQQ $100,000 + SOXL $100,000"],
        [],
        ["═══════════════ 전략 성과 ═══════════════"],
        ["항목", "TQQQ (SMA200)", "SOXL (GoldenCross 50/200)", "합산"],
        ["초기자본",       f"$100,000",          f"$100,000",          f"$200,000"],
        ["최종자산",       f"${tqqq_final:,.2f}", f"${soxl_final:,.2f}", f"${combined:,.2f}"],
        ["총수익률",       f"{tqqq_ret:+.2f}%",  f"{soxl_ret:+.2f}%",  f"{combined_ret:+.2f}%"],
        ["MDD",           f"{tqqq_mdd:.2f}%",   f"{soxl_mdd:.2f}%",   ""],
        [],
        ["═══════════════ 다음 거래일 신호 (TQQQ SMA200) ═══════════════"],
    ]

    for k, v in tqqq_info.items():
        rows.append([k, v])

    rows.append([])
    rows.append(["═══════════════ 다음 거래일 신호 (SOXL GoldenCross 50/200) ═══════════════"])

    for k, v in soxl_info.items():
        rows.append([k, v])

    rows.append([])
    rows.append(["═══════════════ 최근 5거래일 현황 ═══════════════"])
    rows.append(["날짜", "TQQQ종가", "SOXL종가", "TQQQ자산", "SOXL자산", "합산자산"])

    # 최근 5일 공통 날짜
    tqqq_tail = tqqq_df.tail(5)
    soxl_tail = soxl_df.tail(5)
    for i in range(max(len(tqqq_tail), len(soxl_tail))):
        tr = tqqq_tail.iloc[i] if i < len(tqqq_tail) else None
        sr = soxl_tail.iloc[i] if i < len(soxl_tail) else None
        rows.append([
            tr["date"] if tr is not None else "",
            f"${float(tr['close']):,.2f}" if tr is not None else "",
            f"${float(sr['close']):,.2f}" if sr is not None else "",
            f"${float(tr['total_assets']):,.2f}" if tr is not None else "",
            f"${float(sr['total_assets']):,.2f}" if sr is not None else "",
            f"${(float(tr['total_assets']) + float(sr['total_assets'])):,.2f}"
            if (tr is not None and sr is not None) else "",
        ])

    # 시트에 기록
    max_cols = max(len(r) for r in rows)
    col_letter = chr(64 + max_cols) if max_cols <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}{len(rows)}", values=rows)

    print(f"[GoogleSheets] {title} 탭 저장 완료")


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print(f"[TREND STRATEGY] 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 주가 다운로드
    print("[1/5] TQQQ / SOXL 주가 다운로드...")
    tqqq_df_raw = download_ohlcv("TQQQ")
    soxl_df_raw = download_ohlcv("SOXL")
    tqqq_close  = tqqq_df_raw["Close"]
    soxl_close  = soxl_df_raw["Close"]
    print(f"  TQQQ: {len(tqqq_close)}일  |  SOXL: {len(soxl_close)}일")

    # 2. 전략 시뮬레이션
    print("[2/5] 전략 시뮬레이션...")
    tqqq_records = build_sma200_records(tqqq_close)
    soxl_records = build_gc_records(soxl_close)
    print(f"  TQQQ SMA200: 최종 자산 ${float(tqqq_records['total_assets'].iloc[-1]):,.2f}")
    print(f"  SOXL GC50/200: 최종 자산 ${float(soxl_records['total_assets'].iloc[-1]):,.2f}")

    # 3. 다음 거래일 신호 계산
    print("[3/5] 다음 거래일 신호 분석...")
    tqqq_signal = next_day_signal_info(tqqq_close, "SMA200")
    soxl_signal = next_day_signal_info(soxl_close, "GoldenCross50_200")
    print("  [TQQQ 신호]")
    for k, v in tqqq_signal.items():
        print(f"    {k}: {v}")
    print("  [SOXL 신호]")
    for k, v in soxl_signal.items():
        print(f"    {k}: {v}")

    # 4. 구글 시트 새 파일 생성
    print("[4/5] 구글 시트 새 파일 생성 중...")
    existing_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=existing_id)
    gc = sm._get_client()

    ss = gc.create(NEW_FILE_TITLE)
    print(f"  새 파일 생성 완료: {ss.url}")

    # 5. 시트 탭 작성
    print("[5/5] 시트 탭 작성 중...")

    # TQQQ 일별 탭
    tqqq_headers = ["date", "close", "sma200", "signal", "position", "action",
                    "trade_qty", "holdings", "trade_price", "trade_amount",
                    "cash", "total_assets", "return_pct"]
    write_daily_tab(ss, "TQQQ_일별", tqqq_records, tqqq_headers,
                    "TQQQ", "SMA200 추세추종")

    # SOXL 일별 탭
    soxl_headers = ["date", "close", "sma50", "sma200", "gc_signal", "position",
                    "action", "trade_qty", "holdings", "trade_price", "trade_amount",
                    "cash", "total_assets", "return_pct"]
    write_daily_tab(ss, "SOXL_일별", soxl_records, soxl_headers,
                    "SOXL", "골든크로스 50/200")

    # Summary 탭
    write_summary_tab(ss, tqqq_signal, soxl_signal, tqqq_records, soxl_records)

    # 기본 생성되는 "Sheet1" 삭제
    try:
        default_ws = ss.worksheet("Sheet1")
        ss.del_worksheet(default_ws)
    except Exception:
        pass

    print()
    print("=" * 70)
    print(f"[완료] 구글 시트 파일: {ss.url}")
    print(f"  탭 구성: TQQQ_일별 | SOXL_일별 | Summary")
    print("=" * 70)


if __name__ == "__main__":
    main()
