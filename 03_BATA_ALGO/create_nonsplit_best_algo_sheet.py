"""
비분할 6개 알고리즘 비교 + 종목별 최고 알고리즘 일별 데이터 시트 생성
- 기준: LOC (Limit on Close)
- 시작일: 2021-01-01
- 대상: TQQQ, SOXL
- 알고리즘 6종:
  1) BuyHold
  2) SMA200
  3) GoldenCross50_200
  4) MACD_12_26_9
  5) RSI2_MeanReversion
  6) Donchian20_10
- 출력: 새 Google Sheets 파일
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import numpy as np
import pandas as pd
import yfinance as yf

from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

START_DATE = "2021-01-01"
END_DATE = "2026-05-16"
CAPITAL = 100_000.0
TICKERS = ["TQQQ", "SOXL"]
FILE_TITLE = "비분할6알고리즘_최고수익_일별데이터_2021시작"


@dataclass
class AlgoResult:
    ticker: str
    algo_name: str
    total_return_pct: float
    cagr_pct: float
    mdd_pct: float
    final_assets: float
    total_trades: int
    daily_df: pd.DataFrame


def download_close(ticker: str) -> pd.Series:
    end_plus = (pd.Timestamp(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START_DATE, end=end_plus, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"주가 데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna().astype(float)
    close.index = pd.to_datetime(close.index)
    return close


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_perf(total_assets: pd.Series) -> tuple[float, float, float, float]:
    total_return_pct = (float(total_assets.iloc[-1]) / CAPITAL - 1) * 100
    years = (total_assets.index[-1] - total_assets.index[0]).days / 365.25
    cagr_pct = ((float(total_assets.iloc[-1]) / CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    equity = total_assets / CAPITAL
    mdd_pct = float(((equity / equity.cummax()) - 1).min() * 100)
    final_assets = float(total_assets.iloc[-1])
    return total_return_pct, cagr_pct, mdd_pct, final_assets


def simulate_loc_from_target(
    close: pd.Series,
    target_position: pd.Series,
    extra_columns_factory: Callable[[int], dict] | None = None,
) -> pd.DataFrame:
    cash = CAPITAL
    holdings = 0.0
    rows = []

    for i, (dt, price) in enumerate(close.items()):
        desired = float(target_position.iloc[i]) if not pd.isna(target_position.iloc[i]) else 0.0
        action = "HOLD"
        trade_qty = 0.0

        if desired >= 1.0 and holdings == 0.0:
            bought = cash / price
            trade_qty = bought
            holdings = bought
            cash = 0.0
            action = "BUY"
        elif desired <= 0.0 and holdings > 0.0:
            trade_qty = -holdings
            cash = holdings * price
            holdings = 0.0
            action = "SELL"

        total_assets = cash + holdings * price
        row = {
            "date": dt.strftime("%Y-%m-%d"),
            "close": round(float(price), 4),
            "signal": int(desired),
            "position": "STOCK" if holdings > 0 else "CASH",
            "action": action,
            "trade_qty": round(float(trade_qty), 4),
            "holdings": round(float(holdings), 4),
            "trade_price": round(float(price), 4) if action in ("BUY", "SELL") else "",
            "trade_amount": round(abs(float(trade_qty)) * float(price), 2) if action in ("BUY", "SELL") else "",
            "cash": round(float(cash), 2),
            "total_assets": round(float(total_assets), 2),
            "return_pct": round((float(total_assets) / CAPITAL - 1) * 100, 4),
        }
        if extra_columns_factory is not None:
            row.update(extra_columns_factory(i))
        rows.append(row)

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


def build_buyhold(close: pd.Series) -> pd.DataFrame:
    target = pd.Series(1.0, index=close.index)
    return simulate_loc_from_target(close, target)


def build_sma200(close: pd.Series) -> pd.DataFrame:
    sma200 = close.rolling(200).mean()
    target = ((close > sma200) & sma200.notna()).astype(float)

    def extras(i: int) -> dict:
        value = sma200.iloc[i]
        return {"sma200": round(float(value), 4) if not pd.isna(value) else ""}

    return simulate_loc_from_target(close, target, extras)


def build_golden_cross(close: pd.Series) -> pd.DataFrame:
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    target = ((sma50 > sma200) & sma50.notna() & sma200.notna()).astype(float)

    def extras(i: int) -> dict:
        s50 = sma50.iloc[i]
        s200 = sma200.iloc[i]
        return {
            "sma50": round(float(s50), 4) if not pd.isna(s50) else "",
            "sma200": round(float(s200), 4) if not pd.isna(s200) else "",
        }

    return simulate_loc_from_target(close, target, extras)


def build_macd(close: pd.Series) -> pd.DataFrame:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    target = (macd_line > signal_line).astype(float)

    def extras(i: int) -> dict:
        macd_val = macd_line.iloc[i]
        sig_val = signal_line.iloc[i]
        return {
            "macd": round(float(macd_val), 4) if not pd.isna(macd_val) else "",
            "macd_signal": round(float(sig_val), 4) if not pd.isna(sig_val) else "",
        }

    return simulate_loc_from_target(close, target, extras)


def build_rsi2(close: pd.Series) -> pd.DataFrame:
    rsi2 = rsi(close, 2)
    cash = CAPITAL
    holdings = 0.0
    rows = []

    # 양도세 (해외주식, 연간 실현손익 기준 22%)
    TAX_RATE = 0.22
    TAX_EXEMPTION_USD = 1_900.0
    annual_realized_pnl = 0.0
    current_tax_year = None
    cash_at_buy = 0.0
    pending_tax = 0.0
    pending_tax_year = None

    def _apply_pending_tax() -> float:
        nonlocal cash, pending_tax, pending_tax_year
        if pending_tax <= 0:
            return 0.0
        tax_val = pending_tax
        cash -= tax_val
        pending_tax = 0.0
        pending_tax_year = None
        return tax_val

    for i, (dt, price) in enumerate(close.items()):
        rsi_val = float(rsi2.iloc[i]) if not pd.isna(rsi2.iloc[i]) else None
        action = "HOLD"
        trade_qty = 0.0
        signal = ""

        if current_tax_year is None:
            current_tax_year = dt.year
        elif dt.year != current_tax_year:
            taxable = max(0.0, annual_realized_pnl - TAX_EXEMPTION_USD)
            pending_tax = round(pending_tax + taxable * TAX_RATE, 2) if taxable > 0 else pending_tax
            pending_tax_year = current_tax_year
            annual_realized_pnl = 0.0
            current_tax_year = dt.year

        if rsi_val is not None:
            if holdings == 0.0 and rsi_val < 10:
                _apply_pending_tax()
                cash_at_buy = cash
                bought = cash / price
                trade_qty = bought
                holdings = bought
                cash = 0.0
                action = "BUY"
                signal = 1
            elif holdings > 0.0 and rsi_val > 70:
                cash_at_sell = holdings * price
                trade_qty = -holdings
                cash += cash_at_sell
                holdings = 0.0
                annual_realized_pnl += cash_at_sell - cash_at_buy
                _apply_pending_tax()
                action = "SELL"
                signal = 0
            else:
                signal = 1 if holdings > 0 else 0

        total_assets = cash + holdings * price

        rows.append({
            "date": dt.strftime("%Y-%m-%d"),
            "close": round(float(price), 4),
            "rsi2": round(rsi_val, 4) if rsi_val is not None else "",
            "signal": signal,
            "position": "STOCK" if holdings > 0 else "CASH",
            "action": action,
            "trade_qty": round(float(trade_qty), 4),
            "holdings": round(float(holdings), 4),
            "trade_price": round(float(price), 4) if action in ("BUY", "SELL") else "",
            "trade_amount": round(abs(float(trade_qty)) * float(price), 2) if action in ("BUY", "SELL") else "",
            "cash": round(float(cash), 2),
            "total_assets": round(float(total_assets), 2),
            "return_pct": round((float(total_assets) / CAPITAL - 1) * 100, 4),
        })

    # 마지막 연도 세금 정산
    if pending_tax > 0 and rows:
        rows[-1]["cash"] = round(float(rows[-1]["cash"]) - pending_tax, 2)
        rows[-1]["total_assets"] = round(float(rows[-1]["total_assets"]) - pending_tax, 2)
        rows[-1]["return_pct"] = round((float(rows[-1]["total_assets"]) / CAPITAL - 1) * 100, 4)

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


def build_donchian(close: pd.Series) -> pd.DataFrame:
    high20 = close.rolling(20).max().shift(1)
    low10 = close.rolling(10).min().shift(1)
    cash = CAPITAL
    holdings = 0.0
    rows = []

    for i, (dt, price) in enumerate(close.items()):
        high20_val = float(high20.iloc[i]) if not pd.isna(high20.iloc[i]) else None
        low10_val = float(low10.iloc[i]) if not pd.isna(low10.iloc[i]) else None
        action = "HOLD"
        trade_qty = 0.0
        signal = ""

        if high20_val is not None and low10_val is not None:
            if holdings == 0.0 and price > high20_val:
                bought = cash / price
                trade_qty = bought
                holdings = bought
                cash = 0.0
                action = "BUY"
                signal = 1
            elif holdings > 0.0 and price < low10_val:
                trade_qty = -holdings
                cash = holdings * price
                holdings = 0.0
                action = "SELL"
                signal = 0
            else:
                signal = 1 if holdings > 0 else 0

        total_assets = cash + holdings * price
        rows.append({
            "date": dt.strftime("%Y-%m-%d"),
            "close": round(float(price), 4),
            "donchian_high20": round(high20_val, 4) if high20_val is not None else "",
            "donchian_low10": round(low10_val, 4) if low10_val is not None else "",
            "signal": signal,
            "position": "STOCK" if holdings > 0 else "CASH",
            "action": action,
            "trade_qty": round(float(trade_qty), 4),
            "holdings": round(float(holdings), 4),
            "trade_price": round(float(price), 4) if action in ("BUY", "SELL") else "",
            "trade_amount": round(abs(float(trade_qty)) * float(price), 2) if action in ("BUY", "SELL") else "",
            "cash": round(float(cash), 2),
            "total_assets": round(float(total_assets), 2),
            "return_pct": round((float(total_assets) / CAPITAL - 1) * 100, 4),
        })

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


ALGO_BUILDERS: dict[str, Callable[[pd.Series], pd.DataFrame]] = {
    "BuyHold": build_buyhold,
    "SMA200": build_sma200,
    "GoldenCross50_200": build_golden_cross,
    "MACD_12_26_9": build_macd,
    "RSI2_MeanReversion": build_rsi2,
    "Donchian20_10": build_donchian,
}


def evaluate_algorithms(ticker: str) -> list[AlgoResult]:
    close = download_close(ticker)
    results: list[AlgoResult] = []

    for algo_name, builder in ALGO_BUILDERS.items():
        daily_df = builder(close)
        total_return_pct, cagr_pct, mdd_pct, final_assets = calc_perf(daily_df["total_assets"])
        total_trades = int((daily_df["action"] != "HOLD").sum())
        results.append(
            AlgoResult(
                ticker=ticker,
                algo_name=algo_name,
                total_return_pct=float(total_return_pct),
                cagr_pct=float(cagr_pct),
                mdd_pct=float(mdd_pct),
                final_assets=float(final_assets),
                total_trades=total_trades,
                daily_df=daily_df,
            )
        )

    results.sort(key=lambda item: item.total_return_pct, reverse=True)
    return results


def write_table_tab(ss, title: str, rows: list[list], cols: int):
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(200, len(rows) + 20), cols=cols)

    col_letter = chr(64 + cols) if cols <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}{len(rows)}", values=rows)
    print(f"[GoogleSheets] {title} 저장 완료")


def write_daily_tab(ss, title: str, df: pd.DataFrame, algo_name: str, ticker: str):
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1600, len(df) + 20), cols=len(headers))

    meta_rows = [
        [f"{ticker} 최고수익 알고리즘 일별 데이터"],
        [f"알고리즘: {algo_name} | 체결기준: LOC | 초기자본: ${CAPITAL:,.0f}"],
        [f"기간: {START_DATE} ~ {END_DATE}"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        headers,
    ]
    col_letter = chr(64 + len(headers)) if len(headers) <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}5", values=meta_rows)

    data_rows = []
    for _, row in df.iterrows():
        data_rows.append(["" if pd.isna(v) else str(v) for v in row.tolist()])

    if data_rows:
        ws.update(range_name=f"A6:{col_letter}{5 + len(data_rows)}", values=data_rows)
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행)")


def build_summary_rows(results_by_ticker: dict[str, list[AlgoResult]]) -> list[list]:
    rows: list[list] = [
        ["비분할 6개 알고리즘 최고수익 비교"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기간: {START_DATE} ~ {END_DATE} | 초기자본: 종목별 ${CAPITAL:,.0f} | 체결: LOC"],
        [],
        ["종목", "최고 알고리즘", "최종자산($)", "총수익률(%)", "CAGR(%)", "MDD(%)", "거래횟수"],
    ]
    for ticker in TICKERS:
        best = results_by_ticker[ticker][0]
        rows.append([
            ticker,
            best.algo_name,
            round(best.final_assets, 2),
            round(best.total_return_pct, 2),
            round(best.cagr_pct, 2),
            round(best.mdd_pct, 2),
            best.total_trades,
        ])

    rows.append([])
    rows.append(["알고리즘별 상세 성과는 TQQQ_비교 / SOXL_비교 탭 참조"])
    rows.append(["일별 거래 데이터는 TQQQ_최고일별 / SOXL_최고일별 탭 참조"])
    return rows


def build_compare_rows(ticker: str, results: list[AlgoResult]) -> list[list]:
    rows: list[list] = [
        [f"{ticker} 비분할 6개 알고리즘 성과 비교"],
        [f"체결기준: LOC | 기간: {START_DATE} ~ {END_DATE} | 초기자본: ${CAPITAL:,.0f}"],
        [],
        ["순위", "알고리즘", "최종자산($)", "총수익률(%)", "CAGR(%)", "MDD(%)", "거래횟수"],
    ]
    for rank, result in enumerate(results, start=1):
        rows.append([
            rank,
            result.algo_name,
            round(result.final_assets, 2),
            round(result.total_return_pct, 2),
            round(result.cagr_pct, 2),
            round(result.mdd_pct, 2),
            result.total_trades,
        ])
    return rows


def main():
    print("=" * 80)
    print(f"[비분할 6알고리즘 비교] 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    results_by_ticker: dict[str, list[AlgoResult]] = {}
    for ticker in TICKERS:
        print(f"[{ticker}] 6개 알고리즘 계산 중...")
        results = evaluate_algorithms(ticker)
        results_by_ticker[ticker] = results
        for result in results:
            print(
                f"  {result.algo_name:<20} | 수익 {result.total_return_pct:>8.2f}% | "
                f"CAGR {result.cagr_pct:>7.2f}% | MDD {result.mdd_pct:>7.2f}% | "
                f"자산 ${result.final_assets:>12,.2f}"
            )
        best = results[0]
        print(f"  -> 최고: {best.algo_name} ({best.total_return_pct:.2f}%)")

    existing_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=existing_id)
    gc = sm._get_client()
    ss = gc.create(FILE_TITLE)

    write_table_tab(ss, "Summary", build_summary_rows(results_by_ticker), 7)
    write_table_tab(ss, "TQQQ_비교", build_compare_rows("TQQQ", results_by_ticker["TQQQ"]), 7)
    write_table_tab(ss, "SOXL_비교", build_compare_rows("SOXL", results_by_ticker["SOXL"]), 7)
    write_daily_tab(ss, "TQQQ_최고일별", results_by_ticker["TQQQ"][0].daily_df, results_by_ticker["TQQQ"][0].algo_name, "TQQQ")
    write_daily_tab(ss, "SOXL_최고일별", results_by_ticker["SOXL"][0].daily_df, results_by_ticker["SOXL"][0].algo_name, "SOXL")

    try:
        default_ws = ss.worksheet("Sheet1")
        ss.del_worksheet(default_ws)
    except Exception:
        pass

    print("=" * 80)
    print(f"[완료] 새 구글 시트: {ss.url}")
    print("탭: Summary | TQQQ_비교 | SOXL_비교 | TQQQ_최고일별 | SOXL_최고일별")
    print("=" * 80)


if __name__ == "__main__":
    main()
