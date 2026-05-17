"""
TQQQ / SOXL 최적 전략 Google Sheets 생성
- 기간: 2021-01-01 ~ 2026-05-16
- 종목별 최적 전략 1개 선정
- Summary + 일별 매수/매도 기록 탭 생성
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

import search_optimal_strategies as search_mod
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

FILE_TITLE = "TQQQ_SOXL_최적전략_일별기록"


def write_table(ss, title: str, rows: list[list], cols: int):
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(200, len(rows) + 20), cols=cols)

    col_letter = chr(64 + cols) if cols <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}{len(rows)}", values=rows)
    print(f"[GoogleSheets] {title} 저장 완료")


def _apply_row_colors(ws, df: pd.DataFrame, data_start_row: int):
    """BUY 행=초록, SELL 행=빨강 배경색 일괄 적용"""
    num_cols = len(df.columns)
    buy_color = {"red": 0.714, "green": 0.933, "blue": 0.714}   # 연초록
    sell_color = {"red": 1.0, "green": 0.8, "blue": 0.8}         # 연빨강

    requests = []
    for i, action in enumerate(df["action"]):
        if action not in ("BUY", "SELL"):
            continue
        row_idx = data_start_row + i  # 0-indexed
        bg = buy_color if action == "BUY" else sell_color
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": bg
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    if requests:
        ws.spreadsheet.batch_update({"requests": requests})
        print(f"  └─ 색상 적용: BUY/SELL {len(requests)}행")


def write_daily_df(ss, title: str, df: pd.DataFrame, meta_lines: list[str]):
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 20), cols=len(headers))

    meta_rows = [[line] for line in meta_lines]
    meta_rows.append(headers)

    col_letter = chr(64 + len(headers)) if len(headers) <= 26 else "Z"
    header_row = len(meta_rows)
    ws.update(range_name=f"A1:{col_letter}{header_row}", values=meta_rows)

    values = []
    for _, row in df.iterrows():
        values.append(["" if pd.isna(v) else str(v) for v in row.tolist()])
    if values:
        ws.update(range_name=f"A{header_row + 1}:{col_letter}{header_row + len(values)}", values=values)

    # BUY/SELL 행 색상 적용 (data_start_row는 0-indexed)
    _apply_row_colors(ws, df, data_start_row=header_row)

    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행)")


RSI_DESCRIPTION = [
    ["[ RSI (Relative Strength Index) 계산 방식 ]"],
    ["공식", "RSI = 100 - (100 / (1 + RS))   여기서 RS = 평균상승폭 / 평균하락폭"],
    ["기간", "본 전략은 RSI(2) 사용 — 최근 2거래일 기준으로 계산 (단기 평균회귀에 최적화)"],
    ["평균상승폭", "최근 N일 중 전일 대비 상승한 날의 변동폭 평균 (Wilder 방식 지수이동평균)"],
    ["평균하락폭", "최근 N일 중 전일 대비 하락한 날의 변동폭 평균 (절대값, Wilder 방식 지수이동평균)"],
    ["범위", "0 ~ 100  |  낮을수록 과매도(매수 신호), 높을수록 과매수(매도 신호)"],
    [],
    ["[ 매매 임계값 (Threshold) ]"],
    ["buy_limit",  "RSI 가 이 값 이하일 때 매수 신호 발생 (장마감 종가 확인 후 당일 LOC 체결)"],
    ["sell_limit", "RSI 가 이 값 이상일 때 매도 신호 발생 (장마감 종가 확인 후 당일 LOC 체결)"],
    ["체결 방식", "LOC (Limit-On-Close): 장마감 직전 종가 기준으로 주문 체결"],
    ["매수 조건", "전일 장마감 시 RSI < buy_limit → 당일 장마감에 전액 매수"],
    ["매도 조건", "전일 장마감 시 RSI > sell_limit → 당일 장마감에 전액 매도"],
    [],
]


def build_summary_rows(best_results):
    rows = [
        ["TQQQ / SOXL 최적 전략 요약"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기간: {search_mod.START_DATE} ~ {search_mod.END_DATE} | 체결기준: LOC | 초기자본: 종목별 $100,000"],
        [],
        ["종목", "전략명", "전략군", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수", "buy_limit", "sell_limit"],
    ]

    for ticker, result in best_results.items():
        p = result.params
        buy_limit = p.get("buy_below", "-")
        sell_limit = p.get("sell_above", "-")
        rows.append([
            ticker,
            result.strategy_name,
            result.family,
            round(result.total_return_pct, 2),
            round(result.cagr_pct, 2),
            round(result.mdd_pct, 2),
            round(result.final_assets, 2),
            result.total_trades,
            buy_limit,
            sell_limit,
        ])
        rows.append(["조건문", search_mod.describe_rule(result)])
        rows.append(["파라미터", str(result.params)])
        rows.append([])

    rows.append([])
    rows.extend(RSI_DESCRIPTION)
    return rows


def main():
    print("=" * 80)
    print(f"[최적전략 시트 생성] 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    best_results = {}
    daily_dfs = {}

    for ticker in search_mod.TICKERS:
        results = search_mod.search_all(ticker)
        best = results[0]
        best_results[ticker] = best

        close = search_mod.base.download_close(ticker)
        daily_df = search_mod.build_daily_df_from_result(close, best)
        # buy_limit / sell_limit 컬럼 추가 (RSI 임계값 상수 컬럼)
        p = best.params
        if "buy_below" in p:
            daily_df.insert(daily_df.columns.get_loc("rsi2") + 1, "buy_limit", p["buy_below"])
            daily_df.insert(daily_df.columns.get_loc("buy_limit") + 1, "sell_limit", p["sell_above"])
        daily_dfs[ticker] = daily_df

        print(
            f"[{ticker}] {best.strategy_name} | {best.family} | "
            f"수익 {best.total_return_pct:.2f}% | CAGR {best.cagr_pct:.2f}% | "
            f"MDD {best.mdd_pct:.2f}% | 최종 ${best.final_assets:,.2f}"
        )

    existing_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=existing_id)
    gc = sm._get_client()
    ss = gc.create(FILE_TITLE)

    write_table(ss, "Summary", build_summary_rows(best_results), 10)

    for ticker in search_mod.TICKERS:
        result = best_results[ticker]
        daily_df = daily_dfs[ticker]
        meta_lines = [
            f"{ticker} 최적 전략 일별 기록",
            f"전략명: {result.strategy_name} | 전략군: {result.family}",
            f"조건문: {search_mod.describe_rule(result)}",
            f"파라미터: {result.params}",
            f"기간: {search_mod.START_DATE} ~ {search_mod.END_DATE} | 체결기준: LOC",
        ]
        write_daily_df(ss, f"{ticker}_최적전략_일별", daily_df, meta_lines)

    try:
        default_ws = ss.worksheet("Sheet1")
        ss.del_worksheet(default_ws)
    except Exception:
        pass

    print("=" * 80)
    print(f"[완료] 새 구글 시트: {ss.url}")
    print("탭: Summary | TQQQ_최적전략_일별 | SOXL_최적전략_일별")
    print("=" * 80)


if __name__ == "__main__":
    main()
