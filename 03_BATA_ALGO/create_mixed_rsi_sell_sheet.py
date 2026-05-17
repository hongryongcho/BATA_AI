"""
BUY: RSI(2) 기준 유지, SELL: RSI(2) / RSI(4) / RSI(7) / RSI(15) 변경 비교
- 종목: TQQQ, SOXL
- 기간: 2021-01-01 ~ 2026-05-16
- 체결: LOC (장마감 종가 기준)
- 각 SELL RSI 기간별 수익률 비교 + 일별 기록 시트 생성
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import pandas as pd
import numpy as np

import create_nonsplit_best_algo_sheet as base
import search_optimal_strategies as search_mod
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

# ──────────────────────────────────────────────
# 고정 파라미터
# ──────────────────────────────────────────────
START_DATE = search_mod.START_DATE   # "2021-01-01"
END_DATE   = search_mod.END_DATE     # "2026-05-16"
CAPITAL    = search_mod.CAPITAL      # 100_000.0

# 종목별 BUY 기준: RSI(2) < buy_below
# SELL 임계값은 최적 전략과 동일하게 유지하고 SELL RSI 기간만 변경
TICKER_CONFIG = {
    "TQQQ": {"buy_period": 2, "buy_below": 15, "sell_above": 75},
    "SOXL": {"buy_period": 2, "buy_below": 15, "sell_above": 90},
}

SELL_PERIODS = [2, 4, 7, 15]

FILE_TITLE = "TQQQ_SOXL_혼합RSI_SELL비교"


# ──────────────────────────────────────────────
# 시뮬레이션
# ──────────────────────────────────────────────
def simulate_mixed_rsi(
    close: pd.Series,
    buy_rsi: pd.Series,
    sell_rsi: pd.Series,
    buy_below: float,
    sell_above: float,
) -> pd.DataFrame:
    """BUY는 buy_rsi < buy_below, SELL은 sell_rsi > sell_above 기준"""
    cash = CAPITAL
    holdings = 0.0
    rows = []

    for i, (dt, price) in enumerate(close.items()):
        b_val = buy_rsi.iloc[i]
        s_val = sell_rsi.iloc[i]
        action = "HOLD"
        trade_qty = 0.0

        if holdings == 0.0 and not pd.isna(b_val) and b_val < buy_below:
            bought = cash / price
            holdings = bought
            cash = 0.0
            trade_qty = bought
            action = "BUY"
        elif holdings > 0.0 and not pd.isna(s_val) and s_val > sell_above:
            trade_qty = -holdings
            cash = holdings * price
            holdings = 0.0
            action = "SELL"

        total_assets = cash + holdings * price
        rows.append({
            "date": dt.strftime("%Y-%m-%d"),
            "close": round(float(price), 4),
            "rsi2_buy": round(float(b_val), 2) if not pd.isna(b_val) else "",
            "rsi_sell": round(float(s_val), 2) if not pd.isna(s_val) else "",
            "action": action,
            "trade_qty": round(float(trade_qty), 6),
            "holdings": round(float(holdings), 6),
            "cash": round(float(cash), 2),
            "total_assets": round(float(total_assets), 2),
            "return_pct": round(float((total_assets / CAPITAL - 1) * 100), 4),
        })

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


def run_all_variants(ticker: str, close: pd.Series, cfg: dict) -> list[dict]:
    """SELL_PERIODS 별 시뮬레이션 실행 → 결과 목록 반환"""
    buy_rsi = base.rsi(close, cfg["buy_period"])
    variants = []

    for sp in SELL_PERIODS:
        sell_rsi = base.rsi(close, sp)
        df = simulate_mixed_rsi(close, buy_rsi, sell_rsi, cfg["buy_below"], cfg["sell_above"])
        total_ret, cagr, mdd, final_assets = base.calc_perf(df["total_assets"])
        total_trades = int((df["action"] != "HOLD").sum())
        label = f"BUY=RSI(2)<{cfg['buy_below']} / SELL=RSI({sp})>{cfg['sell_above']}"
        variants.append({
            "ticker": ticker,
            "sell_period": sp,
            "label": label,
            "total_return_pct": round(total_ret, 2),
            "cagr_pct": round(cagr, 2),
            "mdd_pct": round(mdd, 2),
            "final_assets": round(final_assets, 2),
            "total_trades": total_trades,
            "df": df,
        })
        print(
            f"  [{ticker}] SELL=RSI({sp:>2}) | 수익 {total_ret:>8.2f}% | "
            f"CAGR {cagr:>6.2f}% | MDD {mdd:>7.2f}% | "
            f"최종 ${final_assets:>14,.2f} | 거래 {total_trades}회"
        )

    return variants


# ──────────────────────────────────────────────
# Google Sheets 쓰기
# ──────────────────────────────────────────────
COLOR_BUY  = {"red": 0.714, "green": 0.933, "blue": 0.714}  # 연초록
COLOR_SELL = {"red": 1.0,   "green": 0.8,   "blue": 0.8}    # 연빨강
COLOR_BEST = {"red": 1.0,   "green": 0.949, "blue": 0.8}    # 연금색 (최고 수익)
COLOR_HEADER_BG = {"red": 0.267, "green": 0.447, "blue": 0.769}  # 짙은 파랑
COLOR_HEADER_FG = {"red": 1.0,   "green": 1.0,   "blue": 1.0}    # 흰색


def _batch_row_colors(ws, df: pd.DataFrame, data_start_row_0: int):
    """BUY/SELL 행 배경색 일괄 적용 (0-indexed data_start_row_0)"""
    num_cols = len(df.columns)
    requests = []
    for i, action in enumerate(df["action"]):
        if action not in ("BUY", "SELL"):
            continue
        r = data_start_row_0 + i
        bg = COLOR_BUY if action == "BUY" else COLOR_SELL
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": r, "endRowIndex": r + 1,
                    "startColumnIndex": 0, "endColumnIndex": num_cols,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def write_summary_tab(ss, all_variants: dict[str, list[dict]]):
    """Summary 탭: 종목별 SELL RSI 기간 비교표 + 설명"""
    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=120, cols=10)

    rows = [
        ["BUY=RSI(2) 고정 / SELL RSI 기간 변경 비교"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기간: {START_DATE} ~ {END_DATE}  |  체결기준: LOC  |  초기자본: $100,000"],
        [],
    ]

    summary_data_starts = {}  # 각 종목 헤더 행 (0-indexed, for formatting)

    for ticker, variants in all_variants.items():
        cfg = TICKER_CONFIG[ticker]
        rows.append([f"▶ {ticker}  —  BUY 조건: RSI(2) < {cfg['buy_below']}  /  SELL 임계값: {cfg['sell_above']}"])
        header_row_idx = len(rows)
        rows.append(["SELL RSI 기간", "전략 레이블", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수", "비고"])
        summary_data_starts[ticker] = (header_row_idx - 1, len(variants))

        best_ret = max(v["total_return_pct"] for v in variants)
        for v in variants:
            note = "★ 최고수익" if v["total_return_pct"] == best_ret else ("기준(원본)" if v["sell_period"] == 2 else "")
            rows.append([
                f"RSI({v['sell_period']})",
                v["label"],
                v["total_return_pct"],
                v["cagr_pct"],
                v["mdd_pct"],
                v["final_assets"],
                v["total_trades"],
                note,
            ])
        rows.append([])

    # RSI 설명
    rows += [
        ["[ RSI 계산 방식 ]"],
        ["공식", "RSI = 100 - (100 / (1 + RS))   RS = 평균상승폭 / 평균하락폭"],
        ["평균 방식", "Wilder 지수이동평균 (EMA 방식과 유사, 스무딩 계수 = 1/N)"],
        ["RSI(2)", "최근 2일 기준 — 단기 과매도/과매수 포착에 최적화, 변동폭 크고 민감"],
        ["RSI(4)", "최근 4일 기준 — RSI(2)보다 부드럽고 노이즈 감소"],
        ["RSI(7)", "최근 7일 기준 — 주간 흐름 반영, 중단기 신호"],
        ["RSI(15)", "최근 15일 기준 — 2~3주 흐름 반영, 안정적이나 느린 반응"],
        [],
        ["[ 체결 방식 (LOC) ]"],
        ["매수 조건", "전일 장마감 시 RSI(2) < buy_limit → 당일 장마감에 전액 매수"],
        ["매도 조건", f"전일 장마감 시 RSI(N) > sell_limit → 당일 장마감에 전액 매도"],
        ["주의", "RSI 값은 당일 장마감 후 계산 → 다음날 LOC 주문 입력 기준"],
        [],
    ]

    ws.update(range_name=f"A1:H{len(rows)}", values=rows)

    # 헤더 행 진한 색 포맷
    requests = []
    for ticker, (hdr_idx, cnt) in summary_data_starts.items():
        # 컬럼 헤더 행 (hdr_idx+1: 0-indexed → 실제 헤더 행)
        col_hdr = hdr_idx + 1
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": col_hdr, "endRowIndex": col_hdr + 1,
                    "startColumnIndex": 0, "endColumnIndex": 8,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_HEADER_BG,
                        "textFormat": {"foregroundColor": COLOR_HEADER_FG, "bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })
        # 최고수익 행 & 기준(원본=RSI2) 행 색 구분
        best_ret = max(v["total_return_pct"] for v in all_variants[ticker])
        for j, v in enumerate(all_variants[ticker]):
            r = col_hdr + 1 + j
            if v["total_return_pct"] == best_ret:
                bg = COLOR_BEST
            elif v["sell_period"] == 2:
                bg = {"red": 0.85, "green": 0.92, "blue": 0.85}
            else:
                continue
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": r, "endRowIndex": r + 1,
                        "startColumnIndex": 0, "endColumnIndex": 8,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })

    if requests:
        ws.spreadsheet.batch_update({"requests": requests})

    print(f"[GoogleSheets] {title} 저장 완료")


def write_daily_tab(ss, ticker: str, variant: dict):
    """일별 기록 탭 1개 작성"""
    sp = variant["sell_period"]
    title = f"{ticker}_SELL_RSI{sp}"
    df = variant["df"]
    headers = list(df.columns)

    # rsi_sell 컬럼 헤더에 기간 반영
    headers[headers.index("rsi_sell")] = f"rsi{sp}_sell"

    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 10), cols=len(headers))

    meta = [
        [f"{ticker} — BUY=RSI(2)<{TICKER_CONFIG[ticker]['buy_below']}  /  SELL=RSI({sp})>{TICKER_CONFIG[ticker]['sell_above']}"],
        [f"수익: {variant['total_return_pct']}%  |  CAGR: {variant['cagr_pct']}%  |  MDD: {variant['mdd_pct']}%  |  최종: ${variant['final_assets']:,}"],
        [f"기간: {START_DATE} ~ {END_DATE}  |  거래: {variant['total_trades']}회"],
        headers,
    ]
    data_start_row_0 = len(meta)  # 0-indexed 데이터 시작 행

    ws.update(range_name=f"A1:{chr(64+len(headers))}{len(meta)}", values=meta)

    values = [["" if (isinstance(v, float) and pd.isna(v)) else str(v) for v in row] for row in df.values.tolist()]
    if values:
        ws.update(
            range_name=f"A{data_start_row_0+1}:{chr(64+len(headers))}{data_start_row_0+len(values)}",
            values=values,
        )

    _batch_row_colors(ws, df, data_start_row_0)
    print(f"  [GoogleSheets] {title} 저장 완료 ({len(df)}행, BUY/SELL {(df['action']!='HOLD').sum()}회)")


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
def main():
    print("=" * 90)
    print(f"[혼합 RSI SELL 비교 시트 생성] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)

    all_variants: dict[str, list[dict]] = {}

    for ticker in search_mod.TICKERS:
        cfg = TICKER_CONFIG[ticker]
        close = base.download_close(ticker)
        print(f"\n[{ticker}]  BUY=RSI(2)<{cfg['buy_below']}  /  SELL 임계값={cfg['sell_above']}")
        variants = run_all_variants(ticker, close, cfg)
        all_variants[ticker] = variants

    # Google Sheets 생성
    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc = sm._get_client()
    ss = gc.create(FILE_TITLE)

    write_summary_tab(ss, all_variants)

    for ticker, variants in all_variants.items():
        for v in variants:
            write_daily_tab(ss, ticker, v)

    # 기본 Sheet1 삭제
    try:
        ss.del_worksheet(ss.worksheet("Sheet1"))
    except Exception:
        pass

    print("\n" + "=" * 90)
    print(f"[완료] 새 구글 시트: {ss.url}")
    tabs = ["Summary"] + [f"{t}_SELL_RSI{sp}" for t in search_mod.TICKERS for sp in SELL_PERIODS]
    print("탭:", " | ".join(tabs))
    print("=" * 90)


if __name__ == "__main__":
    main()
