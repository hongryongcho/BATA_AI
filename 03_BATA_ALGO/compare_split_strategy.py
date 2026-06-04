"""
분할매수/매도 전략 vs 현재 알고리즘 비교 백테스트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
현재 알고리즘: RSI(2)+F&G+QQQ가드+GC지연 (올인/올아웃)
분할 전략:     3단 분할매수 + 2단 분할매도 (동일 필터 적용)

TQQQ 분할매수: RSI<15(30%) / RSI<8(30%) / RSI<3(40%)
TQQQ 분할매도: RSI>75(50%) / RSI>85(50%)
SOXL 분할매수: RSI<15(30%) / RSI<8(30%) / RSI<3(40%)
SOXL 분할매도: RSI>85(50%) / RSI>95(50%)
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from create_qqq_golden_cross_backtest import (
    download_close, compute_qqq_gc,
    _build_rsi_arrays, _build_next_day_limits,
    START_DATE, END_DATE, CAPITAL, TAX_RATE, TAX_EXEMPT,
    QQQ_CRASH_PCT, QQQ_COOLDOWN, GC_DELAY_DAYS,
    GC_MA_FAST, GC_MA_SLOW,
)
from fear_greed_history import load_fng_history

# ── 분할 전략 파라미터 ────────────────────────────────────────────────

SPLIT_CONFIG = {
    "TQQQ": {
        "period": 2,
        # 매수 트랜치: (RSI 임계, F&G 최대, 자본 비율)
        "buy_tranches": [
            {"rsi": 15, "fng_max": 90, "ratio": 0.30},
            {"rsi":  8, "fng_max": 60, "ratio": 0.30},
            {"rsi":  3, "fng_max": 35, "ratio": 0.40},
        ],
        # 매도 트랜치: (RSI 임계, 보유 비율)
        "sell_tranches": [
            {"rsi": 75, "ratio": 0.50},
            {"rsi": 85, "ratio": 1.00},
        ],
        "fear_max":  25,
        "greed_min": 90,
    },
    "SOXL": {
        "period": 2,
        "buy_tranches": [
            {"rsi": 15, "fng_max": 90, "ratio": 0.30},
            {"rsi":  8, "fng_max": 55, "ratio": 0.30},
            {"rsi":  3, "fng_max": 30, "ratio": 0.40},
        ],
        "sell_tranches": [
            {"rsi": 85, "ratio": 0.50},
            {"rsi": 95, "ratio": 1.00},
        ],
        "fear_max":  25,
        "greed_min": 90,
    },
}


# ── 분할 전략 시뮬레이션 ──────────────────────────────────────────────

def simulate_split(
    close: pd.Series,
    fng: pd.Series,
    qqq_close: pd.Series,
    cfg: dict,
    qqq_gc: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict]:

    alpha  = 1.0 / cfg["period"]
    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    fng_al = fng.reindex(close.index, method="ffill").fillna(50).astype(int)

    # 모든 트랜치에 필요한 limit 배열 미리 계산
    rsi_levels = set()
    for t in cfg["buy_tranches"]:
        rsi_levels.add(t["rsi"])
    for t in cfg["sell_tranches"]:
        rsi_levels.add(t["rsi"])

    limit_arrays: dict[float, tuple] = {}
    for rsi_lvl in rsi_levels:
        bl, sl = _build_next_day_limits(closes, ma_up, ma_down, rsi_lvl, rsi_lvl, alpha)
        limit_arrays[rsi_lvl] = (bl, sl)

    # QQQ 데이터
    qqq_al  = qqq_close.reindex(close.index, method="ffill").ffill().bfill()
    qqq_v   = qqq_al.values.astype(float)
    qqq_chg = np.zeros(n)
    for i in range(1, n):
        if qqq_v[i - 1] > 0:
            qqq_chg[i] = (qqq_v[i] / qqq_v[i - 1] - 1.0) * 100.0

    # GC 배열
    if qqq_gc is not None:
        gc_arr = qqq_gc.reindex(close.index, method="ffill").fillna(False).values.astype(bool)
    else:
        gc_arr = np.zeros(n, dtype=bool)

    # ── 상태 변수 ────────────────────────────────────────────────────
    cash = CAPITAL
    holdings = 0.0
    avg_cost  = 0.0           # 평균매입단가 × 수량 (세금 계산용)

    # 트랜치별 상태
    n_buy  = len(cfg["buy_tranches"])
    n_sell = len(cfg["sell_tranches"])
    tranche_filled   = [False] * n_buy   # 매수 트랜치 사용 여부
    sell_done        = [False] * n_sell  # 매도 트랜치 완료 여부
    cycle_start_cash = CAPITAL           # 사이클 시작 시 총 자본

    annual_realized_pnl = 0.0
    annual_profit_ytd   = 0.0
    current_tax_year    = None
    total_tax_paid      = 0.0
    annual_taxes: dict  = {}
    pending_tax         = 0.0
    pending_tax_year    = None
    pending_tax_tb      = 0.0
    pending_realized    = 0.0
    cooldown_until: datetime | None = None

    gc_delay_until: datetime | None = None
    gc_delay_used = False
    gc_started_during_hold = False

    rows: list[dict] = []

    def _apply_tax():
        nonlocal cash, total_tax_paid, pending_tax, pending_tax_year
        nonlocal pending_tax_tb, annual_profit_ytd, pending_realized
        if pending_tax <= 0:
            return None
        tax = pending_tax
        cash           -= tax
        total_tax_paid += tax
        annual_taxes[pending_tax_year] = {
            "tax": tax, "total_before": pending_tax_tb,
            "deducted_on": dt.strftime("%Y-%m-%d"),
        }
        pending_tax = 0.0; pending_tax_year = None
        pending_tax_tb = 0.0; annual_profit_ytd = 0.0
        pending_realized = 0.0
        return tax

    def _is_any_bought():
        return any(tranche_filled)

    def _is_fully_sold():
        return not _is_any_bought() or all(sell_done)

    def _reset_cycle():
        nonlocal avg_cost, gc_delay_until, gc_delay_used, gc_started_during_hold
        nonlocal cycle_start_cash
        for k in range(n_buy):
            tranche_filled[k] = False
        for k in range(n_sell):
            sell_done[k] = False
        avg_cost = 0.0
        gc_delay_until = None
        gc_delay_used  = False
        gc_started_during_hold = False
        total_assets_now = cash + holdings * float(closes[i]) if i < n else cash
        cycle_start_cash = total_assets_now

    for i, (dt, price) in enumerate(close.items()):
        px      = float(price)
        fng_val = int(fng_al.iloc[i])
        q_chg   = float(qqq_chg[i])
        gc_on   = bool(gc_arr[i])

        action      = "HOLD"
        note        = ""
        trade_qty   = 0.0
        tax_today   = None

        # GC 지연 대기 표시
        if gc_delay_until is not None and dt < gc_delay_until and holdings > 0:
            rem = (gc_delay_until - dt).days
            note = f"GC지연대기({rem}일→{gc_delay_until.strftime('%m/%d')})"

        # 연간 양도세
        if current_tax_year is None:
            current_tax_year = dt.year
        elif dt.year != current_tax_year:
            taxable = max(0.0, annual_realized_pnl - TAX_EXEMPT)
            pending_tax_tb = rows[-1]["total_assets"] if rows else 0.0
            pending_realized = annual_realized_pnl
            pending_tax = round(taxable * TAX_RATE, 2) if taxable > 0 else 0.0
            pending_tax_year = current_tax_year
            if pending_tax == 0.0:
                annual_taxes[pending_tax_year] = {
                    "tax": 0.0, "total_before": pending_tax_tb, "deducted_on": None,
                }
                annual_profit_ytd = 0.0; pending_tax_year = None; pending_realized = 0.0
            annual_realized_pnl = 0.0
            current_tax_year = dt.year

        if i > 0:
            # GC 신규 발생 감지
            if holdings > 0 and gc_arr[i] and not gc_arr[i - 1]:
                gc_started_during_hold = True

            # [1] QQQ Crash Guard
            if q_chg <= QQQ_CRASH_PCT:
                new_until = dt + timedelta(days=QQQ_COOLDOWN)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                if holdings > 0:
                    realized = holdings * px - avg_cost
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    trade_qty = -holdings; cash += holdings * px; holdings = 0.0
                    avg_cost  = 0.0
                    tax_today = _apply_tax()
                    action = "SELL_QQQ"
                    note   = f"QQQ{q_chg:.1f}%≤-5%→{QQQ_COOLDOWN}일"
                    _reset_cycle()
                else:
                    note = f"QQQ{q_chg:.1f}%≤-5%(쿨다운연장)"

            # [2] GC 지연 만료 재검토
            if action == "HOLD" and gc_delay_until is not None and dt >= gc_delay_until and holdings > 0:
                sell_rsi = cfg["sell_tranches"][0]["rsi"]
                nsl_arr  = limit_arrays[sell_rsi][1]
                prev_sl  = nsl_arr[i - 1]
                if not np.isnan(prev_sl) and px >= float(prev_sl):
                    # 매도 1차 실행
                    sell_qty  = holdings * 0.50
                    realized  = sell_qty * px - avg_cost * 0.50
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    cash     += sell_qty * px; holdings -= sell_qty
                    avg_cost *= 0.50
                    trade_qty = -sell_qty
                    sell_done[0] = True
                    action = "SELL_P1"
                    note   = f"GC지연후매도(RSI≥{sell_rsi})"
                    tax_today = _apply_tax()
                else:
                    note = f"GC지연해제(RSI<{sell_rsi})"
                gc_delay_until = None

            # [3] 정상 매수/매도 (GC 지연 중이 아닐 때)
            if action == "HOLD" and gc_delay_until is None:
                in_cd = cooldown_until is not None and dt <= cooldown_until

                # ── 분할 매도 체크 ────────────────────────────────────
                if holdings > 0 and not in_cd:
                    for si, st in enumerate(cfg["sell_tranches"]):
                        if sell_done[si]:
                            continue
                        nsl_arr = limit_arrays[st["rsi"]][1]
                        prev_sl = nsl_arr[i - 1]
                        if np.isnan(prev_sl) or px < float(prev_sl):
                            continue
                        if fng_val <= cfg["fear_max"]:
                            note = f"SELL차단(F&G={fng_val}≤{cfg['fear_max']})"
                            break
                        # GC 지연 (1차 매도 시에만)
                        if si == 0 and gc_on and gc_started_during_hold and not gc_delay_used:
                            gc_delay_until = dt + timedelta(days=GC_DELAY_DAYS)
                            gc_delay_used  = True
                            note = f"SELL지연(GC+{GC_DELAY_DAYS}일→{gc_delay_until.strftime('%m/%d')})"
                            break
                        # 매도 실행
                        sell_ratio = st["ratio"]
                        sell_qty   = holdings * sell_ratio
                        cost_sold  = avg_cost * sell_ratio
                        realized   = sell_qty * px - cost_sold
                        annual_realized_pnl += realized; annual_profit_ytd += realized
                        cash     += sell_qty * px; holdings -= sell_qty
                        avg_cost -= cost_sold
                        trade_qty = -sell_qty
                        sell_done[si] = True
                        action = f"SELL_P{si+1}"
                        note   = f"SELL{si+1}차(RSI≥{st['rsi']})"
                        tax_today = _apply_tax()
                        # 완전 매도 시 사이클 리셋
                        if abs(holdings) < 1e-9:
                            holdings = 0.0; avg_cost = 0.0
                            _reset_cycle()
                        break

                # ── 분할 매수 체크 ────────────────────────────────────
                if action == "HOLD" and not in_cd:
                    for bi, bt in enumerate(cfg["buy_tranches"]):
                        if tranche_filled[bi]:
                            continue
                        nbl_arr = limit_arrays[bt["rsi"]][0]
                        prev_bl = nbl_arr[i - 1]
                        if np.isnan(prev_bl) or px > float(prev_bl):
                            continue
                        if fng_val >= cfg["greed_min"]:
                            note = f"BUY차단(F&G={fng_val}≥{cfg['greed_min']})"
                            break
                        if fng_val > bt["fng_max"] and bi > 0:
                            note = f"BUY{bi+1}차차단(F&G={fng_val}>{bt['fng_max']})"
                            continue
                        # 첫 매수 시 사이클 시작 현금 확정
                        if not _is_any_bought():
                            cycle_start_cash = cash + holdings * px
                            tax_today = _apply_tax()

                        alloc  = cycle_start_cash * bt["ratio"]
                        avail  = min(alloc, cash)
                        if avail < 1.0:
                            tranche_filled[bi] = True
                            continue
                        bought    = avail / px
                        avg_cost += avail          # 취득원가 누적
                        cash     -= avail
                        holdings += bought
                        trade_qty = bought
                        tranche_filled[bi] = True
                        action = f"BUY_T{bi+1}"
                        note   = f"BUY{bi+1}차(RSI<{bt['rsi']},F&G<{bt['fng_max']})"
                        break

        total_assets = cash + holdings * px
        cd_rem = max(0, (cooldown_until - dt).days) if cooldown_until and dt <= cooldown_until else 0

        rows.append({
            "date":         dt.strftime("%Y-%m-%d"),
            "close":        round(px, 4),
            "action":       action,
            "note":         note,
            "trade_qty":    round(trade_qty, 6),
            "holdings":     round(holdings, 6),
            "cash":         round(cash, 2),
            "avg_cost":     round(avg_cost, 2),
            "total_assets": round(total_assets, 2),
            "return_pct":   round((total_assets / CAPITAL - 1) * 100, 4),
            "annual_pnl":   round(annual_profit_ytd, 2),
            "tax_deducted": "" if tax_today is None else round(tax_today, 2),
        })

    # 마지막 연도 양도세
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if rows:
        tax_f = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
        if tax_f > 0:
            total_tax_paid += tax_f
            rows[-1]["total_assets"] = round(rows[-1]["total_assets"] - tax_f, 2)
            rows[-1]["return_pct"]   = round((rows[-1]["total_assets"] / CAPITAL - 1) * 100, 4)
            rows[-1]["annual_pnl"]   = 0.0
            ex = rows[-1].get("tax_deducted", "")
            rows[-1]["tax_deducted"] = round((float(ex) if ex != "" else 0.0) + tax_f, 2)
        annual_taxes[current_tax_year] = {
            "tax": tax_f, "total_before": rows[-1]["total_assets"] + tax_f,
            "deducted_on": rows[-1]["date"] if tax_f > 0 else None,
        }

    return pd.DataFrame(rows), annual_taxes


# ── 성과 계산 ─────────────────────────────────────────────────────────

def calc_perf(df: pd.DataFrame, taxes: dict) -> dict:
    ta    = df["total_assets"].astype(float)
    final = float(ta.iloc[-1])
    dates = pd.to_datetime(df["date"])
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1 / 365.25)
    cagr  = ((final / CAPITAL) ** (1 / years) - 1) * 100
    peak  = CAPITAL; mdd = 0.0
    for v in ta:
        if v > peak: peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd: mdd = dd
    # 사이클 수 (완전 매도 횟수 기준)
    sell_actions = df["action"].str.contains("SELL_P2|SELL_QQQ", na=False)
    cycles = int(sell_actions.sum())
    buy_actions  = df["action"].str.startswith("BUY_T1", na=False)
    total_tax = sum(v.get("tax", 0) for v in taxes.values())
    # 평균 보유일 (BUY_T1 → SELL_P2 사이)
    buys  = df[df["action"] == "BUY_T1"]["date"].tolist()
    sells = df[df["action"].isin(["SELL_P2", "SELL_QQQ"])]["date"].tolist()
    hold_days = []
    for b, s in zip(buys, sells):
        hold_days.append((pd.to_datetime(s) - pd.to_datetime(b)).days)
    avg_hold = sum(hold_days) / len(hold_days) if hold_days else 0.0
    return {
        "final": round(final, 0), "cagr": round(cagr, 2),
        "mdd": round(mdd, 2), "total_ret": round((final / CAPITAL - 1) * 100, 2),
        "cycles": cycles, "total_tax": round(total_tax, 0),
        "avg_hold": round(avg_hold, 1),
    }


# ── main ─────────────────────────────────────────────────────────────

def main():
    from create_qqq_golden_cross_backtest import simulate as sim_current, calc_perf as cp_current

    print("=" * 70)
    print(f"분할매수/매도 vs 현재 알고리즘 비교  {START_DATE} ~ {END_DATE}")
    print(f"초기자본: ${CAPITAL:,.0f}   세율: {TAX_RATE*100:.0f}%   비과세: ${TAX_EXEMPT:,.0f}")
    print("=" * 70)

    # 데이터 로드
    print("\n[데이터 로딩]")
    try:
        fng_base = load_fng_history()
    except Exception:
        fng_base = pd.Series(dtype=float)

    qqq_close = download_close("QQQ")
    qqq_gc    = compute_qqq_gc(qqq_close)
    print(f"  QQQ: {len(qqq_close)}일  GC: {qqq_gc.sum()}일({qqq_gc.mean()*100:.1f}%)")

    results = {}

    for ticker in ["TQQQ", "SOXL"]:
        print(f"\n{'='*70}")
        print(f"  {ticker}")
        print(f"{'='*70}")

        close = download_close(ticker)
        fng   = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        cfg_c = {"period": 2,
                 "buy_below":  15 if ticker == "TQQQ" else 15,
                 "sell_above": 75 if ticker == "TQQQ" else 90,
                 "fear_max": 25, "greed_min": 90}

        # 현재 알고리즘
        df_c, tax_c = sim_current(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg_c["period"], buy_below=cfg_c["buy_below"],
            sell_above=cfg_c["sell_above"],
            fear_max=cfg_c["fear_max"], greed_min=cfg_c["greed_min"],
            qqq_gc=qqq_gc, gc_delay_days=GC_DELAY_DAYS,
        )
        p_c = cp_current(df_c, tax_c)

        # 분할 전략
        cfg_s = SPLIT_CONFIG[ticker]
        df_s, tax_s = simulate_split(close, fng, qqq_close, cfg_s, qqq_gc)
        p_s = calc_perf(df_s, tax_s)

        results[ticker] = {"current": p_c, "split": p_s}

        # 출력
        print(f"\n  {'항목':<18} {'현재(올인/올아웃)':>18} {'분할매수/매도':>16} {'차이':>10}")
        print(f"  {'-'*64}")

        # 현재 알고리즘 키 매핑
        pc = {
            "cagr":      p_c.get("cagr_pct", 0),
            "mdd":       p_c.get("mdd_pct", 0),
            "total_ret": p_c.get("total_return_pct", 0),
            "final":     p_c.get("final_assets", 0),
            "cycles":    p_c.get("cycles", 0),
            "avg_hold":  p_c.get("avg_hold_days", 0),
            "total_tax": p_c.get("total_tax_paid", 0),
            "win_rate":  p_c.get("win_rate", 0),
        }

        def row(label, key, fmt="{:.2f}", unit=""):
            vc = pc.get(key, 0)
            vs = p_s.get(key, 0)
            diff = vs - vc
            sign = "+" if diff >= 0 else ""
            print(f"  {label:<18} {fmt.format(vc)+unit:>18} {fmt.format(vs)+unit:>16} {sign+fmt.format(diff)+unit:>10}")

        row("CAGR",       "cagr",       "{:.2f}", "%")
        row("MDD",        "mdd",        "{:.2f}", "%")
        row("총수익률",   "total_ret",  "{:.2f}", "%")
        row("최종자산",   "final",      "{:,.0f}", "$")
        row("완료사이클", "cycles",     "{:.0f}",  "회")
        row("평균보유일", "avg_hold",   "{:.1f}",  "일")
        row("총양도세",   "total_tax",  "{:,.0f}", "$")

        results[ticker]["current_mapped"] = pc

    # 최종 요약
    print(f"\n{'='*70}")
    print("  최종 요약")
    print(f"{'='*70}")
    for ticker, r in results.items():
        c = r["current_mapped"]; s = r["split"]
        cagr_diff = s["cagr"] - c["cagr"]
        mdd_diff  = s["mdd"]  - c["mdd"]
        sign_c = "+" if cagr_diff >= 0 else ""
        sign_m = "+" if mdd_diff  >= 0 else ""
        print(f"  {ticker}:  CAGR {sign_c}{cagr_diff:.2f}%p  /  MDD {sign_m}{mdd_diff:.2f}%p  /  "
              f"최종자산 ${s['final']:,.0f} (현재 ${c['final']:,.0f})")


if __name__ == "__main__":
    main()
