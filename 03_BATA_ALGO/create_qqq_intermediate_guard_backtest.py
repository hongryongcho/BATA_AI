"""
QQQ Crash Guard 중간 낙폭 대응 비교 백테스트 (2011-01-01 ~ 오늘)
─────────────────────────────────────────────────────────────────
이전 결과 : QQQ -5%→10일 휴식이 최적 (TQQQ CAGR +6.7%p / SOXL +13.2%p 개선)
이번 탐색 : -3%~-5% 중간 구간에 대응하는 다양한 가드 방식 비교

시나리오 종류:
  단일 임계치  : -4.0%, -4.5% 각각에 5일/10일 적용
  계단식(step) : [-4%→5일, -5%→10일] / [-4.5%→7일, -5%→10일] 등
  선형(linear) : -4%부터 -5%까지 5~10일로 선형 비례
                 -3%부터 -5%까지 3~10일로 선형 비례
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# 공통 유틸리티 (이전 파일에서 재사용)
from create_qqq_crash_guard_backtest import (
    download_close, _build_rsi_arrays, _build_next_day_limits,
    calc_perf, yearly_returns,
    CAPITAL, TAX_RATE, TAX_EXEMPT, START_DATE, END_DATE, TICKER_CONFIG,
)

# ── 가드 설정 ─────────────────────────────────────────────────────────────
#
# mode = "none"   : 가드 없음
# mode = "step"   : steps = [(임계%, 휴식일), ...] 엄격한 순으로 먼저 확인
# mode = "linear" : start_pct→start_days  ..  end_pct→end_days 선형, 이후 cap_days
#
SCENARIOS = [
    # ── 비교 기준선 ───────────────────────────────────────────────────
    {
        "name":  "① 기준선 (QQQ가드없음)",
        "guard": {"mode": "none"},
    },
    {
        "name":  "② 전회최적 (-5%→10일)",
        "guard": {"mode": "step", "steps": [(-5.0, 10)]},
    },

    # ── 단일 임계치: -4.0% ───────────────────────────────────────────
    {
        "name":  "③ -4.0%→5일",
        "guard": {"mode": "step", "steps": [(-4.0, 5)]},
    },
    {
        "name":  "④ -4.0%→10일",
        "guard": {"mode": "step", "steps": [(-4.0, 10)]},
    },
    {
        "name":  "⑤ -4.0%→15일",
        "guard": {"mode": "step", "steps": [(-4.0, 15)]},
    },

    # ── 단일 임계치: -4.5% ───────────────────────────────────────────
    {
        "name":  "⑥ -4.5%→5일",
        "guard": {"mode": "step", "steps": [(-4.5, 5)]},
    },
    {
        "name":  "⑦ -4.5%→10일",
        "guard": {"mode": "step", "steps": [(-4.5, 10)]},
    },

    # ── 계단식 복합 임계치 ───────────────────────────────────────────
    {
        "name":  "⑧ 계단 [-4%→5일 / -5%→10일]",
        "guard": {"mode": "step", "steps": [(-5.0, 10), (-4.0, 5)]},
    },
    {
        "name":  "⑨ 계단 [-4.5%→7일 / -5%→10일]",
        "guard": {"mode": "step", "steps": [(-5.0, 10), (-4.5, 7)]},
    },
    {
        "name":  "⑩ 계단 [-4%→5일 / -5%→15일]",
        "guard": {"mode": "step", "steps": [(-5.0, 15), (-4.0, 5)]},
    },
    {
        "name":  "⑪ 계단 [-4%→5일 / -4.5%→7일 / -5%→10일]",
        "guard": {"mode": "step", "steps": [(-5.0, 10), (-4.5, 7), (-4.0, 5)]},
    },

    # ── 선형 스케일링 ────────────────────────────────────────────────
    {
        "name":  "⑫ 선형 [-4%→5일 ~ -5%→10일]",
        "guard": {"mode": "linear",
                  "start_pct": -4.0, "start_days": 5,
                  "end_pct":   -5.0, "end_days":  10, "cap_days": 10},
    },
    {
        "name":  "⑬ 선형 [-3%→3일 ~ -5%→10일]",
        "guard": {"mode": "linear",
                  "start_pct": -3.0, "start_days": 3,
                  "end_pct":   -5.0, "end_days":  10, "cap_days": 10},
    },
    {
        "name":  "⑭ 선형 [-4%→5일 ~ -5%→15일]",
        "guard": {"mode": "linear",
                  "start_pct": -4.0, "start_days": 5,
                  "end_pct":   -5.0, "end_days":  15, "cap_days": 15},
    },
    {
        "name":  "⑮ 선형 [-4%→5일 ~ -6%→15일]",
        "guard": {"mode": "linear",
                  "start_pct": -4.0, "start_days": 5,
                  "end_pct":   -6.0, "end_days":  15, "cap_days": 15},
    },
]


# ── 가드 설정으로 쿨다운 일수 계산 ───────────────────────────────────────

def _calc_cooldown(qqq_chg: float, guard: dict) -> tuple[int, str]:
    """(cooldown_days, reason_str) 반환"""
    mode = guard.get("mode", "none")

    if mode == "none" or qqq_chg > 0:
        return 0, ""

    if mode == "step":
        steps: list[tuple[float, int]] = guard["steps"]
        # 가장 엄격한(더 낮은) 임계치부터 확인
        for threshold, days in sorted(steps, key=lambda x: x[0]):
            if qqq_chg <= threshold:
                return days, f"QQQ{qqq_chg:.1f}%≤{threshold}%→{days}일"
        return 0, ""

    if mode == "linear":
        s_pct  = guard["start_pct"]   # e.g. -4.0
        s_days = guard["start_days"]  # e.g.  5
        e_pct  = guard["end_pct"]     # e.g. -5.0
        e_days = guard["end_days"]    # e.g. 10
        cap    = guard.get("cap_days", e_days)

        if qqq_chg > s_pct:           # 미달
            return 0, ""
        if qqq_chg <= e_pct:          # 상한 초과
            return cap, f"QQQ{qqq_chg:.1f}%≤{e_pct}%→{cap}일(cap)"
        t    = (qqq_chg - s_pct) / (e_pct - s_pct)   # 0 → 1
        days = max(1, round(s_days + t * (e_days - s_days)))
        return days, f"QQQ{qqq_chg:.1f}%→선형{days}일"

    return 0, ""


# ── 핵심 시뮬레이션 (유연한 가드 설정 지원) ──────────────────────────────

def simulate_flexible(
    close:       pd.Series,
    fng:         pd.Series,
    qqq_close:   pd.Series,
    period:      int,
    buy_below:   float,
    sell_above:  float,
    fear_max:    int,
    greed_min:   int,
    guard:       dict,          # SCENARIOS[i]["guard"]
) -> tuple[pd.DataFrame, dict[int, dict]]:

    alpha  = 1.0 / period
    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    next_buy_limits, next_sell_limits = _build_next_day_limits(
        closes, ma_up, ma_down, buy_below, sell_above, alpha,
    )

    fng_aligned = fng.reindex(close.index, method="ffill").fillna(50).astype(int)
    qqq_aligned = qqq_close.reindex(close.index, method="ffill")
    qqq_aligned = qqq_aligned.ffill().bfill()
    qqq_vals    = qqq_aligned.values.astype(float)
    qqq_chg_arr = np.zeros(n)
    for i in range(1, n):
        if qqq_vals[i - 1] > 0:
            qqq_chg_arr[i] = (qqq_vals[i] / qqq_vals[i - 1] - 1.0) * 100.0

    cash                     = CAPITAL
    holdings                 = 0.0
    cash_at_buy              = 0.0
    annual_realized_pnl      = 0.0
    annual_profit_ytd        = 0.0
    current_tax_year         = None
    total_tax_paid           = 0.0
    annual_taxes: dict       = {}
    pending_tax              = 0.0
    pending_tax_year         = None
    pending_tax_total_before = 0.0
    cooldown_until: datetime | None = None

    rows: list[dict] = []

    def _apply_pending_tax():
        nonlocal cash, total_tax_paid, pending_tax, pending_tax_year
        nonlocal pending_tax_total_before, annual_profit_ytd
        if pending_tax <= 0:
            return None
        tax = pending_tax
        cash           -= tax
        total_tax_paid += tax
        annual_taxes[pending_tax_year] = {
            "tax":          tax,
            "total_before": pending_tax_total_before,
            "deducted_on":  dt.strftime("%Y-%m-%d"),
        }
        pending_tax              = 0.0
        pending_tax_year         = None
        pending_tax_total_before = 0.0
        annual_profit_ytd        = 0.0
        return tax

    for i, (dt, price) in enumerate(close.items()):
        rsi_val = rsi[i]
        fng_val = int(fng_aligned.iloc[i])
        qqq_chg = float(qqq_chg_arr[i])

        action        = "HOLD"
        fng_blocked   = ""
        trade_qty     = 0.0
        buy_cash_used = ""
        tax_today     = None

        # 연간 양도세 처리
        if current_tax_year is None:
            current_tax_year = dt.year
        elif dt.year != current_tax_year:
            taxable = max(0.0, annual_realized_pnl - TAX_EXEMPT)
            pending_tax_total_before = rows[-1]["total_assets"] if rows else 0.0
            pending_tax      = round(taxable * TAX_RATE, 2) if taxable > 0 else 0.0
            pending_tax_year = current_tax_year
            if pending_tax == 0.0:
                annual_taxes[pending_tax_year] = {
                    "tax": 0.0, "total_before": pending_tax_total_before,
                    "deducted_on": dt.strftime("%Y-%m-%d"),
                }
                annual_profit_ytd = 0.0
                pending_tax_year  = None
            annual_realized_pnl = 0.0
            current_tax_year    = dt.year

        if i > 0:
            # QQQ Crash Guard
            cd_days, cd_reason = _calc_cooldown(qqq_chg, guard)

            if cd_days > 0:
                new_until = dt + timedelta(days=cd_days)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                if holdings > 0:
                    realized = holdings * price - cash_at_buy
                    annual_realized_pnl += realized
                    annual_profit_ytd   += realized
                    trade_qty = -holdings
                    cash     += holdings * price
                    holdings  = 0.0
                    t = _apply_pending_tax()
                    tax_today    = t
                    action       = "SELL_QQQ"
                    fng_blocked  = cd_reason
                else:
                    fng_blocked = cd_reason  # 현금보유 중 쿨다운 연장

            # RSI+FnG 로직
            if action == "HOLD":
                prev_buy  = next_buy_limits[i - 1]
                prev_sell = next_sell_limits[i - 1]
                in_cd     = (cooldown_until is not None and dt <= cooldown_until)

                if holdings == 0.0 and not np.isnan(prev_buy) and float(price) <= float(prev_buy):
                    if in_cd:
                        rem = (cooldown_until - dt).days
                        fng_blocked = f"QQQ차단({rem}일남음)"
                    elif fng_val >= greed_min:
                        fng_blocked = f"BUY차단(F&G={fng_val}≥{greed_min})"
                    else:
                        t = _apply_pending_tax()
                        tax_today     = t
                        cash_at_buy   = cash
                        buy_cash_used = round(float(cash), 2)
                        bought        = cash / price
                        holdings      = bought
                        cash          = 0.0
                        trade_qty     = bought
                        action        = "BUY"

                elif holdings > 0 and not np.isnan(prev_sell) and float(price) >= float(prev_sell):
                    if fng_val <= fear_max:
                        fng_blocked = f"SELL차단(F&G={fng_val}≤{fear_max})"
                    else:
                        realized = holdings * price - cash_at_buy
                        annual_realized_pnl += realized
                        annual_profit_ytd   += realized
                        trade_qty = -holdings
                        cash     += holdings * price
                        holdings  = 0.0
                        t = _apply_pending_tax()
                        tax_today = t
                        action    = "SELL"

        total_assets = cash + holdings * float(price)
        prev_price   = float(closes[i - 1]) if i > 0 else float(price)
        daily_chg    = round((float(price) / prev_price - 1) * 100, 2) if i > 0 else ""
        cd_rem       = max(0, (cooldown_until - dt).days) if cooldown_until and dt <= cooldown_until else 0

        rows.append({
            "date":           dt.strftime("%Y-%m-%d"),
            "close":          round(float(price), 4),
            "chg_pct":        daily_chg,
            "qqq_chg_pct":    round(qqq_chg, 2) if i > 0 else "",
            "fng":            fng_val,
            f"rsi{period}":   round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "fng_blocked":    fng_blocked,
            "cooldown_days":  cd_rem if cd_rem > 0 else "",
            "action":         action,
            "trade_qty":      round(float(trade_qty), 6),
            "buy_cash_used":  buy_cash_used,
            "holdings":       round(float(holdings), 6),
            "cash":           round(float(cash), 2),
            "total_assets":   round(float(total_assets), 2),
            "return_pct":     round(float((total_assets / CAPITAL - 1) * 100), 4),
            "annual_profit_ytd": round(float(annual_profit_ytd), 2),
            "tax_deducted":   "" if tax_today is None else round(float(tax_today), 2),
        })

    # 마지막 연도 양도세
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if rows:
        tax_final = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
        if tax_final > 0:
            total_tax_paid         += tax_final
            rows[-1]["total_assets"] = round(rows[-1]["total_assets"] - tax_final, 2)
            rows[-1]["return_pct"]   = round((rows[-1]["total_assets"] / CAPITAL - 1) * 100, 4)
            rows[-1]["annual_profit_ytd"] = 0.0
            existing = rows[-1].get("tax_deducted", "")
            rows[-1]["tax_deducted"] = round((float(existing) if existing != "" else 0.0) + tax_final, 2)
            annual_taxes[current_tax_year] = {
                "tax":          tax_final,
                "total_before": rows[-1]["total_assets"] + tax_final,
                "deducted_on":  rows[-1]["date"],
            }

    return pd.DataFrame(rows), annual_taxes


# ── Google Sheet 저장 ─────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    """1→A, 26→Z, 27→AA, 28→AB … 무제한"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_results(
    all_results: dict[str, list[dict]],   # {ticker: [{name, perf, yearly}, ...]}
):
    from sheets_manager import SheetsManager
    sm = SheetsManager(spreadsheet_id=None)   # 새 시트 생성용 (get_client만 사용)
    gc = sm._get_client()

    sheet_title = f"QQQ_IntermediateGuard_{START_DATE[:4]}_{END_DATE[:4]}"
    print(f"\n[GoogleSheets] 새 스프레드시트 생성: {sheet_title}")
    ss  = gc.create(sheet_title)
    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    # ── 1. 비교 Summary 탭 ─────────────────────────────────────────
    ws = ss.sheet1
    ws.update_title("비교Summary")

    year_labels: list[str] = []
    for ticker, results in all_results.items():
        for r in results:
            for y in r["yearly"].keys():
                if y not in year_labels:
                    year_labels.append(y)
    year_labels.sort()

    header_cols = ["종목", "시나리오", "CAGR(%)", "총수익률(%)", "MDD(%)",
                   "최종자산($)", "승률(%)", "사이클수", "QQQ강제매도", "양도세($)",
                   "기준대비CAGR차(%p)", "기준대비MDD차(%p)"] + year_labels

    rows = [
        [f"QQQ Crash Guard 중간낙폭 대응 비교  {START_DATE} ~ {END_DATE}  초기자본 ${CAPITAL:,.0f}"],
        [f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"비교기준: ① 기준선(가드없음) | CAGR 내림차순 정렬"],
        [],
        header_cols,
    ]

    for ticker, results in all_results.items():
        baseline_cagr = next(r["perf"]["cagr_pct"] for r in results if "기준선" in r["name"])
        baseline_mdd  = next(r["perf"]["mdd_pct"]  for r in results if "기준선" in r["name"])
        for r in results:
            p = r["perf"]
            rows.append([
                ticker,
                r["name"],
                p["cagr_pct"],
                p["total_return_pct"],
                p["mdd_pct"],
                p["final_assets"],
                p["win_rate"],
                p["cycles"],
                p["sell_qqq_count"],
                p["total_tax_paid"],
                round(p["cagr_pct"] - baseline_cagr, 2),
                round(p["mdd_pct"]  - baseline_mdd, 2),
            ] + [r["yearly"].get(y, "") for y in year_labels])
        rows.append([])

    max_c = max(len(r) for r in rows if r)
    col_l = _col_letter(max_c)
    ws.update(range_name=f"A1:{col_l}{len(rows)}", values=rows)
    print("[GoogleSheets] 비교Summary 저장 완료")

    # ── 2. 종목별 시나리오 순위 탭 ─────────────────────────────────
    for ticker, results in all_results.items():
        tab  = f"{ticker}_순위"
        ws2  = ss.add_worksheet(title=tab, rows=max(50, len(results) + 10), cols=20)
        hdr  = ["순위", "시나리오", "CAGR(%)", "총수익률(%)", "MDD(%)",
                "최종자산($)", "승률(%)", "사이클수", "QQQ강제매도",
                "양도세($)", "기준대비CAGR(%p)", "기준대비MDD(%p)"]
        baseline_cagr = next(r["perf"]["cagr_pct"] for r in results if "기준선" in r["name"])
        baseline_mdd  = next(r["perf"]["mdd_pct"]  for r in results if "기준선" in r["name"])

        # CAGR 기준 정렬
        sorted_r = sorted(results, key=lambda x: x["perf"]["cagr_pct"], reverse=True)
        meta = [
            [f"{ticker}  시나리오별 성과 비교 (CAGR 내림차순)  {START_DATE}~{END_DATE}"],
            [],
            hdr,
        ]
        data = []
        for rank, r in enumerate(sorted_r, 1):
            p = r["perf"]
            data.append([
                rank, r["name"], p["cagr_pct"], p["total_return_pct"],
                p["mdd_pct"], p["final_assets"], p["win_rate"],
                p["cycles"], p["sell_qqq_count"], p["total_tax_paid"],
                round(p["cagr_pct"] - baseline_cagr, 2),
                round(p["mdd_pct"]  - baseline_mdd, 2),
            ])
        col_l = _col_letter(len(hdr))
        ws2.update(range_name=f"A1:{col_l}{len(meta)}", values=meta)
        ws2.update(range_name=f"A{len(meta)+1}:{col_l}{len(meta)+len(data)}", values=data)
        print(f"[GoogleSheets] {tab} 저장 완료")

    # ── 3. 연도별 수익률 탭 ────────────────────────────────────────
    ws3 = ss.add_worksheet(title="연도별수익률", rows=100, cols=30)
    yr_rows = [
        [f"연도별 수익률(%) — 시나리오별  {START_DATE}~{END_DATE}"],
        [],
    ]
    yr_hdr = ["종목", "시나리오"] + year_labels
    yr_rows.append(yr_hdr)
    for ticker, results in all_results.items():
        for r in results:
            yr_rows.append([ticker, r["name"]] + [r["yearly"].get(y, "") for y in year_labels])
        yr_rows.append([])
    col_l = _col_letter(len(yr_hdr))
    ws3.update(range_name=f"A1:{col_l}{len(yr_rows)}", values=yr_rows)
    print("[GoogleSheets] 연도별수익률 저장 완료")

    return url, ss.id


# ── main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 75)
    print(f"QQQ Crash Guard 중간낙폭 비교  {START_DATE} ~ {END_DATE}")
    print(f"시나리오 수: {len(SCENARIOS)}개")
    print("=" * 75)

    # 공통 데이터 로딩
    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
    except Exception:
        fng_base = pd.Series(dtype=float)

    print("\n[QQQ] 가격 데이터 다운로드...")
    qqq_close = download_close("QQQ")
    print(f"[QQQ] {len(qqq_close)}일 ({qqq_close.index[0].date()} ~ {qqq_close.index[-1].date()})")

    # QQQ 낙폭 통계 (참고용)
    qqq_vals  = qqq_close.values.astype(float)
    qqq_chgs  = np.zeros(len(qqq_vals))
    for i in range(1, len(qqq_vals)):
        if qqq_vals[i - 1] > 0:
            qqq_chgs[i] = (qqq_vals[i] / qqq_vals[i - 1] - 1) * 100
    print(f"\n[QQQ 낙폭 통계]")
    for thresh in [-3.0, -3.5, -4.0, -4.5, -5.0, -5.5, -6.0]:
        cnt = int((qqq_chgs <= thresh).sum())
        print(f"  QQQ ≤ {thresh:+.1f}%: {cnt}일 ({cnt/len(qqq_chgs)*100:.1f}% of 거래일)")

    all_results: dict[str, list[dict]] = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n{'='*60}")
        print(f"[{ticker}] 가격 다운로드 및 시나리오 실행...")
        close = download_close(ticker)
        fng   = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)
        ticker_results = []
        baseline_cagr  = None

        for sc in SCENARIOS:
            df, taxes = simulate_flexible(
                close=close, fng=fng, qqq_close=qqq_close,
                period=cfg["period"], buy_below=cfg["buy_below"],
                sell_above=cfg["sell_above"], fear_max=cfg["fear_max"],
                greed_min=cfg["greed_min"], guard=sc["guard"],
            )
            perf = calc_perf(df, taxes)
            yr   = yearly_returns(df, taxes)

            if "기준선" in sc["name"]:
                baseline_cagr = perf["cagr_pct"]
                baseline_mdd  = perf["mdd_pct"]

            vs_cagr = f"{perf['cagr_pct'] - baseline_cagr:+.1f}%p" if baseline_cagr is not None else ""
            print(f"  {sc['name']:40s}  CAGR {perf['cagr_pct']:5.1f}% {vs_cagr:10s}  "
                  f"MDD {perf['mdd_pct']:6.1f}%  QQQ매도 {perf['sell_qqq_count']}회")

            ticker_results.append({
                "name":  sc["name"],
                "guard": sc["guard"],
                "perf":  perf,
                "yearly": yr,
                "df":    df,
                "taxes": taxes,
            })

        all_results[ticker] = ticker_results

        # 순위 요약 출력
        sorted_r = sorted(ticker_results, key=lambda x: x["perf"]["cagr_pct"], reverse=True)
        print(f"\n  [{ticker}] CAGR 순위:")
        for rank, r in enumerate(sorted_r[:6], 1):
            p = r["perf"]
            print(f"    #{rank} {r['name']:40s}  CAGR {p['cagr_pct']:.1f}%  MDD {p['mdd_pct']:.1f}%  QQQ매도 {p['sell_qqq_count']}회")

    # Google Sheet 저장
    print("\n" + "="*75)
    print("Google Sheet 저장 중...")
    url, sheet_id = write_results(all_results)

    # 최종 결론
    print("\n" + "="*75)
    print("[ 최종 비교 요약 ]")
    for ticker, results in all_results.items():
        baseline = next(r for r in results if "기준선" in r["name"])
        best     = max(results, key=lambda x: x["perf"]["cagr_pct"])
        prev_best = next(r for r in results if "전회최적" in r["name"])
        print(f"\n{ticker}:")
        print(f"  ① 기준선  : CAGR {baseline['perf']['cagr_pct']:.1f}%  MDD {baseline['perf']['mdd_pct']:.1f}%")
        print(f"  ② 전회최적: CAGR {prev_best['perf']['cagr_pct']:.1f}%  MDD {prev_best['perf']['mdd_pct']:.1f}%")
        print(f"  ★ 이번최적: CAGR {best['perf']['cagr_pct']:.1f}%  MDD {best['perf']['mdd_pct']:.1f}%  ← {best['name']}")
    print(f"\nGoogle Sheet: {url}")
    print("="*75)


if __name__ == "__main__":
    main()
