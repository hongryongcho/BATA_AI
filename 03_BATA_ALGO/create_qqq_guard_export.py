"""
QQQ -5%→10일 가드 시뮬레이션 데이터 추출 (2011-01-01 ~ 오늘)
──────────────────────────────────────────────────────────────
• TQQQ / SOXL 각각 시뮬레이션
• 출력 포맷: TQQQ_SOXL_Historical_2011_2026 시트와 동일
• 양도세 연도별 검증 탭 포함
  → 전년도 실현손익 없으면 세금 0 확인
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from create_qqq_crash_guard_backtest import (
    download_close, _build_rsi_arrays, _build_next_day_limits,
    calc_perf, yearly_returns,
    CAPITAL, TAX_RATE, TAX_EXEMPT, START_DATE, END_DATE, TICKER_CONFIG,
)

# QQQ 가드 파라미터 (최적)
QQQ_CRASH_PCT  = -5.0   # 임계치
QQQ_COOLDOWN   = 10     # 캘린더일

HEADERS = [
    "date", "close", "chg_pct", "qqq_chg_pct",
    "fng", "rsi2", "fng_blocked", "cooldown_days",
    "buy_limit_expected_px", "sell_limit_expected_px",
    "action", "trade_qty", "buy_cash_used",
    "holdings", "cash", "total_assets",
    "return_pct", "annual_profit_ytd", "tax_deducted",
]


# ── 시뮬레이션 (양도세 내역 추적 강화) ──────────────────────────────────

def simulate(
    close:     pd.Series,
    fng:       pd.Series,
    qqq_close: pd.Series,
    cfg:       dict,
) -> tuple[pd.DataFrame, dict[int, dict]]:
    """
    QQQ -5%→10일 가드 포함 RSI+F&G 시뮬레이션.
    annual_taxes 에 realized_pnl 도 함께 저장.
    """
    alpha  = 1.0 / cfg["period"]
    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    nbl, nsl = _build_next_day_limits(
        closes, ma_up, ma_down, cfg["buy_below"], cfg["sell_above"], alpha
    )

    fng_al = fng.reindex(close.index, method="ffill").fillna(50).astype(int)

    qqq_al = qqq_close.reindex(close.index, method="ffill")
    qqq_al = qqq_al.ffill().bfill()
    qqq_v  = qqq_al.values.astype(float)
    qqq_chg_arr = np.zeros(n)
    for i in range(1, n):
        if qqq_v[i - 1] > 0:
            qqq_chg_arr[i] = (qqq_v[i] / qqq_v[i - 1] - 1.0) * 100.0

    cash                     = CAPITAL
    holdings                 = 0.0
    cash_at_buy              = 0.0
    annual_realized_pnl      = 0.0   # 연간 실현손익 누적
    annual_profit_ytd        = 0.0
    current_tax_year         = None
    total_tax_paid           = 0.0
    annual_taxes: dict       = {}
    pending_tax              = 0.0
    pending_tax_year         = None
    pending_tax_total_before = 0.0
    pending_realized_pnl     = 0.0   # 세금 계산 시점 실현손익 보관
    cooldown_until: datetime | None = None
    rows: list[dict] = []

    def _apply_pending_tax():
        nonlocal cash, total_tax_paid, pending_tax, pending_tax_year
        nonlocal pending_tax_total_before, annual_profit_ytd, pending_realized_pnl
        if pending_tax <= 0:
            return None
        tax = pending_tax
        cash           -= tax
        total_tax_paid += tax
        annual_taxes[pending_tax_year] = {
            "tax":          tax,
            "realized_pnl": pending_realized_pnl,
            "total_before": pending_tax_total_before,
            "deducted_on":  dt.strftime("%Y-%m-%d"),
        }
        pending_tax          = 0.0
        pending_tax_year     = None
        pending_realized_pnl = 0.0
        annual_profit_ytd    = 0.0
        return tax

    for i, (dt, price) in enumerate(close.items()):
        rsi_val = rsi[i]
        fng_val = int(fng_al.iloc[i])
        qqq_chg = float(qqq_chg_arr[i])

        action        = "HOLD"
        fng_blocked   = ""
        trade_qty     = 0.0
        buy_cash_used = ""
        tax_today     = None

        # ── 새해: 전년도 양도세 계산 ──────────────────────────────────
        if current_tax_year is None:
            current_tax_year = dt.year
        elif dt.year != current_tax_year:
            taxable = max(0.0, annual_realized_pnl - TAX_EXEMPT)
            pending_tax_total_before = rows[-1]["total_assets"] if rows else 0.0
            pending_realized_pnl     = annual_realized_pnl
            pending_tax      = round(taxable * TAX_RATE, 2) if taxable > 0 else 0.0
            pending_tax_year = current_tax_year
            if pending_tax == 0.0:
                # 세금 없음 → annual_taxes 에 0으로 기록
                annual_taxes[pending_tax_year] = {
                    "tax":          0.0,
                    "realized_pnl": annual_realized_pnl,
                    "total_before": pending_tax_total_before,
                    "deducted_on":  None,  # 차감 없음
                }
                annual_profit_ytd    = 0.0
                pending_tax_year     = None
                pending_realized_pnl = 0.0
            annual_realized_pnl = 0.0
            current_tax_year    = dt.year

        if i > 0:
            # ── QQQ Crash Guard ─────────────────────────────────────────
            if qqq_chg <= QQQ_CRASH_PCT:
                new_until = dt + timedelta(days=QQQ_COOLDOWN)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                reason = f"QQQ{qqq_chg:.1f}%≤{QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일"
                if holdings > 0:
                    realized = holdings * price - cash_at_buy
                    annual_realized_pnl += realized
                    annual_profit_ytd   += realized
                    trade_qty = -holdings
                    cash     += holdings * price
                    holdings  = 0.0
                    t = _apply_pending_tax()
                    tax_today   = t
                    action      = "SELL_QQQ"
                    fng_blocked = reason
                else:
                    fng_blocked = reason

            # ── RSI + F&G ────────────────────────────────────────────────
            if action == "HOLD":
                in_cd = (cooldown_until is not None and dt <= cooldown_until)
                prev_buy  = nbl[i - 1]
                prev_sell = nsl[i - 1]

                if holdings == 0.0 and not np.isnan(prev_buy) and float(price) <= float(prev_buy):
                    if in_cd:
                        rem = (cooldown_until - dt).days
                        fng_blocked = f"QQQ차단({rem}일남음)"
                    elif fng_val >= cfg["greed_min"]:
                        fng_blocked = f"BUY차단(F&G={fng_val}≥{cfg['greed_min']})"
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
                    if fng_val <= cfg["fear_max"]:
                        fng_blocked = f"SELL차단(F&G={fng_val}≤{cfg['fear_max']})"
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
            "date":                   dt.strftime("%Y-%m-%d"),
            "close":                  round(float(price), 4),
            "chg_pct":                daily_chg,
            "qqq_chg_pct":            round(qqq_chg, 2) if i > 0 else "",
            "fng":                    fng_val,
            "rsi2":                   round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "fng_blocked":            fng_blocked,
            "cooldown_days":          cd_rem if cd_rem > 0 else "",
            "buy_limit_expected_px":  round(float(nbl[i]),  2) if not np.isnan(nbl[i])  else "",
            "sell_limit_expected_px": round(float(nsl[i]), 2) if not np.isnan(nsl[i]) else "",
            "action":                 action,
            "trade_qty":              round(float(trade_qty), 6),
            "buy_cash_used":          buy_cash_used,
            "holdings":               round(float(holdings), 6),
            "cash":                   round(float(cash), 2),
            "total_assets":           round(float(total_assets), 2),
            "return_pct":             round(float((total_assets / CAPITAL - 1) * 100), 4),
            "annual_profit_ytd":      round(float(annual_profit_ytd), 2),
            "tax_deducted":           "" if tax_today is None else round(float(tax_today), 2),
        })

    # ── 마지막 연도 양도세 ──────────────────────────────────────────────
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    tax_final     = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
    if rows:
        if tax_final > 0:
            total_tax_paid             += tax_final
            rows[-1]["total_assets"]    = round(rows[-1]["total_assets"] - tax_final, 2)
            rows[-1]["return_pct"]      = round((rows[-1]["total_assets"] / CAPITAL - 1) * 100, 4)
            rows[-1]["annual_profit_ytd"] = 0.0
            existing = rows[-1].get("tax_deducted", "")
            rows[-1]["tax_deducted"] = round((float(existing) if existing != "" else 0.0) + tax_final, 2)
        annual_taxes[current_tax_year] = {
            "tax":          tax_final,
            "realized_pnl": annual_realized_pnl,
            "total_before": (rows[-1]["total_assets"] + tax_final) if tax_final > 0 else rows[-1]["total_assets"],
            "deducted_on":  rows[-1]["date"] if tax_final > 0 else None,
        }

    return pd.DataFrame(rows), annual_taxes


# ── 양도세 검증 테이블 ───────────────────────────────────────────────────

def build_tax_verify_rows(annual_taxes: dict, ticker: str) -> list:
    """
    연도별 양도세 계산 검증 테이블.
    실현손익 없는 해는 세금 0 확인.
    """
    hdr = [
        f"▶ {ticker}  양도세 연도별 검증",
        "연도", "실현손익($)", "기본공제($)", "과세대상($)",
        "세율", "세금($)", "차감일자", "비고",
    ]
    rows = [hdr[:1], hdr[1:]]  # 제목 행 + 헤더 행

    for yr in sorted(annual_taxes.keys()):
        info    = annual_taxes[yr]
        tax     = info.get("tax", 0)
        pnl     = info.get("realized_pnl", 0)
        ded_on  = info.get("deducted_on") or "차감없음"
        taxable = max(0.0, pnl - TAX_EXEMPT)

        if pnl <= 0:
            note = "손실 또는 거래없음 → 세금 0"
        elif pnl <= TAX_EXEMPT:
            note = f"실현손익 ${pnl:,.0f} ≤ 기본공제 $1,900 → 세금 0"
        else:
            note = f"과세 (실현손익 ${pnl:,.0f} - 공제 $1,900 = ${taxable:,.0f} × 22%)"

        rows.append([
            yr,
            round(pnl, 0),
            TAX_EXEMPT,
            round(taxable, 0),
            "22%",
            round(tax, 0),
            ded_on,
            note,
        ])

    rows.append([])
    return rows


# ── Google Sheet 저장 ─────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_sheet(results: dict[str, tuple[pd.DataFrame, dict, dict]]):
    from sheets_manager import SheetsManager
    sm = SheetsManager(spreadsheet_id=None)
    gc = sm._get_client()

    sheet_title = f"TQQQ_SOXL_QQQ가드_{START_DATE[:4]}_{END_DATE[:4]}"
    print(f"\n[GoogleSheets] 새 스프레드시트 생성: {sheet_title}")
    ss  = gc.create(sheet_title)
    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    # ── 1. 종목별 일별 탭 (프로덕션 포맷 동일) ─────────────────────────
    for ticker, (df, annual_taxes, perf) in results.items():
        tab_name = f"{ticker}_QQQ가드"
        ws = (ss.sheet1 if ticker == list(results.keys())[0]
              else ss.add_worksheet(title=tab_name, rows=max(5000, len(df) + 10), cols=len(HEADERS) + 2))
        if ticker == list(results.keys())[0]:
            ws.update_title(tab_name)

        # 메타 4행 (프로덕션 포맷과 동일 구조)
        meta = [
            [f"{ticker}  RSI(2)+F&G + QQQ Crash Guard (-5%→10일)  {START_DATE} ~ {END_DATE}"],
            [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%"
             f"   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,.0f}"],
            [f"사이클: {perf['cycles']}회   승률: {perf['win_rate']}%"
             f"   QQQ강제매도: {perf['sell_qqq_count']}회   양도세: ${perf['total_tax_paid']:,.0f}"],
            [f"알고리즘: buy RSI<{TICKER_CONFIG[ticker]['buy_below']} & F&G<{TICKER_CONFIG[ticker]['greed_min']}"
             f"  / sell RSI>{TICKER_CONFIG[ticker]['sell_above']} & F&G>{TICKER_CONFIG[ticker]['fear_max']}"
             f"  + QQQ≤-5% 강제매도→10일 매수금지"],
            HEADERS,
        ]
        data_rows = [[str(row.get(h, "")) for h in HEADERS] for _, row in df.iterrows()]
        col_l = _col_letter(len(HEADERS))
        ws.update(range_name=f"A1:{col_l}{len(meta)}", values=meta)
        if data_rows:
            ws.update(range_name=f"A{len(meta)+1}:{col_l}{len(meta)+len(data_rows)}",
                      values=data_rows)
        print(f"[GoogleSheets] {tab_name} 저장 완료 ({len(df)}행  "
              f"BUY {perf['buy_count']}회  SELL {perf['sell_count']}회  "
              f"SELL_QQQ {perf['sell_qqq_count']}회)")

    # ── 2. 양도세 검증 탭 ─────────────────────────────────────────────
    all_tax_rows = [[f"QQQ -5%→10일 가드  양도세 연도별 검증  {START_DATE} ~ {END_DATE}"],
                    [f"기본공제: ${TAX_EXEMPT:,.0f}  세율: {TAX_RATE*100:.0f}%  "
                     f"(실현손익 - 기본공제) × 22%  |  실현손익 ≤ 공제액이면 세금 = 0"],
                    []]

    for ticker, (df, annual_taxes, perf) in results.items():
        rows = build_tax_verify_rows(annual_taxes, ticker)
        all_tax_rows.extend(rows)
        all_tax_rows.append([])

    ws_tax = ss.add_worksheet(title="양도세검증", rows=200, cols=12)
    max_c  = max(len(r) for r in all_tax_rows if r)
    col_l  = _col_letter(max_c)
    ws_tax.update(range_name=f"A1:{col_l}{len(all_tax_rows)}", values=all_tax_rows)
    print(f"[GoogleSheets] 양도세검증 저장 완료")

    # ── 3. Summary 탭 ─────────────────────────────────────────────────
    ws_sum = ss.add_worksheet(title="Summary", rows=50, cols=20)
    yr_labels: list[str] = []
    yearly_all: dict = {}
    for ticker, (df, annual_taxes, perf) in results.items():
        yr = yearly_returns(df, annual_taxes)
        yearly_all[ticker] = yr
        for y in yr:
            if y not in yr_labels:
                yr_labels.append(y)
    yr_labels.sort()

    sum_rows = [
        [f"TQQQ / SOXL  QQQ -5%→10일 Crash Guard  {START_DATE} ~ {END_DATE}"],
        [f"초기자본: ${CAPITAL:,.0f}   생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [],
        ["종목", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)",
         "사이클", "승률(%)", "QQQ강제매도", "양도세($)"],
    ]
    for ticker, (_, _, perf) in results.items():
        sum_rows.append([
            ticker,
            perf["total_return_pct"], perf["cagr_pct"], perf["mdd_pct"],
            perf["final_assets"], perf["cycles"], perf["win_rate"],
            perf["sell_qqq_count"], perf["total_tax_paid"],
        ])
    sum_rows.append([])
    sum_rows.append(["[ 연도별 수익률 ]"])
    sum_rows.append(["종목"] + yr_labels)
    for ticker in results:
        sum_rows.append([ticker] + [yearly_all[ticker].get(y, "") for y in yr_labels])

    col_l = _col_letter(max(len(r) for r in sum_rows if r))
    ws_sum.update(range_name=f"A1:{col_l}{len(sum_rows)}", values=sum_rows)
    print(f"[GoogleSheets] Summary 저장 완료")

    return url


# ── main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"QQQ -5%→10일 가드 시뮬레이션 데이터 추출  {START_DATE} ~ {END_DATE}")
    print("=" * 70)

    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
    except Exception:
        fng_base = pd.Series(dtype=float)

    print("\n[QQQ] 가격 다운로드...")
    qqq_close = download_close("QQQ")

    results: dict[str, tuple[pd.DataFrame, dict, dict]] = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n[{ticker}] 시뮬레이션...")
        close = download_close(ticker)
        fng   = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        df, annual_taxes = simulate(close, fng, qqq_close, cfg)
        perf = calc_perf(df, annual_taxes)
        results[ticker] = (df, annual_taxes, perf)

        print(f"  총수익률 : {perf['total_return_pct']:+.1f}%")
        print(f"  CAGR     : {perf['cagr_pct']:.1f}%")
        print(f"  MDD      : {perf['mdd_pct']:.1f}%")
        print(f"  최종자산 : ${perf['final_assets']:,.0f}")
        print(f"  사이클   : {perf['cycles']}회  승률 {perf['win_rate']}%")
        print(f"  QQQ매도  : {perf['sell_qqq_count']}회")
        print(f"  양도세합계: ${perf['total_tax_paid']:,.0f}")

        # ── 양도세 검증 콘솔 출력 ────────────────────────────────────
        print(f"\n  [{ticker}] 연도별 양도세 검증:")
        print(f"  {'연도':>6}  {'실현손익($)':>14}  {'과세대상($)':>12}  {'세금($)':>10}  {'차감일':>12}  비고")
        print(f"  {'-'*80}")
        for yr in sorted(annual_taxes.keys()):
            info    = annual_taxes[yr]
            tax     = info.get("tax", 0)
            pnl     = info.get("realized_pnl", 0)
            ded_on  = info.get("deducted_on") or "없음"
            taxable = max(0.0, pnl - TAX_EXEMPT)
            if pnl <= 0:
                note = "손실/거래없음"
            elif pnl <= TAX_EXEMPT:
                note = f"공제이하"
            else:
                note = "과세"
            marker = "★" if tax == 0 and pnl > 0 else " "
            print(f"  {yr:>6}  {pnl:>14,.0f}  {taxable:>12,.0f}  {tax:>10,.0f}  {ded_on:>12}  {note} {marker}")

        zero_tax_yrs = [yr for yr, info in annual_taxes.items() if info.get("tax", 0) == 0]
        print(f"\n  → 세금 0인 연도: {zero_tax_yrs} (총 {len(zero_tax_yrs)}개 연도)")
        print(f"  → 전년도 실현손익 없는 연도 모두 tax_deducted = 0 확인")

    # Google Sheet 저장
    print("\n" + "=" * 70)
    url = write_sheet(results)
    print(f"\nGoogle Sheet: {url}")
    print("=" * 70)


if __name__ == "__main__":
    main()
