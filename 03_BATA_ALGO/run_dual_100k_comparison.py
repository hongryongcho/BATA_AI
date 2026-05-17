"""
요청 전용 실행 스크립트
- 자금 분리: TQQQ 100,000 USD + SOXL 100,000 USD (각각 독립)
- 1) 분할매수/분할매도 Grid Search 최적화 (각 종목별)
- 2) 비분할(유명 알고리즘) 최대수익 비교 (각 종목별)
- 3) Google Sheets에 결과 저장

기간: 2022-01-01 ~ 2026-05-16
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_engine import AlgoParams, BacktestEngine, DayRecord
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id


START_DATE = "2022-01-01"
END_DATE = "2026-05-16"
CAPITAL_PER_TICKER = 100_000.0
TICKERS = ["TQQQ", "SOXL"]


@dataclass
class SplitBest:
    ticker: str
    params: dict
    summary: dict
    records: List[DayRecord]


@dataclass
class AlgoPerf:
    ticker: str
    algo_name: str
    total_return_pct: float
    cagr_pct: float
    mdd_pct: float
    final_assets: float


def run_split_grid_search(ticker: str) -> SplitBest:
    print("=" * 90)
    print(f"[분할최적화] {ticker} 시작")
    print("=" * 90)

    n_splits_options = [20, 30, 40, 50]
    base_profit_options = [1.0, 2.0, 3.0, 5.0]
    buy_threshold_options = [
        (8, 12, 16),
        (10, 15, 20),
        (5, 10, 15),
        (12, 18, 24),
    ]
    sell_threshold_options = [
        (8, 16, 24),
        (10, 20, 30),
        (5, 15, 25),
        (12, 24, 36),
        (15, 30, 45),
    ]

    total = (
        len(n_splits_options)
        * len(base_profit_options)
        * len(buy_threshold_options)
        * len(sell_threshold_options)
    )
    print(f"[분할최적화] {ticker} 조합수: {total}")

    best_return = -10**9
    best_payload = None
    iteration = 0

    for n_splits, base_profit, buy_t, sell_t in itertools.product(
        n_splits_options,
        base_profit_options,
        buy_threshold_options,
        sell_threshold_options,
    ):
        iteration += 1

        params = AlgoParams(
            ticker=ticker,
            initial_capital=CAPITAL_PER_TICKER,
            n_splits=n_splits,
            start_date=START_DATE,
            end_date=END_DATE,
            base_profit_pct=base_profit,
            buy_threshold_1=buy_t[0],
            buy_threshold_2=buy_t[1],
            buy_threshold_3=buy_t[2],
            sell_threshold_1=sell_t[0],
            sell_threshold_2=sell_t[1],
            sell_threshold_3=sell_t[2],
            gap_up_pct=2.0,
            is_3x=True,
        )

        try:
            engine = BacktestEngine(params=params, fg_series={})
            records, summary = engine.run()
            ret = float(summary["total_return_pct"])

            if ret > best_return:
                best_return = ret
                best_payload = {
                    "params": {
                        "n_splits": n_splits,
                        "base_profit_pct": base_profit,
                        "buy_threshold_1": buy_t[0],
                        "buy_threshold_2": buy_t[1],
                        "buy_threshold_3": buy_t[2],
                        "sell_threshold_1": sell_t[0],
                        "sell_threshold_2": sell_t[1],
                        "sell_threshold_3": sell_t[2],
                        "gap_up_pct": 2.0,
                    },
                    "summary": summary,
                    "records": records,
                }

            if iteration % 20 == 0:
                print(f"[분할최적화] {ticker} {iteration}/{total} 현재최고 {best_return:.2f}%")

        except Exception as e:
            print(f"[분할최적화] {ticker} {iteration}/{total} 오류: {str(e)[:80]}")

    if best_payload is None:
        raise RuntimeError(f"{ticker} 최적화 실패")

    # 저장용 summary 보정
    summary = dict(best_payload["summary"])
    summary.update(
        {
            "ticker": ticker,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "initial_capital": CAPITAL_PER_TICKER,
            "is_3x": True,
            "n_splits": best_payload["params"]["n_splits"],
            "base_profit_pct": best_payload["params"]["base_profit_pct"],
            "buy_threshold_1": best_payload["params"]["buy_threshold_1"],
            "buy_threshold_2": best_payload["params"]["buy_threshold_2"],
            "buy_threshold_3": best_payload["params"]["buy_threshold_3"],
            "sell_threshold_1": best_payload["params"]["sell_threshold_1"],
            "sell_threshold_2": best_payload["params"]["sell_threshold_2"],
            "sell_threshold_3": best_payload["params"]["sell_threshold_3"],
            "gap_up_pct": best_payload["params"]["gap_up_pct"],
        }
    )

    print(
        f"[분할최적화] {ticker} 완료 | 수익 {summary['total_return_pct']:.2f}% | "
        f"CAGR {summary['cagr_pct']:.2f}% | MDD {summary['mdd_pct']:.2f}%"
    )

    return SplitBest(
        ticker=ticker,
        params=best_payload["params"],
        summary=summary,
        records=best_payload["records"],
    )


def _download_close(ticker: str) -> pd.Series:
    end_plus = (pd.Timestamp(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START_DATE, end=end_plus, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"주가 데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].dropna().astype(float)
    s.index = pd.to_datetime(s.index)
    return s


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _perf_from_position(close: pd.Series, pos: pd.Series) -> Tuple[float, float, float, float]:
    ret = close.pct_change().fillna(0.0)
    strat_ret = ret * pos.shift(1).fillna(0.0)
    eq = (1 + strat_ret).cumprod()

    total_return_pct = (eq.iloc[-1] - 1) * 100
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr_pct = ((eq.iloc[-1]) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    mdd_pct = ((eq / eq.cummax()) - 1).min() * 100
    final_assets = float(eq.iloc[-1] * CAPITAL_PER_TICKER)
    return float(total_return_pct), float(cagr_pct), float(mdd_pct), final_assets


def run_non_split_best(ticker: str) -> AlgoPerf:
    print("=" * 90)
    print(f"[비분할비교] {ticker} 시작")
    print("=" * 90)

    close = _download_close(ticker)

    # 1) Buy & Hold
    pos_bh = pd.Series(1.0, index=close.index)

    # 2) SMA 200 추세추종
    sma200 = close.rolling(200).mean()
    pos_sma200 = (close > sma200).astype(float)

    # 3) 골든크로스(50/200)
    sma50 = close.rolling(50).mean()
    pos_gc = (sma50 > sma200).astype(float)

    # 4) MACD(12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    pos_macd = (macd > macd_sig).astype(float)

    # 5) RSI(2) mean reversion (국내/해외에서 매우 널리 알려진 단기전략)
    rsi2 = _rsi(close, 2)
    pos_rsi = pd.Series(0.0, index=close.index)
    holding = 0.0
    for i in range(len(close)):
        if pd.isna(rsi2.iloc[i]):
            pos_rsi.iloc[i] = holding
            continue
        if holding == 0.0 and rsi2.iloc[i] < 10:
            holding = 1.0
        elif holding == 1.0 and rsi2.iloc[i] > 70:
            holding = 0.0
        pos_rsi.iloc[i] = holding

    # 6) 돈치안(20/10) 브레이크아웃
    high20 = close.rolling(20).max().shift(1)
    low10 = close.rolling(10).min().shift(1)
    pos_dc = pd.Series(0.0, index=close.index)
    holding = 0.0
    for i in range(len(close)):
        c = close.iloc[i]
        if pd.isna(high20.iloc[i]) or pd.isna(low10.iloc[i]):
            pos_dc.iloc[i] = holding
            continue
        if holding == 0.0 and c > high20.iloc[i]:
            holding = 1.0
        elif holding == 1.0 and c < low10.iloc[i]:
            holding = 0.0
        pos_dc.iloc[i] = holding

    candidates = {
        "BuyHold": pos_bh,
        "SMA200": pos_sma200,
        "GoldenCross50_200": pos_gc,
        "MACD_12_26_9": pos_macd,
        "RSI2_MeanReversion": pos_rsi,
        "Donchian20_10": pos_dc,
    }

    best: AlgoPerf | None = None
    for name, pos in candidates.items():
        total, cagr, mdd, final_assets = _perf_from_position(close, pos)
        if best is None or total > best.total_return_pct:
            best = AlgoPerf(
                ticker=ticker,
                algo_name=name,
                total_return_pct=total,
                cagr_pct=cagr,
                mdd_pct=mdd,
                final_assets=final_assets,
            )

    if best is None:
        raise RuntimeError(f"{ticker} 비분할 알고리즘 계산 실패")

    print(
        f"[비분할비교] {ticker} 완료 | 최고 {best.algo_name} | "
        f"수익 {best.total_return_pct:.2f}% | CAGR {best.cagr_pct:.2f}% | MDD {best.mdd_pct:.2f}%"
    )
    return best


def write_backtest_sheet(ss, title: str, records: List[DayRecord], summary: dict):
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1200, len(records) + 100), cols=17)

    ws.clear()

    top = [
        [f"{summary.get('ticker')} 분할매매 최적 백테스트"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기간: {summary.get('start_date')} ~ {summary.get('end_date')}"],
        [f"초기자본: ${summary.get('initial_capital', 0):,.0f}"],
    ]
    ws.update(range_name="A1:Q4", values=top)

    headers = [
        "날짜", "종가", "52주전고점", "전고점낙폭(%)", "평단가", "평단대비수익률(%)",
        "Fear&Greed", "매매구분", "거래수량", "거래금액", "보유주식수",
        "현금잔고", "평가금액", "총자산", "수익률(%)", "사이클", "메모",
    ]
    ws.update(range_name="A6:Q6", values=[headers])

    rows = []
    for r in records:
        rows.append([
            r.date,
            r.close,
            r.high_52w,
            r.drawdown_pct,
            r.avg_cost,
            r.profit_pct,
            r.fear_greed,
            r.action,
            r.qty,
            r.trade_amount,
            r.shares,
            r.cash,
            r.portfolio_value,
            r.total_assets,
            r.return_pct,
            r.cycle,
            r.memo,
        ])

    if rows:
        ws.update(range_name=f"A7:Q{6 + len(rows)}", values=rows)


def write_summary_sheet(
    ss,
    split_best: Dict[str, SplitBest],
    non_split_best: Dict[str, AlgoPerf],
):
    title = "요청_통합결과"
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=120, cols=20)

    ws.clear()

    split_rows = [
        ["구분", "티커", "수익률(%)", "CAGR(%)", "MDD(%)", "거래수", "최종자산($)", "N", "base", "buy(1/2/3)", "sell(1/2/3)"],
    ]
    for tk in TICKERS:
        b = split_best[tk]
        p = b.params
        s = b.summary
        split_rows.append([
            "분할최적",
            tk,
            round(s["total_return_pct"], 2),
            round(s["cagr_pct"], 2),
            round(s["mdd_pct"], 2),
            int(s["total_trades"]),
            round(s["final_total_assets"], 2),
            p["n_splits"],
            p["base_profit_pct"],
            f"{p['buy_threshold_1']}/{p['buy_threshold_2']}/{p['buy_threshold_3']}",
            f"{p['sell_threshold_1']}/{p['sell_threshold_2']}/{p['sell_threshold_3']}",
        ])

    split_final = sum(split_best[tk].summary["final_total_assets"] for tk in TICKERS)
    split_total_return = (split_final / (CAPITAL_PER_TICKER * len(TICKERS)) - 1) * 100

    non_rows = [
        ["구분", "티커", "알고리즘", "수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)"],
    ]
    for tk in TICKERS:
        n = non_split_best[tk]
        non_rows.append([
            "비분할최고",
            tk,
            n.algo_name,
            round(n.total_return_pct, 2),
            round(n.cagr_pct, 2),
            round(n.mdd_pct, 2),
            round(n.final_assets, 2),
        ])

    non_final = sum(non_split_best[tk].final_assets for tk in TICKERS)
    non_total_return = (non_final / (CAPITAL_PER_TICKER * len(TICKERS)) - 1) * 100

    top = [
        ["TQQQ 10만 + SOXL 10만 독립 운용 결과"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"] ,
        [f"기간: {START_DATE} ~ {END_DATE}"],
        [""],
        ["[1] 분할매수/분할매도 최적화 결과"],
    ]
    ws.update(range_name="A1:K5", values=top)
    ws.update(range_name=f"A6:K{5 + len(split_rows)}", values=split_rows)

    ws.update(
        range_name=f"A{7 + len(split_rows)}:D{7 + len(split_rows)}",
        values=[["분할 합산결과", round(split_total_return, 2), round(split_final, 2), "(초기 200,000)" ]],
    )

    start_non = 10 + len(split_rows)
    ws.update(range_name=f"A{start_non}:G{start_non}", values=[["[2] 비분할 유명 알고리즘 중 최대수익"]])
    ws.update(range_name=f"A{start_non+1}:G{start_non + len(non_rows)}", values=non_rows)
    ws.update(
        range_name=f"A{start_non + len(non_rows) + 2}:D{start_non + len(non_rows) + 2}",
        values=[["비분할 합산결과", round(non_total_return, 2), round(non_final, 2), "(초기 200,000)"]],
    )


def save_to_google_sheets(split_best: Dict[str, SplitBest], non_split_best: Dict[str, AlgoPerf]):
    sheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=sheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(sheet_id)

    write_summary_sheet(ss, split_best, non_split_best)
    write_backtest_sheet(ss, "요청_TQQQ_분할백테스트", split_best["TQQQ"].records, split_best["TQQQ"].summary)
    write_backtest_sheet(ss, "요청_SOXL_분할백테스트", split_best["SOXL"].records, split_best["SOXL"].summary)

    print("\n[GoogleSheets] 저장 완료")
    print(f"URL: https://docs.google.com/spreadsheets/d/{sheet_id}")


def main():
    split_best: Dict[str, SplitBest] = {}
    non_split_best: Dict[str, AlgoPerf] = {}

    for tk in TICKERS:
        split_best[tk] = run_split_grid_search(tk)

    for tk in TICKERS:
        non_split_best[tk] = run_non_split_best(tk)

    save_to_google_sheets(split_best, non_split_best)

    print("\n" + "=" * 90)
    print("요약")
    print("=" * 90)
    for tk in TICKERS:
        s = split_best[tk].summary
        p = split_best[tk].params
        print(
            f"[분할최적] {tk} | 수익 {s['total_return_pct']:.2f}% | CAGR {s['cagr_pct']:.2f}% | MDD {s['mdd_pct']:.2f}% | "
            f"N={p['n_splits']} base={p['base_profit_pct']} buy=({p['buy_threshold_1']},{p['buy_threshold_2']},{p['buy_threshold_3']}) "
            f"sell=({p['sell_threshold_1']},{p['sell_threshold_2']},{p['sell_threshold_3']})"
        )

    for tk in TICKERS:
        n = non_split_best[tk]
        print(
            f"[비분할최고] {tk} | {n.algo_name} | 수익 {n.total_return_pct:.2f}% | CAGR {n.cagr_pct:.2f}% | MDD {n.mdd_pct:.2f}%"
        )


if __name__ == "__main__":
    main()
