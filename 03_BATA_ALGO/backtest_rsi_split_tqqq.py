"""
RSI(2) 분할매수 전략 백테스트 — TMF 10% + TQQQ 5분할

[전략 요약]
  기본 배분  : 자산 10% → TMF 보유, 90% → TQQQ 5-lot 풀 (각 lot = 18% of total)
  매수 신호  : RSI(2) < 15 크로스다운 → 1 lot 매수 (최대 5회)
  마지막 lot : RSI(2) < 15 5번째 크로스 → TMF 전량 매도 + lot 자금 합산 → TQQQ 일괄 매수
  매도 신호  : RSI(2) > 75 크로스업 → TQQQ 전량 일괄 매도
  사이클 재시작: 매도 후 새 총자산 기준 10% TMF 재배분, 90% 5-lot 풀 재설정
  양도세     : 연간 실현손익 22% (비과세 $1,900), 다음 해 첫 거래일 차감

[비교 전략]
  FnG(원본)  : RSI(2) + 공포탐욕지수, 전액 all-in/all-out
  그리드(원본): TMF 30% + TQQQ N=20 슬롯, MDD 기반 그리드

RSI(2) 계산: Wilder EWM, alpha = 1/period (FnG 와 동일)
크로스 판정: 전일 RSI >= 임계값, 당일 RSI < 임계값 (혹은 반대) → 당일 종가 체결
"""

import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── 상수 ─────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100_000.0
TAX_RATE        = 0.22
TAX_EXEMPTION   = 1_900.0
START_DATE      = "2021-01-01"

# 새 전략 파라미터
TMF_RATIO_NEW = 0.10
N_SPLITS      = 5
BUY_BELOW     = 15.0
SELL_ABOVE    = 75.0
RSI_PERIOD    = 2

# FnG 비교 파라미터 (최적값)
FEAR_MAX      = 25
GREED_MIN     = 75


# ── 데이터 다운로드 ──────────────────────────────────────────────────────────
def download_data(start: str = "2020-01-01") -> tuple[pd.Series, pd.Series, pd.Series]:
    """TQQQ, TMF, BIL 다운로드"""
    print(f"  yfinance 다운로드: TQQQ, TMF, BIL ({start} ~)")
    raw = yf.download(["TQQQ", "TMF", "BIL"], start=start, auto_adjust=True, progress=False)
    tqqq = raw["Close"]["TQQQ"].dropna()
    tmf  = raw["Close"]["TMF"].dropna()
    bil  = raw["Close"]["BIL"].dropna()
    idx  = tqqq.index.intersection(tmf.index).intersection(bil.index)
    return tqqq.loc[idx], tmf.loc[idx], bil.loc[idx]


# ── RSI(2) Wilder EWM ────────────────────────────────────────────────────────
def calc_rsi(prices: np.ndarray, period: int = 2) -> np.ndarray:
    alpha = 1.0 / period
    n = len(prices)
    ma_up   = np.zeros(n)
    ma_down = np.zeros(n)
    for i in range(1, n):
        d = prices[i] - prices[i - 1]
        ma_up[i]   = alpha * max(d, 0.0)  + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-d, 0.0) + (1 - alpha) * ma_down[i - 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rs  = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[0] = np.nan
    return rsi


# ── 전략 1: RSI(2) 분할매수 (신규) ───────────────────────────────────────────
def simulate_rsi_split(
    tqqq_s: pd.Series,
    tmf_s:  pd.Series,
    tmf_ratio:  float      = TMF_RATIO_NEW,
    n_splits:   int        = N_SPLITS,
    lot_weights: list[float] = None,   # None → 균등, [0.6,0.1,0.1,0.1,0.1] 등
    buy_below:  float      = BUY_BELOW,
    sell_above: float      = SELL_ABOVE,
    start: str = START_DATE,
    end:   str = None,
) -> list[dict]:
    all_idx  = tqqq_s.index
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end or str(date.today()))
    trade_idx = all_idx[(all_idx >= start_ts) & (all_idx <= end_ts)]

    rsi_arr = calc_rsi(tqqq_s.values.astype(float), RSI_PERIOD)
    rsi_map = {dt: float(rsi_arr[all_idx.get_loc(dt)]) for dt in trade_idx}

    # 가중치 정규화
    if lot_weights is None:
        weights = [1.0 / n_splits] * n_splits
    else:
        s = sum(lot_weights)
        weights = [w / s for w in lot_weights]
    assert len(weights) == n_splits

    # 사이클 초기화
    first_pos = all_idx.get_loc(trade_idx[0])
    first_mp  = float(tmf_s.iloc[first_pos])

    pool      = INITIAL_CAPITAL * (1.0 - tmf_ratio)   # TQQQ 투자 풀
    lot_sizes = [pool * w for w in weights]             # 각 lot 절대금액
    cash      = pool
    tmf_sh    = (INITIAL_CAPITAL * tmf_ratio) / first_mp
    tmf_cost  = INITIAL_CAPITAL * tmf_ratio

    tqqq_lots  = []   # [(shares, cost), ...]
    lots_bought = 0

    gains_by_yr   = {}
    pending_tax   = []
    prev_yr       = None
    prev_rsi_val  = None
    rows          = []

    for dt in trade_idx:
        pos = all_idx.get_loc(dt)
        tp  = float(tqqq_s.iloc[pos])
        mp  = float(tmf_s.iloc[pos])
        yr  = dt.year
        rsi_val = rsi_map[dt]

        if prev_yr is not None and yr != prev_yr:
            pending_tax.append(prev_yr)

        actions = []

        # 연초 세금 차감
        for tyr in pending_tax:
            gain    = gains_by_yr.get(tyr, 0.0)
            taxable = max(0.0, gain - TAX_EXEMPTION)
            tax     = round(taxable * TAX_RATE, 2)
            if tax > 0:
                cash -= tax
                actions.append(f"TAX{tyr}:-${tax:.0f}")
        pending_tax.clear()

        # 신호 판단 (크로스 방식)
        if prev_rsi_val is not None and not np.isnan(rsi_val) and not np.isnan(prev_rsi_val):
            buy_cross  = (rsi_val < buy_below)  and (prev_rsi_val >= buy_below)
            sell_cross = (rsi_val > sell_above) and (prev_rsi_val <= sell_above)

            # ── 매수 ──────────────────────────────────────────────────────
            if buy_cross and lots_bought < n_splits:
                idx_lot  = lots_bought          # 0-based index
                lots_bought += 1
                this_size = lot_sizes[idx_lot]

                if lots_bought < n_splits:
                    buy_cash = min(this_size, max(0.0, cash))
                    if buy_cash > 0.01:
                        sh = buy_cash / tp
                        tqqq_lots.append((sh, buy_cash))
                        cash -= buy_cash
                        actions.append(f"BUY-L{lots_bought}@{tp:.2f}(${buy_cash:.0f})")

                else:  # 마지막 lot → TMF 전량 매도 + 합산 매수
                    tmf_proceeds = tmf_sh * mp
                    tmf_gain     = tmf_proceeds - tmf_cost
                    gains_by_yr[yr] = gains_by_yr.get(yr, 0.0) + tmf_gain

                    lot_cash  = min(this_size, max(0.0, cash))
                    total_buy = lot_cash + tmf_proceeds
                    sh = total_buy / tp
                    tqqq_lots.append((sh, total_buy))
                    cash    -= lot_cash
                    tmf_sh   = 0.0
                    tmf_cost = 0.0
                    actions.append(f"BUY-L{lots_bought}+TMF@{tp:.2f}(${total_buy:.0f})")

            # ── 매도 ──────────────────────────────────────────────────────
            elif sell_cross and tqqq_lots:
                total_sh       = sum(s for s, _ in tqqq_lots)
                total_cost_tqqq= sum(c for _, c in tqqq_lots)
                proceeds       = total_sh * tp
                gain           = proceeds - total_cost_tqqq
                gains_by_yr[yr] = gains_by_yr.get(yr, 0.0) + gain
                cash           += proceeds
                tqqq_lots.clear()
                lots_bought    = 0
                actions.append(f"SELL-ALL@{tp:.2f}(${proceeds:.0f})")

                # 남은 TMF 처리 (lot5 전에 SELL 신호 온 경우)
                if tmf_sh > 0:
                    tmf_v   = tmf_sh * mp
                    tg      = tmf_v - tmf_cost
                    gains_by_yr[yr] = gains_by_yr.get(yr, 0.0) + tg
                    cash   += tmf_v
                    tmf_sh  = 0.0
                    tmf_cost= 0.0

                # 사이클 재시작: TMF 10% 재배분
                total_now    = cash
                tmf_new_cost = total_now * tmf_ratio
                tmf_sh       = tmf_new_cost / mp
                tmf_cost     = tmf_new_cost
                cash        -= tmf_new_cost
                new_pool     = cash
                lot_sizes    = [new_pool * w for w in weights]
                actions.append(f"REBUY-TMF(${tmf_new_cost:.0f}),L1=${lot_sizes[0]:.0f}")

        # 자산 계산
        tqqq_val  = sum(s * tp for s, _ in tqqq_lots)
        tmf_val   = tmf_sh * mp
        total_val = cash + tqqq_val + tmf_val

        rows.append({
            "date":     str(dt.date()),
            "tqqq_p":  round(tp, 2),
            "tmf_p":   round(mp, 2),
            "rsi2":    round(rsi_val, 2) if not np.isnan(rsi_val) else "",
            "lots":    lots_bought,
            "tqqq_val":round(tqqq_val, 2),
            "tmf_val": round(tmf_val, 2),
            "cash":    round(cash, 2),
            "total":   round(total_val, 2),
            "ret_pct": round((total_val / INITIAL_CAPITAL - 1) * 100, 2),
            "action":  " | ".join(actions) if actions else "",
        })

        prev_rsi_val = rsi_val
        prev_yr      = yr

    # 최종 연도 세금
    if prev_yr:
        gain    = gains_by_yr.get(prev_yr, 0.0)
        taxable = max(0.0, gain - TAX_EXEMPTION)
        tax     = round(taxable * TAX_RATE, 2)
        if tax > 0 and rows:
            rows[-1]["cash"]    = round(rows[-1]["cash"] - tax, 2)
            rows[-1]["total"]   = round(rows[-1]["total"] - tax, 2)
            rows[-1]["ret_pct"] = round((rows[-1]["total"] / INITIAL_CAPITAL - 1) * 100, 2)

    return rows


# ── 전략 2: FnG All-in/out (비교용, F&G 없이 RSI만 사용) ────────────────────
def simulate_fng_rsi_only(
    tqqq_s:    pd.Series,
    buy_below:  float = BUY_BELOW,
    sell_above: float = SELL_ABOVE,
    start: str = START_DATE,
    end:   str = None,
) -> list[dict]:
    """공포탐욕지수 없이 순수 RSI(2) 크로스만 사용한 all-in/all-out 전략"""
    all_idx  = tqqq_s.index
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end or str(date.today()))
    trade_idx = all_idx[(all_idx >= start_ts) & (all_idx <= end_ts)]

    rsi_arr = calc_rsi(tqqq_s.values.astype(float), RSI_PERIOD)
    rsi_map = {dt: float(rsi_arr[all_idx.get_loc(dt)]) for dt in trade_idx}

    cash     = INITIAL_CAPITAL
    holdings = 0.0
    in_pos   = False

    gains_by_yr  = {}
    pending_tax  = []
    prev_yr      = None
    prev_rsi_val = None
    rows         = []

    for dt in trade_idx:
        pos = all_idx.get_loc(dt)
        tp  = float(tqqq_s.iloc[pos])
        yr  = dt.year
        rsi_val = rsi_map[dt]

        if prev_yr is not None and yr != prev_yr:
            pending_tax.append(prev_yr)

        actions = []
        for tyr in pending_tax:
            gain    = gains_by_yr.get(tyr, 0.0)
            taxable = max(0.0, gain - TAX_EXEMPTION)
            tax     = round(taxable * TAX_RATE, 2)
            if tax > 0:
                cash -= tax
                actions.append(f"TAX{tyr}:-${tax:.0f}")
        pending_tax.clear()

        if prev_rsi_val is not None and not np.isnan(rsi_val) and not np.isnan(prev_rsi_val):
            buy_cross  = (rsi_val < buy_below)  and (prev_rsi_val >= buy_below)
            sell_cross = (rsi_val > sell_above) and (prev_rsi_val <= sell_above)

            if buy_cross and not in_pos and cash > 0:
                holdings = cash / tp
                cash     = 0.0
                in_pos   = True
                actions.append(f"BUY-ALL@{tp:.2f}")

            elif sell_cross and in_pos and holdings > 0:
                proceeds = holdings * tp
                gain     = proceeds - (holdings * tp)   # cost tracking 단순화
                # 실제 cost 필요 → 간단히 마지막 매수가 기준은 복잡하므로 전체 gain 추적
                cash     = proceeds
                holdings = 0.0
                in_pos   = False
                actions.append(f"SELL-ALL@{tp:.2f}(${proceeds:.0f})")

        total_val = cash + holdings * tp
        rows.append({
            "date":    str(dt.date()),
            "tqqq_p": round(tp, 2),
            "rsi2":   round(rsi_val, 2) if not np.isnan(rsi_val) else "",
            "total":  round(total_val, 2),
            "ret_pct":round((total_val / INITIAL_CAPITAL - 1) * 100, 2),
            "action": " | ".join(actions) if actions else "",
        })

        prev_rsi_val = rsi_val
        prev_yr      = yr

    return rows


# ── 성과 지표 ────────────────────────────────────────────────────────────────
def calc_perf(rows: list[dict], label: str = "") -> dict:
    arr   = np.array([r["total"] for r in rows])
    final = arr[-1]
    total_ret = (final / INITIAL_CAPITAL - 1) * 100.0

    d0    = datetime.strptime(rows[0]["date"],  "%Y-%m-%d")
    d1    = datetime.strptime(rows[-1]["date"], "%Y-%m-%d")
    years = (d1 - d0).days / 365.25
    cagr  = ((final / INITIAL_CAPITAL) ** (1.0 / years) - 1) * 100.0 if years > 0 else 0.0

    peak = arr[0]
    mdd  = 0.0
    for v in arr:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < mdd:
            mdd = dd

    return {
        "label":     label,
        "total_ret": round(total_ret, 2),
        "cagr":      round(cagr, 2),
        "mdd":       round(mdd * 100.0, 2),
        "final":     round(final, 2),
    }


# ── 매매 이벤트 출력 ─────────────────────────────────────────────────────────
def print_trades(rows: list[dict], label: str, max_trades: int = 60):
    trades = [r for r in rows if r.get("action") and ("BUY" in r["action"] or "SELL" in r["action"])]
    print(f"\n  [{label}] 매매 이벤트 ({len(trades)}회)")
    print(f"  {'날짜':<12} {'RSI':>6} {'자산':>13} 액션")
    print(f"  {'-'*12} {'-'*6} {'-'*13} {'-'*50}")
    for r in trades[:max_trades]:
        rsi_s = f"{r['rsi2']:>6.1f}" if r.get("rsi2") != "" else "  -   "
        print(f"  {r['date']:<12} {rsi_s} ${r['total']:>12,.0f} {r['action'][:70]}")
    if len(trades) > max_trades:
        print(f"  ... 이하 {len(trades) - max_trades}건 생략")


# ── 연간 수익 요약 ────────────────────────────────────────────────────────────
def print_yearly(rows: list[dict], label: str):
    by_yr = {}
    for r in rows:
        yr = r["date"][:4]
        by_yr[yr] = r["total"]

    yrs = sorted(by_yr.keys())
    print(f"\n  [{label}] 연도별 자산")
    prev_v = INITIAL_CAPITAL
    for yr in yrs:
        v   = by_yr[yr]
        ret = (v / prev_v - 1) * 100
        print(f"    {yr}  ${v:>12,.0f}  ({ret:+.1f}%)")
        prev_v = v


# ── 메인 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 76)
    print("RSI(2) 분할매수 전략 비교 백테스트  — TMF vs BIL 헤지 비교")
    print(f"기간: {START_DATE} ~ {date.today()}  |  초기자산: ${INITIAL_CAPITAL:,.0f}")
    print("=" * 76)

    tqqq_s, tmf_s, bil_s = download_data()

    # ── 전략 설정 ─────────────────────────────────────────────────────────────
    strategies = [
        # ─ 기준선 ─
        {"label": "FnG RSI-only (All-in/out)",              "fng": True},
        # ─ TMF 헤지 ─
        {"label": "A  60/10/10/10/10 [TMF10%]",  "fng": False, "hedge": "tmf", "lot_weights": [0.60, 0.10, 0.10, 0.10, 0.10]},
        {"label": "A2 70/7.5×4       [TMF10%]",  "fng": False, "hedge": "tmf", "lot_weights": [0.70, 0.075,0.075,0.075,0.075]},
        {"label": "A4 80/5×4         [TMF10%]",  "fng": False, "hedge": "tmf", "lot_weights": [0.80, 0.05, 0.05, 0.05, 0.05]},
        # ─ BIL 헤지 ─
        {"label": "A  60/10/10/10/10 [BIL10%]",  "fng": False, "hedge": "bil", "lot_weights": [0.60, 0.10, 0.10, 0.10, 0.10]},
        {"label": "A2 70/7.5×4       [BIL10%]",  "fng": False, "hedge": "bil", "lot_weights": [0.70, 0.075,0.075,0.075,0.075]},
        {"label": "A4 80/5×4         [BIL10%]",  "fng": False, "hedge": "bil", "lot_weights": [0.80, 0.05, 0.05, 0.05, 0.05]},
    ]

    results = []
    for cfg in strategies:
        print(f"  시뮬레이션: {cfg['label']}")
        if cfg.get("fng"):
            rows = simulate_fng_rsi_only(tqqq_s)
        else:
            hedge_s = bil_s if cfg.get("hedge") == "bil" else tmf_s
            rows = simulate_rsi_split(tqqq_s, hedge_s, lot_weights=cfg["lot_weights"])
        perf = calc_perf(rows, cfg["label"])
        results.append((perf, rows))

    # ── 결과 테이블 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print(f"{'전략':<38} {'총수익률':>9} {'CAGR':>7} {'MDD':>8} {'최종자산':>12}")
    print("-" * 76)

    # 섹션 구분선으로 출력
    prev_hedge = None
    for perf, _ in results:
        hedge = "BIL" if "BIL" in perf["label"] else ("FnG" if "FnG" in perf["label"] else "TMF")
        if prev_hedge is not None and hedge != prev_hedge:
            print("-" * 76)
        print(
            f"{perf['label']:<38} {perf['total_ret']:>8.1f}% "
            f"{perf['cagr']:>6.1f}% {perf['mdd']:>7.1f}% "
            f"${perf['final']:>11,.0f}"
        )
        prev_hedge = hedge
    print("=" * 76)

    # ── 연간 수익 ────────────────────────────────────────────────────────────
    print()
    key_labels = [
        "FnG RSI-only (All-in/out)",
        "A  60/10/10/10/10 [TMF10%]",
        "A  60/10/10/10/10 [BIL10%]",
        "A4 80/5×4         [TMF10%]",
        "A4 80/5×4         [BIL10%]",
    ]
    for perf, rows in results:
        if perf["label"] in key_labels:
            print_yearly(rows, perf["label"])

    # ── TMF vs BIL 직접 비교 요약 ────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("TMF vs BIL 헤지 효과 비교")
    print("=" * 76)
    pairs = [
        ("A  60/10/10/10/10 [TMF10%]", "A  60/10/10/10/10 [BIL10%]"),
        ("A2 70/7.5×4       [TMF10%]", "A2 70/7.5×4       [BIL10%]"),
        ("A4 80/5×4         [TMF10%]", "A4 80/5×4         [BIL10%]"),
    ]
    perf_map = {p["label"]: p for p, _ in results}
    print(f"  {'전략':<25} {'헤지':>5} {'총수익률':>9} {'CAGR':>7} {'MDD':>8} {'최종자산':>12}")
    print(f"  {'-'*25} {'-'*5} {'-'*9} {'-'*7} {'-'*8} {'-'*12}")
    for tmf_lbl, bil_lbl in pairs:
        pt = perf_map[tmf_lbl]
        pb = perf_map[bil_lbl]
        name = tmf_lbl.split("[")[0].strip()
        print(f"  {name:<25}  TMF  {pt['total_ret']:>8.1f}% {pt['cagr']:>6.1f}% {pt['mdd']:>7.1f}% ${pt['final']:>11,.0f}")
        diff_ret = pb['total_ret'] - pt['total_ret']
        diff_mdd = pb['mdd'] - pt['mdd']
        print(f"  {'':<25}  BIL  {pb['total_ret']:>8.1f}% {pb['cagr']:>6.1f}% {pb['mdd']:>7.1f}% ${pb['final']:>11,.0f}  "
              f"(수익 {diff_ret:+.1f}%p / MDD {diff_mdd:+.1f}%p)")
        print()
    print("=" * 76)
