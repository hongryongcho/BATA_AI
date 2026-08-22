"""
FnG RSI(2) 알고리즘 기간별 수익률 비교
  Period 1: 2011-01-01 ~ 2020-12-31  (F&G 도입 전 기간)
  Period 2: 2021-01-01 ~ 오늘        (실제 운영 기간)
대상: TQQQ, SOXL
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from create_qqq_crash_guard_backtest import (
    download_close,
    simulate_with_qqq_guard,
    calc_perf,
    yearly_returns,
    TICKER_CONFIG,
    CAPITAL,
)
from fear_greed_history import load_fng_history

PERIODS = {
    "2011~2020 (F&G 이전)": ("2011-01-01", "2020-12-31"),
    "2021~현재 (운영 기간)": ("2021-01-01", datetime.today().strftime("%Y-%m-%d")),
}

COOLDOWN_3 = 15
COOLDOWN_5 = 30


def bnh_stats(close: pd.Series) -> dict:
    start_px = float(close.iloc[0])
    end_px   = float(close.iloc[-1])
    dates    = close.index
    years    = max((dates[-1] - dates[0]).days / 365.25, 1 / 365.25)
    total    = (end_px / start_px - 1) * 100
    cagr     = ((end_px / start_px) ** (1 / years) - 1) * 100
    peak     = start_px
    mdd      = 0.0
    for px in close:
        if float(px) > peak:
            peak = float(px)
        dd = (float(px) / peak - 1) * 100
        if dd < mdd:
            mdd = dd
    return {"total_return_pct": round(total, 2), "cagr_pct": round(cagr, 2), "mdd_pct": round(mdd, 2)}


def print_period(ticker: str, period_name: str, r: dict):
    perf = r["perf"]
    bnh  = r["bnh"]
    yr   = r["yearly"]

    print(f"\n  ┌─ {ticker}  │  {period_name}  ({r['start']} ~ {r['end']}, {r['days']}일) ─────")

    algo_rows = [
        ("총 수익률",        f"{perf['total_return_pct']:>+9.2f}%"),
        ("CAGR",             f"{perf['cagr_pct']:>+9.2f}%"),
        ("MDD",              f"{perf['mdd_pct']:>+9.2f}%"),
        ("최종 자산",        f"${perf['final_assets']:>12,.0f}"),
        ("납부 양도세",      f"${perf['total_tax_paid']:>12,.0f}"),
        ("사이클 수",        f"{perf['cycles']:>13}회"),
        ("승률",             f"{perf['win_rate']:>9.1f}%"),
        ("평균 수익/사이클", f"{perf['avg_ret_pct']:>+9.2f}%"),
        ("평균 보유기간",    f"{perf['avg_hold_days']:>10.1f}일"),
        ("매수",             f"{perf['buy_count']:>13}회"),
        ("매도(일반)",       f"{perf['sell_count']:>13}회"),
        ("매도(QQQ강제)",    f"{perf['sell_qqq_count']:>13}회"),
        ("F&G 차단",         f"{perf['fng_blocked']:>13}회"),
    ]

    bnh_rows = [
        ("B&H 총 수익률",    f"{bnh['total_return_pct']:>+9.2f}%"),
        ("B&H CAGR",         f"{bnh['cagr_pct']:>+9.2f}%"),
        ("B&H MDD",          f"{bnh['mdd_pct']:>+9.2f}%"),
        ("알고vs.B&H CAGR",  f"{perf['cagr_pct']-bnh['cagr_pct']:>+9.2f}%p"),
    ]

    print(f"  │  알고리즘 성과")
    for label, val in algo_rows:
        print(f"  │    {label:<18} {val}")
    print(f"  │")
    print(f"  │  Buy & Hold 비교")
    for label, val in bnh_rows:
        print(f"  │    {label:<18} {val}")
    print(f"  │")
    print(f"  │  연도별 수익률")
    for yr_label in sorted(yr.keys()):
        pct = yr[yr_label]
        bar = ("▲" if pct >= 0 else "▼") + "█" * min(int(abs(pct) / 5), 20)
        print(f"  │    {yr_label}: {pct:>+8.1f}%  {bar}")
    print(f"  └{'─'*60}")


def main():
    print("=" * 75)
    print("FnG RSI(2) + QQQ Crash Guard  기간별 수익률 비교")
    print(f"알고리즘: buy<15 / F&G  fear≤25/greed≥90  QQQ-3%→{COOLDOWN_3}일  QQQ-5%→{COOLDOWN_5}일")
    print(f"초기자본: ${CAPITAL:,.0f}  |  TQQQ sell>75  /  SOXL sell>90")
    print("=" * 75)

    print("\n[F&G 데이터 로드 중...]")
    try:
        fng_full = load_fng_history()
        print(f"  F&G: {fng_full.index.min().date()} ~ {fng_full.index.max().date()}")
    except Exception as e:
        print(f"  F&G 로드 실패: {e}  → 전 기간 F&G=50 사용")
        fng_full = pd.Series(dtype=float)

    print("\n[QQQ 다운로드 중...]")
    qqq_full = download_close("QQQ")
    print(f"  QQQ: {qqq_full.index[0].date()} ~ {qqq_full.index[-1].date()} ({len(qqq_full)}일)")

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n[{ticker}] 다운로드 중...")
        close_full = download_close(ticker)
        print(f"  {ticker}: {close_full.index[0].date()} ~ {close_full.index[-1].date()} ({len(close_full)}일)")

        print(f"\n{'═'*75}")
        print(f"  {ticker}")
        print(f"{'═'*75}")

        for period_name, (p_start, p_end) in PERIODS.items():
            close = close_full[p_start:p_end]
            qqq   = qqq_full[p_start:p_end]
            if len(close) < 10:
                print(f"  [{period_name}] 데이터 부족 → 건너뜀")
                continue

            if not fng_full.empty:
                fng = fng_full.reindex(close.index, method="ffill").fillna(50).astype(int)
            else:
                fng = pd.Series(50, index=close.index)

            df, taxes = simulate_with_qqq_guard(
                close=close, fng=fng, qqq_close=qqq,
                period=cfg["period"],
                buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
                fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
                cooldown_3=COOLDOWN_3, cooldown_5=COOLDOWN_5,
            )
            perf = calc_perf(df, taxes)
            bnh  = bnh_stats(close)
            yr   = yearly_returns(df, taxes)

            r = {
                "perf": perf, "bnh": bnh, "yearly": yr,
                "start": str(close.index[0].date()),
                "end":   str(close.index[-1].date()),
                "days":  len(close),
            }
            print_period(ticker, period_name, r)

    print("\n" + "=" * 75)
    print("완료")


if __name__ == "__main__":
    main()
