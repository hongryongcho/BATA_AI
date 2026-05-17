"""
일일 투자 현황 시트 생성
- 대상: TQQQ 100,000 + SOXL 100,000 (독립 운용)
- 분할최적(기존 도출 결과) + 비분할최고(기존 도출 결과) 동시 기록
- Google Sheets 탭: 요청_일일현황
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import yfinance as yf

from backtest_engine import AlgoParams, BacktestEngine
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

START_DATE = "2022-01-01"
END_DATE = "2026-05-16"
CAPITAL = 100_000.0


def run_split_backtest(ticker: str, n_splits: int) -> tuple[pd.DataFrame, dict]:
    """이미 계산된 최적 파라미터를 그대로 사용해 일일 레코드를 생성한다."""
    params = AlgoParams(
        ticker=ticker,
        initial_capital=CAPITAL,
        n_splits=n_splits,
        start_date=START_DATE,
        end_date=END_DATE,
        base_profit_pct=5.0,
        buy_threshold_1=5,
        buy_threshold_2=10,
        buy_threshold_3=15,
        sell_threshold_1=8,
        sell_threshold_2=16,
        sell_threshold_3=24,
        gap_up_pct=2.0,
        is_3x=True,
    )

    engine = BacktestEngine(params=params, fg_series={})
    records, summary = engine.run()

    rows = []
    for r in records:
        rows.append(
            {
                "date": r.date,
                "action": r.action,
                "total_assets": float(r.total_assets),
                "cash": float(r.cash),
                "shares": int(r.shares),
                "close": float(r.close),
            }
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    return df, summary


def download_close(ticker: str) -> pd.Series:
    end_plus = (pd.Timestamp(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START_DATE, end=end_plus, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna().astype(float)
    close.index = pd.to_datetime(close.index)
    return close


def build_non_split_equity(close: pd.Series, mode: str) -> pd.Series:
    if mode == "SMA200":
        sma200 = close.rolling(200).mean()
        pos = (close > sma200).astype(float)
    elif mode == "GoldenCross50_200":
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        pos = (sma50 > sma200).astype(float)
    else:
        raise ValueError(f"지원하지 않는 mode: {mode}")

    ret = close.pct_change().fillna(0.0)
    strat_ret = ret * pos.shift(1).fillna(0.0)
    equity = (1 + strat_ret).cumprod() * CAPITAL
    return equity


def write_daily_sheet(df: pd.DataFrame):
    sheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=sheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(sheet_id)

    title = "요청_일일현황"
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1400, len(df) + 50), cols=16)

    ws.clear()

    top_rows = [
        ["TQQQ 10만 + SOXL 10만 일일 투자 현황 (분할최적 + 비분할최고)"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기간: {START_DATE} ~ {END_DATE}"],
        ["분할최적: TQQQ(N=40, base=5, buy=5/10/15, sell=8/16/24), SOXL(N=20, base=5, buy=5/10/15, sell=8/16/24)"],
        ["비분할최고: TQQQ=SMA200, SOXL=GoldenCross50_200"],
    ]
    ws.update(range_name="A1:N5", values=top_rows)

    headers = [
        "date",
        "split_tqqq_action",
        "split_soxl_action",
        "split_tqqq_assets",
        "split_soxl_assets",
        "split_total_assets",
        "split_total_return_pct",
        "nonsplit_tqqq_assets",
        "nonsplit_soxl_assets",
        "nonsplit_total_assets",
        "nonsplit_total_return_pct",
        "split_vs_nonsplit_gap",
    ]
    ws.update(range_name="A7:L7", values=[headers])

    values = []
    for idx, row in df.iterrows():
        values.append(
            [
                idx.strftime("%Y-%m-%d"),
                row["split_tqqq_action"],
                row["split_soxl_action"],
                round(float(row["split_tqqq_assets"]), 2),
                round(float(row["split_soxl_assets"]), 2),
                round(float(row["split_total_assets"]), 2),
                round(float(row["split_total_return_pct"]), 4),
                round(float(row["nonsplit_tqqq_assets"]), 2),
                round(float(row["nonsplit_soxl_assets"]), 2),
                round(float(row["nonsplit_total_assets"]), 2),
                round(float(row["nonsplit_total_return_pct"]), 4),
                round(float(row["split_vs_nonsplit_gap"]), 2),
            ]
        )

    if values:
        ws.update(range_name=f"A8:L{7 + len(values)}", values=values)

    print("[GoogleSheets] 요청_일일현황 저장 완료")
    print(f"URL: https://docs.google.com/spreadsheets/d/{sheet_id}")


def main():
    # 분할최적 일일 레코드
    tqqq_split, _ = run_split_backtest("TQQQ", n_splits=40)
    soxl_split, _ = run_split_backtest("SOXL", n_splits=20)

    split_df = pd.DataFrame(index=tqqq_split.index.union(soxl_split.index).sort_values())
    split_df["split_tqqq_action"] = tqqq_split["action"]
    split_df["split_soxl_action"] = soxl_split["action"]
    split_df["split_tqqq_assets"] = tqqq_split["total_assets"]
    split_df["split_soxl_assets"] = soxl_split["total_assets"]
    split_df = split_df.ffill().dropna(subset=["split_tqqq_assets", "split_soxl_assets"])
    split_df["split_total_assets"] = split_df["split_tqqq_assets"] + split_df["split_soxl_assets"]
    split_df["split_total_return_pct"] = (split_df["split_total_assets"] / (CAPITAL * 2) - 1) * 100

    # 비분할최고 일일 자산
    tqqq_close = download_close("TQQQ")
    soxl_close = download_close("SOXL")
    ns_tqqq = build_non_split_equity(tqqq_close, "SMA200")
    ns_soxl = build_non_split_equity(soxl_close, "GoldenCross50_200")

    ns_df = pd.DataFrame(index=ns_tqqq.index.union(ns_soxl.index).sort_values())
    ns_df["nonsplit_tqqq_assets"] = ns_tqqq
    ns_df["nonsplit_soxl_assets"] = ns_soxl
    ns_df = ns_df.ffill().dropna(subset=["nonsplit_tqqq_assets", "nonsplit_soxl_assets"])
    ns_df["nonsplit_total_assets"] = ns_df["nonsplit_tqqq_assets"] + ns_df["nonsplit_soxl_assets"]
    ns_df["nonsplit_total_return_pct"] = (ns_df["nonsplit_total_assets"] / (CAPITAL * 2) - 1) * 100

    merged = split_df.join(ns_df, how="inner")
    merged["split_vs_nonsplit_gap"] = merged["split_total_assets"] - merged["nonsplit_total_assets"]

    write_daily_sheet(merged)


if __name__ == "__main__":
    main()
