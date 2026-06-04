"""
종합 전략 탐색기 — TQQQ / SOXL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
테스트 전략 유형:
  A. 현재 알고리즘 (기준선)
  B. 수익목표 매도: RSI 진입 + X% 수익 시 매도
  C. 하이브리드: RSI 진입 + (수익목표 OR RSI 매도) 먼저 발생 시
  D. GC 적응형: 강세장/약세장별 다른 매도 기준
  E. 최대보유일: N일 경과 시 강제 매도
  F. MA 필터: MA200 위에서만 매수
  G. 불타기: 초기 진입 후 추가 상승 시 추가 매수
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from create_qqq_golden_cross_backtest import (
    download_close, compute_qqq_gc,
    _build_rsi_arrays, _build_next_day_limits,
    START_DATE, END_DATE, CAPITAL, TAX_RATE, TAX_EXEMPT,
    QQQ_CRASH_PCT, QQQ_COOLDOWN,
)
from fear_greed_history import load_fng_history


# ── 범용 단일 백테스트 엔진 ───────────────────────────────────────────

def simulate_strategy(
    close: pd.Series,
    fng: pd.Series,
    qqq_close: pd.Series,
    qqq_gc: pd.Series,
    # 매수 조건
    buy_rsi: float = 15,
    fng_greed_min: int = 90,
    ma_filter: int | None = None,          # MA-N 위에서만 매수 (None=없음)
    # 매도 조건
    sell_rsi: float | None = 75,           # RSI 매도 임계 (None=미사용)
    profit_target: float | None = None,    # X% 수익목표 (None=미사용)
    trailing_stop: float | None = None,    # X% 트레일링스탑 (None=미사용)
    max_hold_days: int | None = None,      # N일 강제매도 (None=미사용)
    # GC 적응형
    gc_bull_sell: float | None = None,     # GC=True일 때 매도 RSI
    gc_bear_sell: float | None = None,     # GC=False일 때 매도 RSI
    # 불타기 (추가 매수)
    pyramid_rsi_add: float | None = None,  # RSI가 이 값 이상 오른 후 추가진입 없음 (미구현)
    # F&G 매도 필터
    fng_fear_max: int = 25,
) -> dict:

    alpha  = 1.0 / 2  # RSI(2) 고정
    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)

    # 매수/매도 limit 배열
    nbl, _   = _build_next_day_limits(closes, ma_up, ma_down, buy_rsi, buy_rsi, alpha)
    if sell_rsi is not None:
        _, nsl = _build_next_day_limits(closes, ma_up, ma_down, sell_rsi, sell_rsi, alpha)
    else:
        nsl = np.full(n, np.nan)

    # GC 적응형 limit
    nsl_bull = nsl_bear = nsl
    if gc_bull_sell is not None:
        _, nsl_bull = _build_next_day_limits(closes, ma_up, ma_down, gc_bull_sell, gc_bull_sell, alpha)
    if gc_bear_sell is not None:
        _, nsl_bear = _build_next_day_limits(closes, ma_up, ma_down, gc_bear_sell, gc_bear_sell, alpha)

    # MA 배열
    if ma_filter is not None:
        ma_arr = pd.Series(closes).rolling(ma_filter).mean().values
    else:
        ma_arr = None

    fng_al  = fng.reindex(close.index, method="ffill").fillna(50).astype(int)
    qqq_al  = qqq_close.reindex(close.index, method="ffill").ffill().bfill()
    qqq_v   = qqq_al.values.astype(float)
    qqq_chg = np.zeros(n)
    for i in range(1, n):
        if qqq_v[i - 1] > 0:
            qqq_chg[i] = (qqq_v[i] / qqq_v[i - 1] - 1.0) * 100.0
    gc_arr = qqq_gc.reindex(close.index, method="ffill").fillna(False).values.astype(bool)

    # 상태
    cash = CAPITAL; holdings = 0.0; cash_at_buy = 0.0
    peak_price = 0.0; buy_date_i = -1
    annual_realized_pnl = 0.0; annual_profit_ytd = 0.0
    current_tax_year = None; total_tax_paid = 0.0
    annual_taxes: dict = {}
    pending_tax = 0.0; pending_tax_year = None
    pending_tax_tb = 0.0; pending_real = 0.0
    cooldown_until: datetime | None = None
    total_assets_series = []
    buy_count = 0; sell_count = 0; sell_qqq_count = 0
    cycle_returns: list[float] = []
    hold_days_list: list[int] = []

    def _apply_tax():
        nonlocal cash, total_tax_paid, pending_tax, pending_tax_year
        nonlocal pending_tax_tb, annual_profit_ytd, pending_real
        if pending_tax <= 0: return None
        tax = pending_tax
        cash -= tax; total_tax_paid += tax
        annual_taxes[pending_tax_year] = {"tax": tax, "total_before": pending_tax_tb}
        pending_tax = 0.0; pending_tax_year = None
        pending_tax_tb = 0.0; annual_profit_ytd = 0.0; pending_real = 0.0
        return tax

    dates = list(close.index)

    for i, (dt, price) in enumerate(close.items()):
        px = float(price)

        if current_tax_year is None:
            current_tax_year = dt.year
        elif dt.year != current_tax_year:
            taxable = max(0.0, annual_realized_pnl - TAX_EXEMPT)
            pending_tax_tb = total_assets_series[-1] if total_assets_series else 0.0
            pending_real   = annual_realized_pnl
            pending_tax    = round(taxable * TAX_RATE, 2) if taxable > 0 else 0.0
            pending_tax_year = current_tax_year
            if pending_tax == 0.0:
                annual_taxes[pending_tax_year] = {"tax": 0.0, "total_before": pending_tax_tb}
                annual_profit_ytd = 0.0; pending_tax_year = None
            annual_realized_pnl = 0.0; current_tax_year = dt.year

        action = "HOLD"

        if i > 0:
            q_chg  = float(qqq_chg[i])
            fng_v  = int(fng_al.iloc[i])
            gc_on  = bool(gc_arr[i])
            in_cd  = cooldown_until is not None and dt <= cooldown_until

            # [1] QQQ Crash Guard
            if q_chg <= QQQ_CRASH_PCT:
                new_u = dt + timedelta(days=QQQ_COOLDOWN)
                if cooldown_until is None or new_u > cooldown_until:
                    cooldown_until = new_u
                if holdings > 0:
                    realized = holdings * px - cash_at_buy
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    ret_pct = (holdings * px / cash_at_buy - 1) * 100
                    hd = (dt - dates[buy_date_i]).days if buy_date_i >= 0 else 0
                    cycle_returns.append(ret_pct); hold_days_list.append(hd)
                    cash += holdings * px; holdings = 0.0; cash_at_buy = 0.0
                    peak_price = 0.0; buy_date_i = -1
                    _apply_tax(); action = "SELL_QQQ"; sell_qqq_count += 1

            # [2] 보유 중 매도 조건 체크
            if action == "HOLD" and holdings > 0:
                should_sell = False

                # GC 적응형 매도
                if gc_bull_sell is not None or gc_bear_sell is not None:
                    sl_arr  = nsl_bull if gc_on else nsl_bear
                    prev_sl = sl_arr[i - 1] if i > 0 else np.nan
                    if not np.isnan(prev_sl) and px >= float(prev_sl) and fng_v > fng_fear_max:
                        should_sell = True
                # 기본 RSI 매도
                elif sell_rsi is not None:
                    prev_sl = nsl[i - 1]
                    if not np.isnan(prev_sl) and px >= float(prev_sl) and fng_v > fng_fear_max:
                        should_sell = True

                # 수익목표 매도
                if profit_target is not None and cash_at_buy > 0:
                    current_ret = holdings * px / cash_at_buy - 1
                    if current_ret >= profit_target / 100.0:
                        should_sell = True

                # 트레일링 스탑
                if trailing_stop is not None and holdings > 0:
                    if px > peak_price:
                        peak_price = px
                    if peak_price > 0 and px <= peak_price * (1 - trailing_stop / 100.0):
                        should_sell = True

                # 최대보유일 강제 매도
                if max_hold_days is not None and buy_date_i >= 0:
                    held = (dt - dates[buy_date_i]).days
                    if held >= max_hold_days:
                        should_sell = True

                if should_sell:
                    realized = holdings * px - cash_at_buy
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    ret_pct = (holdings * px / cash_at_buy - 1) * 100
                    hd = (dt - dates[buy_date_i]).days if buy_date_i >= 0 else 0
                    cycle_returns.append(ret_pct); hold_days_list.append(hd)
                    cash += holdings * px; holdings = 0.0; cash_at_buy = 0.0
                    peak_price = 0.0; buy_date_i = -1
                    _apply_tax(); action = "SELL"; sell_count += 1

            # [3] 매수 조건 체크
            if action == "HOLD" and holdings == 0.0 and not in_cd:
                prev_bl = nbl[i - 1]
                ma_ok = True
                if ma_arr is not None and not np.isnan(ma_arr[i]):
                    ma_ok = px >= ma_arr[i]  # MA 위에서만 매수
                if (not np.isnan(prev_bl) and px <= float(prev_bl)
                        and int(fng_al.iloc[i]) < fng_greed_min and ma_ok):
                    _apply_tax()
                    cash_at_buy = cash
                    bought = cash / px
                    holdings = bought; cash = 0.0
                    peak_price = px; buy_date_i = i
                    action = "BUY"; buy_count += 1

        total_assets = cash + holdings * px
        total_assets_series.append(total_assets)

    # 마지막 세금
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if total_assets_series:
        tax_f = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
        if tax_f > 0:
            total_assets_series[-1] = round(total_assets_series[-1] - tax_f, 2)
            total_tax_paid += tax_f

    ta = np.array(total_assets_series, dtype=float)
    final = float(ta[-1])
    dates_pd = pd.to_datetime(close.index)
    years = max((dates_pd[-1] - dates_pd[0]).days / 365.25, 1 / 365.25)
    cagr  = ((final / CAPITAL) ** (1 / years) - 1) * 100
    peak  = CAPITAL; mdd = 0.0
    for v in ta:
        if v > peak: peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd: mdd = dd
    win_rate  = len([r for r in cycle_returns if r > 0]) / len(cycle_returns) * 100 if cycle_returns else 0.0
    avg_ret   = sum(cycle_returns) / len(cycle_returns) if cycle_returns else 0.0
    avg_hold  = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0.0

    return {
        "final": round(final, 0),
        "cagr": round(cagr, 2),
        "mdd": round(mdd, 2),
        "total_ret": round((final / CAPITAL - 1) * 100, 2),
        "cycles": buy_count,
        "win_rate": round(win_rate, 1),
        "avg_ret": round(avg_ret, 2),
        "avg_hold": round(avg_hold, 1),
        "total_tax": round(total_tax_paid, 0),
    }


# ── main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 78)
    print(f"종합 전략 탐색기  {START_DATE} ~ {END_DATE}  초기자본 ${CAPITAL:,.0f}")
    print("=" * 78)

    try:
        fng_base = load_fng_history()
    except Exception:
        fng_base = pd.Series(dtype=float)

    print("\n[데이터 로딩 중...]")
    qqq_close = download_close("QQQ")
    qqq_gc    = compute_qqq_gc(qqq_close)

    for TICKER in ["TQQQ", "SOXL"]:
        close = download_close(TICKER)
        fng   = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        BASE_SELL = 75 if TICKER == "TQQQ" else 90

        print(f"\n{'='*78}")
        print(f"  {TICKER}   (기준 매도 RSI: {BASE_SELL})")
        print(f"{'='*78}")

        results: list[dict] = []

        def run(name: str, **kw) -> dict:
            p = simulate_strategy(close, fng, qqq_close, qqq_gc, **kw)
            p["name"] = name
            return p

        # ── A. 현재 알고리즘 (기준선) ───────────────────────────
        results.append(run(
            f"[A] 현재 (RSI<15 → RSI>{BASE_SELL})",
            buy_rsi=15, sell_rsi=BASE_SELL,
        ))

        # ── B. 수익목표 매도 (다양한 % 탐색) ─────────────────────
        for pct in [3, 5, 7, 10, 12, 15, 20]:
            results.append(run(
                f"[B] RSI<15 진입 + {pct}% 수익목표",
                buy_rsi=15, sell_rsi=None, profit_target=pct,
            ))

        # ── C. 하이브리드: 수익목표 OR RSI (먼저 오는 것) ────────
        for pct in [5, 7, 10, 15]:
            results.append(run(
                f"[C] RSI<15 → {pct}%목표 OR RSI>{BASE_SELL}",
                buy_rsi=15, sell_rsi=BASE_SELL, profit_target=pct,
            ))

        # ── D. GC 적응형 (강세장 더 길게, 약세장 빠르게) ─────────
        gc_combos = [
            (min(BASE_SELL + 10, 97), BASE_SELL - 10),
            (min(BASE_SELL + 15, 97), BASE_SELL - 10),
            (min(BASE_SELL + 10, 97), BASE_SELL - 15),
            (min(90, 97), 60),
            (min(85, 97), 65),
        ]
        for bull_s, bear_s in gc_combos:
            results.append(run(
                f"[D] GC적응: 강세RSI>{bull_s} / 약세RSI>{bear_s}",
                buy_rsi=15, sell_rsi=None,
                gc_bull_sell=bull_s, gc_bear_sell=bear_s,
            ))

        # ── E. 최대보유일 강제매도 ────────────────────────────────
        for days in [10, 15, 20, 30]:
            results.append(run(
                f"[E] RSI<15 진입 + 최대{days}일 보유",
                buy_rsi=15, sell_rsi=BASE_SELL, max_hold_days=days,
            ))

        # ── F. MA200 필터 + RSI 매도 ──────────────────────────────
        results.append(run(
            f"[F] MA200위+RSI<15 → RSI>{BASE_SELL}",
            buy_rsi=15, sell_rsi=BASE_SELL, ma_filter=200,
        ))
        results.append(run(
            f"[F] MA200위+RSI<15 → 10%목표",
            buy_rsi=15, sell_rsi=None, profit_target=10, ma_filter=200,
        ))

        # ── G. 더 낮은 RSI 진입 (더 극단 과매도만) ───────────────
        for buy_r in [10, 8, 5]:
            results.append(run(
                f"[G] RSI<{buy_r} 진입 → RSI>{BASE_SELL}",
                buy_rsi=buy_r, sell_rsi=BASE_SELL,
            ))
            results.append(run(
                f"[G] RSI<{buy_r} 진입 → 10%목표",
                buy_rsi=buy_r, sell_rsi=None, profit_target=10,
            ))

        # ── H. 트레일링 스탑 ─────────────────────────────────────
        for ts in [5, 7, 10]:
            results.append(run(
                f"[H] RSI<15 → 트레일링{ts}%",
                buy_rsi=15, sell_rsi=None, trailing_stop=ts,
            ))

        # ── I. GC 적응형 + 수익목표 혼합 ─────────────────────────
        bull_sell_i = min(BASE_SELL + 10, 97)
        results.append(run(
            f"[I] GC적응+수익목표: 강세RSI>{bull_sell_i} / 약세10%",
            buy_rsi=15, sell_rsi=None,
            gc_bull_sell=bull_sell_i, gc_bear_sell=None, profit_target=10,
        ))

        # ── 정렬 및 출력 ──────────────────────────────────────────
        df_r = pd.DataFrame(results).sort_values("cagr", ascending=False)

        print(f"\n  {'전략명':<42} {'CAGR':>7} {'MDD':>7} {'사이클':>6} "
              f"{'승률':>6} {'평균수익':>7} {'평균보유':>7} {'최종자산':>14}")
        print(f"  {'-'*100}")

        base_cagr = results[0]["cagr"]  # 현재 알고리즘 CAGR

        for _, r in df_r.iterrows():
            mark = " ◀최고" if r["cagr"] == df_r["cagr"].max() else ""
            is_base = "[A]" in r["name"]
            prefix = "▶" if is_base else " "
            print(f"  {prefix} {r['name']:<41} {r['cagr']:>6.1f}% "
                  f"{r['mdd']:>6.1f}% {r['cycles']:>6.0f} "
                  f"{r['win_rate']:>5.0f}% {r['avg_ret']:>6.2f}% "
                  f"{r['avg_hold']:>6.1f}일 "
                  f"${r['final']:>13,.0f}{mark}")

        # TOP 5 요약
        print(f"\n  ── TOP 5 전략 ({TICKER}) ─────────────────────────────────────")
        for rank, (_, r) in enumerate(df_r.head(5).iterrows(), 1):
            diff = r["cagr"] - base_cagr
            sign = "+" if diff >= 0 else ""
            print(f"  {rank}위  {r['name']}")
            print(f"       CAGR {r['cagr']:.1f}% ({sign}{diff:.1f}%p) | "
                  f"MDD {r['mdd']:.1f}% | 사이클 {r['cycles']:.0f}회 | "
                  f"최종 ${r['final']:,.0f}")


if __name__ == "__main__":
    main()
