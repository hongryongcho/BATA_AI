"""
TQQQ / SOXL 최적 매수·매도 알고리즘 탐색
- 기존 고정 전략을 확장한 넓은 전략군 탐색
- LOC (종가 확인 후 종가 체결) 기준
- 기간: 2021-01-01 ~ 2026-05-16
- 목적함수: 총수익률 최대
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

import numpy as np
import pandas as pd

import create_nonsplit_best_algo_sheet as base

START_DATE = "2021-01-01"
END_DATE = "2026-05-16"
CAPITAL = 100_000.0
TICKERS = ["TQQQ", "SOXL"]

base.START_DATE = START_DATE
base.END_DATE = END_DATE


@dataclass
class SearchResult:
    ticker: str
    family: str
    strategy_name: str
    params: dict
    total_return_pct: float
    cagr_pct: float
    mdd_pct: float
    final_assets: float
    total_trades: int


def simulate_target_strategy(close: pd.Series, target: pd.Series) -> pd.DataFrame:
    cash = CAPITAL
    holdings = 0.0
    rows = []

    for dt, price in close.items():
        desired = int(target.loc[dt]) if not pd.isna(target.loc[dt]) else 0
        action = "HOLD"
        trade_qty = 0.0

        if desired == 1 and holdings == 0.0:
            bought = cash / price
            holdings = bought
            cash = 0.0
            trade_qty = bought
            action = "BUY"
        elif desired == 0 and holdings > 0.0:
            trade_qty = -holdings
            cash = holdings * price
            holdings = 0.0
            action = "SELL"

        total_assets = cash + holdings * price
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "close": float(price),
                "signal": desired,
                "action": action,
                "trade_qty": float(trade_qty),
                "holdings": float(holdings),
                "cash": float(cash),
                "total_assets": float(total_assets),
                "return_pct": float((total_assets / CAPITAL - 1) * 100),
            }
        )

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


def simulate_state_strategy(close: pd.Series, decide: Callable[[int, pd.Series, float], str]) -> pd.DataFrame:
    cash = CAPITAL
    holdings = 0.0
    rows = []

    for i, (dt, price) in enumerate(close.items()):
        decision = decide(i, close, holdings)
        action = "HOLD"
        trade_qty = 0.0

        if decision == "BUY" and holdings == 0.0:
            bought = cash / price
            holdings = bought
            cash = 0.0
            trade_qty = bought
            action = "BUY"
        elif decision == "SELL" and holdings > 0.0:
            trade_qty = -holdings
            cash = holdings * price
            holdings = 0.0
            action = "SELL"

        total_assets = cash + holdings * price
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "close": float(price),
                "action": action,
                "trade_qty": float(trade_qty),
                "holdings": float(holdings),
                "cash": float(cash),
                "total_assets": float(total_assets),
                "return_pct": float((total_assets / CAPITAL - 1) * 100),
            }
        )

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


def summarize_strategy(ticker: str, family: str, strategy_name: str, params: dict, df: pd.DataFrame) -> SearchResult:
    total_return_pct, cagr_pct, mdd_pct, final_assets = base.calc_perf(df["total_assets"])
    total_trades = int((df["action"] != "HOLD").sum())
    return SearchResult(
        ticker=ticker,
        family=family,
        strategy_name=strategy_name,
        params=params,
        total_return_pct=float(total_return_pct),
        cagr_pct=float(cagr_pct),
        mdd_pct=float(mdd_pct),
        final_assets=float(final_assets),
        total_trades=total_trades,
    )


def search_sma_trend(ticker: str, close: pd.Series) -> list[SearchResult]:
    results = []
    for window in [20, 30, 50, 75, 100, 120, 150, 180, 200, 220, 250, 300]:
        sma = close.rolling(window).mean()
        target = ((close > sma) & sma.notna()).astype(int)
        df = simulate_target_strategy(close, target)
        results.append(summarize_strategy(ticker, "SMA_Trend", f"SMA{window}", {"window": window}, df))
    return results


def search_dual_sma_cross(ticker: str, close: pd.Series) -> list[SearchResult]:
    results = []
    windows = [5, 10, 20, 30, 50, 75, 100, 150, 200]
    for fast, slow in product(windows, windows):
        if fast >= slow:
            continue
        fast_sma = close.rolling(fast).mean()
        slow_sma = close.rolling(slow).mean()
        target = ((fast_sma > slow_sma) & fast_sma.notna() & slow_sma.notna()).astype(int)
        df = simulate_target_strategy(close, target)
        results.append(
            summarize_strategy(
                ticker,
                "Dual_SMA_Cross",
                f"SMA{fast}_{slow}",
                {"fast": fast, "slow": slow},
                df,
            )
        )
    return results


def search_ema_cross(ticker: str, close: pd.Series) -> list[SearchResult]:
    results = []
    windows = [3, 5, 8, 10, 12, 15, 20, 30, 50, 80, 100, 150, 200]
    for fast, slow in product(windows, windows):
        if fast >= slow:
            continue
        fast_ema = close.ewm(span=fast, adjust=False).mean()
        slow_ema = close.ewm(span=slow, adjust=False).mean()
        target = (fast_ema > slow_ema).astype(int)
        df = simulate_target_strategy(close, target)
        results.append(
            summarize_strategy(
                ticker,
                "EMA_Cross",
                f"EMA{fast}_{slow}",
                {"fast": fast, "slow": slow},
                df,
            )
        )
    return results


def search_rsi_mean_reversion(ticker: str, close: pd.Series) -> list[SearchResult]:
    results = []
    for period, buy_th, sell_th in product([2, 3, 4, 5, 7], [3, 5, 8, 10, 12, 15, 20], [55, 60, 65, 70, 75, 80, 85, 90]):
        if buy_th >= sell_th:
            continue
        rsi_series = base.rsi(close, period)

        def decide(i: int, price_series: pd.Series, holdings: float) -> str:
            rsi_val = rsi_series.iloc[i]
            if pd.isna(rsi_val):
                return "HOLD"
            if holdings == 0.0 and rsi_val < buy_th:
                return "BUY"
            if holdings > 0.0 and rsi_val > sell_th:
                return "SELL"
            return "HOLD"

        df = simulate_state_strategy(close, decide)
        results.append(
            summarize_strategy(
                ticker,
                "RSI_MeanReversion",
                f"RSI{period}_{buy_th}_{sell_th}",
                {"period": period, "buy_below": buy_th, "sell_above": sell_th},
                df,
            )
        )
    return results


def search_donchian(ticker: str, close: pd.Series) -> list[SearchResult]:
    results = []
    for entry, exit_ in product([10, 20, 30, 40, 50, 60, 80, 100], [5, 10, 15, 20, 30, 40]):
        if exit_ >= entry:
            continue
        high_n = close.rolling(entry).max().shift(1)
        low_n = close.rolling(exit_).min().shift(1)

        def decide(i: int, price_series: pd.Series, holdings: float) -> str:
            c = price_series.iloc[i]
            hi = high_n.iloc[i]
            lo = low_n.iloc[i]
            if pd.isna(hi) or pd.isna(lo):
                return "HOLD"
            if holdings == 0.0 and c > hi:
                return "BUY"
            if holdings > 0.0 and c < lo:
                return "SELL"
            return "HOLD"

        df = simulate_state_strategy(close, decide)
        results.append(
            summarize_strategy(
                ticker,
                "Donchian_Breakout",
                f"Donchian_{entry}_{exit_}",
                {"entry": entry, "exit": exit_},
                df,
            )
        )
    return results


def search_bollinger_mean_reversion(ticker: str, close: pd.Series) -> list[SearchResult]:
    results = []
    for window, std_mult, exit_mode in product([10, 15, 20, 30, 40], [1.5, 2.0, 2.5, 3.0], ["mid", "upper"]):
        mid = close.rolling(window).mean()
        std = close.rolling(window).std()
        lower = mid - std_mult * std
        upper = mid + std_mult * std

        def decide(i: int, price_series: pd.Series, holdings: float) -> str:
            c = price_series.iloc[i]
            m = mid.iloc[i]
            lo = lower.iloc[i]
            up = upper.iloc[i]
            if pd.isna(m) or pd.isna(lo) or pd.isna(up):
                return "HOLD"
            if holdings == 0.0 and c < lo:
                return "BUY"
            if holdings > 0.0:
                if exit_mode == "mid" and c > m:
                    return "SELL"
                if exit_mode == "upper" and c > up:
                    return "SELL"
            return "HOLD"

        df = simulate_state_strategy(close, decide)
        results.append(
            summarize_strategy(
                ticker,
                "Bollinger_MeanReversion",
                f"BB_{window}_{std_mult}_{exit_mode}",
                {"window": window, "std_mult": std_mult, "exit_mode": exit_mode},
                df,
            )
        )
    return results


def search_all(ticker: str) -> list[SearchResult]:
    close = base.download_close(ticker)
    results: list[SearchResult] = []
    results.extend(search_sma_trend(ticker, close))
    results.extend(search_dual_sma_cross(ticker, close))
    results.extend(search_ema_cross(ticker, close))
    results.extend(search_rsi_mean_reversion(ticker, close))
    results.extend(search_donchian(ticker, close))
    results.extend(search_bollinger_mean_reversion(ticker, close))
    results.sort(key=lambda x: x.total_return_pct, reverse=True)
    return results


def build_daily_df_from_result(close: pd.Series, result: SearchResult) -> pd.DataFrame:
    p = result.params

    if result.family == "SMA_Trend":
        sma = close.rolling(p["window"]).mean()
        target = ((close > sma) & sma.notna()).astype(int)
        df = simulate_target_strategy(close, target)
        df["indicator_1"] = sma.round(4)
        return df

    if result.family == "Dual_SMA_Cross":
        fast_sma = close.rolling(p["fast"]).mean()
        slow_sma = close.rolling(p["slow"]).mean()
        target = ((fast_sma > slow_sma) & fast_sma.notna() & slow_sma.notna()).astype(int)
        df = simulate_target_strategy(close, target)
        df["indicator_1"] = fast_sma.round(4)
        df["indicator_2"] = slow_sma.round(4)
        return df

    if result.family == "EMA_Cross":
        fast_ema = close.ewm(span=p["fast"], adjust=False).mean()
        slow_ema = close.ewm(span=p["slow"], adjust=False).mean()
        target = (fast_ema > slow_ema).astype(int)
        df = simulate_target_strategy(close, target)
        df["indicator_1"] = fast_ema.round(4)
        df["indicator_2"] = slow_ema.round(4)
        return df

    if result.family == "RSI_MeanReversion":
        rsi_series = base.rsi(close, p["period"])

        def decide(i: int, price_series: pd.Series, holdings: float) -> str:
            rsi_val = rsi_series.iloc[i]
            if pd.isna(rsi_val):
                return "HOLD"
            if holdings == 0.0 and rsi_val < p["buy_below"]:
                return "BUY"
            if holdings > 0.0 and rsi_val > p["sell_above"]:
                return "SELL"
            return "HOLD"

        df = simulate_state_strategy(close, decide)
        df[f"rsi{p['period']}"] = rsi_series.values.round(4)
        return df

    if result.family == "Donchian_Breakout":
        high_n = close.rolling(p["entry"]).max().shift(1)
        low_n = close.rolling(p["exit"]).min().shift(1)

        def decide(i: int, price_series: pd.Series, holdings: float) -> str:
            c = price_series.iloc[i]
            hi = high_n.iloc[i]
            lo = low_n.iloc[i]
            if pd.isna(hi) or pd.isna(lo):
                return "HOLD"
            if holdings == 0.0 and c > hi:
                return "BUY"
            if holdings > 0.0 and c < lo:
                return "SELL"
            return "HOLD"

        df = simulate_state_strategy(close, decide)
        df["indicator_1"] = high_n.round(4)
        df["indicator_2"] = low_n.round(4)
        return df

    if result.family == "Bollinger_MeanReversion":
        mid = close.rolling(p["window"]).mean()
        std = close.rolling(p["window"]).std()
        lower = mid - p["std_mult"] * std
        upper = mid + p["std_mult"] * std

        def decide(i: int, price_series: pd.Series, holdings: float) -> str:
            c = price_series.iloc[i]
            m = mid.iloc[i]
            lo = lower.iloc[i]
            up = upper.iloc[i]
            if pd.isna(m) or pd.isna(lo) or pd.isna(up):
                return "HOLD"
            if holdings == 0.0 and c < lo:
                return "BUY"
            if holdings > 0.0:
                if p["exit_mode"] == "mid" and c > m:
                    return "SELL"
                if p["exit_mode"] == "upper" and c > up:
                    return "SELL"
            return "HOLD"

        df = simulate_state_strategy(close, decide)
        df["indicator_1"] = lower.round(4)
        df["indicator_2"] = mid.round(4)
        df["indicator_3"] = upper.round(4)
        return df

    raise ValueError(f"지원하지 않는 family: {result.family}")


def describe_rule(result: SearchResult) -> str:
    p = result.params
    if result.family == "SMA_Trend":
        return f"매수: 종가 > SMA{p['window']} / 매도: 종가 <= SMA{p['window']}"
    if result.family == "Dual_SMA_Cross":
        return f"매수: SMA{p['fast']} > SMA{p['slow']} / 매도: SMA{p['fast']} <= SMA{p['slow']}"
    if result.family == "EMA_Cross":
        return f"매수: EMA{p['fast']} > EMA{p['slow']} / 매도: EMA{p['fast']} <= EMA{p['slow']}"
    if result.family == "RSI_MeanReversion":
        return f"매수: RSI({p['period']}) < {p['buy_below']} / 매도: RSI({p['period']}) > {p['sell_above']}"
    if result.family == "Donchian_Breakout":
        return f"매수: 종가 > 최근 {p['entry']}일 최고가 / 매도: 종가 < 최근 {p['exit']}일 최저가"
    if result.family == "Bollinger_MeanReversion":
        if p['exit_mode'] == 'mid':
            return f"매수: 종가 < 볼린저 하단({p['window']}일, {p['std_mult']}σ) / 매도: 종가 > 중심선"
        return f"매수: 종가 < 볼린저 하단({p['window']}일, {p['std_mult']}σ) / 매도: 종가 > 볼린저 상단"
    return ""


def main():
    for ticker in TICKERS:
        print("=" * 100)
        print(f"[{ticker}] 최적 전략 탐색")
        print("=" * 100)
        results = search_all(ticker)
        for rank, result in enumerate(results[:10], start=1):
            print(
                f"{rank}. {result.strategy_name:<20} | family={result.family:<24} | "
                f"return={result.total_return_pct:>8.2f}% | CAGR={result.cagr_pct:>7.2f}% | "
                f"MDD={result.mdd_pct:>7.2f}% | final=${result.final_assets:>12,.2f} | trades={result.total_trades:>4}"
            )
            print(f"   params={result.params}")
            print(f"   rule={describe_rule(result)}")


if __name__ == "__main__":
    main()
