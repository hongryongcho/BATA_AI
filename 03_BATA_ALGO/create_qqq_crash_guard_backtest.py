"""
TQQQ / SOXL  QQQ Crash Guard 백테스트  (2011-01-01 ~ 오늘)
─────────────────────────────────────────────────────────────
기본 알고리즘 : RSI(2) + Fear&Greed (production과 동일)
추가 알고리즘 : QQQ 당일 낙폭 임계치 시 강제 매도 + N일 시장 휴식

임계치 (기본값):
  QQQ -3% 이하 → 즉시 전량 매도 → 15 캘린더일 매수 금지
  QQQ -5% 이하 → 즉시 전량 매도 → 30 캘린더일 매수 금지
  (-5% 가 -3%보다 심각 → -5% 는 -3% 임계도 동시 충족하므로, 더 긴 휴식 사용)

최적화:
  cooldown_3 (−3% 임계 휴식일) : 0, 5, 10, 15, 20, 25, 30, 45, 60
  cooldown_5 (−5% 임계 휴식일) : 0, 5, 10, 15, 20, 25, 30, 45, 60
  목적함수 : CAGR (세후) 최대화

결과:
  새로운 Google Spreadsheet 에 저장
  기존 운영 시트 / 앱 / 대시보드에는 영향 없음
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# ── 파라미터 ──────────────────────────────────────────────────────────────
START_DATE   = "2011-01-01"
END_DATE     = datetime.today().strftime("%Y-%m-%d")
CAPITAL      = 100_000.0
TAX_RATE     = 0.22
TAX_EXEMPT   = 1_900.0   # ~250만원 ($1,900 ≒ KRW 2,500,000 / 1,300)

# QQQ 임계값 (변경 가능)
CRASH_PCT_3  = -3.0   # % (이하이면 minor crash)
CRASH_PCT_5  = -5.0   # % (이하이면 major crash)

TICKER_CONFIG = {
    "TQQQ": {"period": 2, "buy_below": 15, "sell_above": 75,  "fear_max": 25, "greed_min": 90, "profit_target": 15.0},
    "SOXL": {"period": 2, "buy_below": 15, "sell_above": 90,  "fear_max": 25, "greed_min": 90, "profit_target": None},
}

# 최적화 탐색 범위
OPT_COOLDOWN_3 = [0, 5, 10, 15, 20, 25, 30, 45, 60]   # 0 = -3% 가드 미사용
OPT_COOLDOWN_5 = [0, 5, 10, 15, 20, 25, 30, 45, 60]   # 0 = -5% 가드 미사용


# ── 주가 다운로드 ────────────────────────────────────────────────────────

def download_close(ticker: str) -> pd.Series:
    import yfinance as yf
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"주가 데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].squeeze()
    s.index = pd.to_datetime(s.index).normalize()
    return s.sort_index().dropna()


# ── RSI(2) 핵심 함수 (production 동일 Wilder EWM) ──────────────────────

def _build_rsi_arrays(closes: np.ndarray, alpha: float):
    """Wilder EWM 방식 ma_up, ma_down, rsi 배열 반환"""
    n = len(closes)
    ma_up   = np.zeros(n)
    ma_down = np.zeros(n)
    for i in range(1, n):
        delta      = closes[i] - closes[i - 1]
        ma_up[i]   = alpha * max(delta, 0.0)  + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-delta, 0.0) + (1 - alpha) * ma_down[i - 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rs  = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[:1] = np.nan
    return ma_up, ma_down, rsi


def _solve_rsi_target_close(prev: float, mu: float, md: float,
                             target_rsi: float, alpha: float) -> float:
    """전일 EWM 상태에서 target_rsi가 되는 다음 종가를 역산 (production 동일)"""
    if mu == 0.0 and md == 0.0:
        return round(prev, 2)
    beta     = 1.0 - alpha
    r_target = target_rsi / (100.0 - target_rsi)
    x_down   = prev + (md - mu / r_target) * beta / alpha
    if x_down <= prev:
        return round(x_down, 2)
    x_up     = prev + (r_target * md - mu) * beta / alpha
    return round(x_up, 2)


def _build_next_day_limits(closes: np.ndarray, ma_up: np.ndarray, ma_down: np.ndarray,
                            buy_below: float, sell_above: float, alpha: float):
    """각 i일 상태에서 i+1일에 RSI 임계가 되는 종가 (next_buy_limits, next_sell_limits)"""
    n = len(closes)
    nbl = np.full(n, np.nan)
    nsl = np.full(n, np.nan)
    for i in range(n):
        nbl[i] = _solve_rsi_target_close(closes[i], ma_up[i], ma_down[i], buy_below,  alpha)
        nsl[i] = _solve_rsi_target_close(closes[i], ma_up[i], ma_down[i], sell_above, alpha)
    return nbl, nsl


# ── 핵심 시뮬레이션 (RSI+FnG + QQQ Crash Guard) ─────────────────────────

def simulate_with_qqq_guard(
    close:       pd.Series,   # TQQQ 또는 SOXL
    fng:         pd.Series,   # Fear & Greed Index (날짜 인덱스)
    qqq_close:   pd.Series,   # QQQ 종가 (날짜 인덱스)
    period:      int,
    buy_below:   float,
    sell_above:  float,
    fear_max:    int,
    greed_min:   int,
    cooldown_3:  int = 15,    # QQQ -3% 이하 시 매수 금지 캘린더일
    cooldown_5:  int = 30,    # QQQ -5% 이하 시 매수 금지 캘린더일
) -> tuple[pd.DataFrame, dict[int, dict]]:
    """
    production simulate_with_fng 와 동일 로직 + QQQ Crash Guard 추가.
    Returns: (df, annual_taxes)
    """
    alpha  = 1.0 / period
    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    next_buy_limits, next_sell_limits = _build_next_day_limits(
        closes, ma_up, ma_down, buy_below, sell_above, alpha
    )

    # F&G 정렬
    fng_aligned = fng.reindex(close.index, method="ffill").fillna(50).astype(int)

    # QQQ 일별 등락률 계산 (close 날짜에 맞춤)
    qqq_aligned = qqq_close.reindex(close.index, method="ffill").fillna(method="bfill")
    qqq_vals    = qqq_aligned.values.astype(float)
    qqq_chg_arr = np.full(n, 0.0)
    for i in range(1, n):
        if qqq_vals[i - 1] > 0:
            qqq_chg_arr[i] = (qqq_vals[i] / qqq_vals[i - 1] - 1.0) * 100.0

    # 상태 초기화
    cash                    = CAPITAL
    holdings                = 0.0
    cash_at_buy             = 0.0
    annual_realized_pnl     = 0.0
    annual_profit_ytd       = 0.0
    current_tax_year        = None
    total_tax_paid          = 0.0
    annual_taxes: dict[int, dict] = {}
    pending_tax             = 0.0
    pending_tax_year        = None
    pending_tax_total_before = 0.0

    # QQQ 가드 상태
    cooldown_until: datetime | None = None   # 이 날짜까지는 매수 금지

    rows: list[dict] = []

    def _apply_pending_tax():
        nonlocal cash, total_tax_paid, pending_tax, pending_tax_year
        nonlocal pending_tax_total_before, annual_profit_ytd
        if pending_tax <= 0:
            return None
        tax = pending_tax
        cash            -= tax
        total_tax_paid  += tax
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
        rsi_val  = rsi[i]
        fng_val  = int(fng_aligned.iloc[i])
        qqq_chg  = float(qqq_chg_arr[i])

        action        = "HOLD"
        fng_blocked   = ""
        trade_qty     = 0.0
        buy_cash_used = ""
        tax_today     = None

        # ── 연간 양도세 처리 (새해 첫 거래일) ────────────────────────
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
                pending_tax_year = None
            annual_realized_pnl = 0.0
            current_tax_year    = dt.year

        if i > 0:
            # ── QQQ Crash Guard 판단 ──────────────────────────────────
            guard_triggered_days = 0
            guard_reason = ""

            if cooldown_5 > 0 and qqq_chg <= CRASH_PCT_5:
                guard_triggered_days = cooldown_5
                guard_reason = f"QQQ{qqq_chg:.1f}%≤{CRASH_PCT_5}%→{cooldown_5}일"
            elif cooldown_3 > 0 and qqq_chg <= CRASH_PCT_3:
                guard_triggered_days = cooldown_3
                guard_reason = f"QQQ{qqq_chg:.1f}%≤{CRASH_PCT_3}%→{cooldown_3}일"

            if guard_triggered_days > 0:
                new_until = dt + timedelta(days=guard_triggered_days)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                # 보유 중이면 강제 매도
                if holdings > 0:
                    realized = holdings * price - cash_at_buy
                    annual_realized_pnl += realized
                    annual_profit_ytd   += realized
                    trade_qty = -holdings
                    cash     += holdings * price
                    holdings  = 0.0
                    t = _apply_pending_tax()
                    tax_today = t
                    action      = "SELL_QQQ"
                    fng_blocked = guard_reason
                else:
                    fng_blocked = guard_reason  # 현금 보유 중 쿨다운 연장

            # ── 정상 RSI+FnG 로직 ─────────────────────────────────────
            if action == "HOLD":
                prev_buy_trigger  = next_buy_limits[i - 1]
                prev_sell_trigger = next_sell_limits[i - 1]

                in_cooldown = (cooldown_until is not None and dt <= cooldown_until)

                if holdings == 0.0 and not np.isnan(prev_buy_trigger) and float(price) <= float(prev_buy_trigger):
                    if in_cooldown:
                        remaining_days = (cooldown_until - dt).days
                        fng_blocked = f"QQQ차단({remaining_days}일남음)"
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

                elif holdings > 0 and not np.isnan(prev_sell_trigger) and float(price) >= float(prev_sell_trigger):
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

        cooldown_rem = max(0, (cooldown_until - dt).days) if cooldown_until and dt <= cooldown_until else 0

        rows.append({
            "date":                    dt.strftime("%Y-%m-%d"),
            "close":                   round(float(price), 4),
            "chg_pct":                 daily_chg,
            "qqq_chg_pct":             round(qqq_chg, 2) if i > 0 else "",
            "fng":                     fng_val,
            f"rsi{period}":            round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "fng_blocked":             fng_blocked,
            "cooldown_days":           cooldown_rem if cooldown_rem > 0 else "",
            "buy_limit_expected_px":   round(float(next_buy_limits[i]),  2) if not np.isnan(next_buy_limits[i])  else "",
            "sell_limit_expected_px":  round(float(next_sell_limits[i]), 2) if not np.isnan(next_sell_limits[i]) else "",
            "action":                  action,
            "trade_qty":               round(float(trade_qty), 6),
            "buy_cash_used":           buy_cash_used,
            "holdings":                round(float(holdings), 6),
            "cash":                    round(float(cash), 2),
            "total_assets":            round(float(total_assets), 2),
            "return_pct":              round(float((total_assets / CAPITAL - 1) * 100), 4),
            "annual_profit_ytd":       round(float(annual_profit_ytd), 2),
            "tax_deducted":            "" if tax_today is None else round(float(tax_today), 2),
        })

    # ── 마지막 연도 양도세 ──────────────────────────────────────────
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if rows:
        tax_final = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
        if tax_final > 0:
            total_tax_paid += tax_final
            rows[-1]["total_assets"] = round(rows[-1]["total_assets"] - tax_final, 2)
            rows[-1]["return_pct"]   = round((rows[-1]["total_assets"] / CAPITAL - 1) * 100, 4)
            rows[-1]["annual_profit_ytd"] = 0.0
            existing = rows[-1].get("tax_deducted", "")
            existing_num = float(existing) if existing != "" else 0.0
            rows[-1]["tax_deducted"] = round(existing_num + tax_final, 2)
            annual_taxes[current_tax_year] = {
                "tax":          tax_final,
                "total_before": rows[-1]["total_assets"] + tax_final,
                "deducted_on":  rows[-1]["date"],
            }

    return pd.DataFrame(rows), annual_taxes


# ── 성과 계산 ────────────────────────────────────────────────────────────

def calc_perf(df: pd.DataFrame, annual_taxes: dict) -> dict:
    ta      = df["total_assets"].astype(float)
    final   = float(ta.iloc[-1])
    dates   = pd.to_datetime(df["date"])
    years   = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1 / 365.25)
    cagr    = ((final / CAPITAL) ** (1 / years) - 1) * 100

    peak = CAPITAL
    mdd  = 0.0
    for v in ta:
        if v > peak:
            peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd:
            mdd = dd

    # 사이클 (SELL / SELL_QQQ 기준)
    cycles, in_pos = [], False
    buy_date = buy_px = None
    buy_count = sell_count = sell_qqq_count = 0

    for _, row in df.iterrows():
        act = str(row["action"])
        if act == "BUY" and not in_pos:
            in_pos    = True
            buy_date  = row["date"]
            buy_px    = float(row["close"])
            buy_count += 1
        elif act in ("SELL", "SELL_QQQ") and in_pos:
            sell_px = float(row["close"])
            ret     = (sell_px - buy_px) / buy_px * 100 if buy_px else 0.0
            hold    = (pd.Timestamp(row["date"]) - pd.Timestamp(buy_date)).days
            cycles.append({
                "buy_date": buy_date, "sell_date": row["date"],
                "buy_px": buy_px, "sell_px": sell_px,
                "ret_pct": round(ret, 2), "hold_days": hold,
                "type": act,
            })
            if act == "SELL":
                sell_count += 1
            else:
                sell_qqq_count += 1
            in_pos = False

    rets  = [c["ret_pct"] for c in cycles]
    wins  = [r for r in rets if r > 0]
    total_tax = sum(v.get("tax", 0) for v in annual_taxes.values())
    fng_blocked_cnt = int((df["fng_blocked"].astype(str).str.startswith(("BUY차단", "SELL차단"))).sum())
    qqq_sell_cnt    = int((df["action"] == "SELL_QQQ").sum())

    return {
        "total_return_pct": round((final / CAPITAL - 1) * 100, 2),
        "cagr_pct":         round(cagr, 2),
        "mdd_pct":          round(mdd, 2),
        "final_assets":     round(final, 0),
        "buy_count":        buy_count,
        "sell_count":       sell_count,
        "sell_qqq_count":   sell_qqq_count,
        "fng_blocked":      fng_blocked_cnt,
        "cycles":           len(cycles),
        "win_rate":         round(len(wins) / len(rets) * 100, 1) if rets else 0,
        "avg_ret_pct":      round(sum(rets) / len(rets), 2) if rets else 0,
        "avg_hold_days":    round(sum(c["hold_days"] for c in cycles) / len(cycles), 1) if cycles else 0,
        "total_tax_paid":   round(total_tax, 0),
        "cycle_list":       cycles,
    }


# ── 연도별 수익률 계산 ───────────────────────────────────────────────────

def yearly_returns(df: pd.DataFrame, annual_taxes: dict) -> dict[str, float]:
    df2 = df.copy()
    df2["year"] = pd.to_datetime(df2["date"]).dt.year
    cur = datetime.now().year
    result = {}
    for yr, grp in df2.groupby("year"):
        s = float(grp.iloc[0]["total_assets"])
        e = float(grp.iloc[-1]["total_assets"])
        if yr == cur:
            e += float(annual_taxes.get(yr, {}).get("tax", 0))
        label = f"{yr}{'(진행)' if yr == cur else ''}"
        result[label] = round((e / s - 1) * 100, 2)
    return result


# ── 최적화 그리드 탐색 ───────────────────────────────────────────────────

def run_optimization(
    close: pd.Series, fng: pd.Series, qqq_close: pd.Series,
    ticker: str, cfg: dict,
) -> list[dict]:
    """
    cooldown_3 × cooldown_5 전체 조합 탐색.
    Returns 결과 리스트 (CAGR 내림차순 정렬)
    """
    total = len(OPT_COOLDOWN_3) * len(OPT_COOLDOWN_5)
    print(f"  [{ticker}] 최적화 탐색: {total}개 조합 ...")
    opt_results = []
    done = 0

    for cd3 in OPT_COOLDOWN_3:
        for cd5 in OPT_COOLDOWN_5:
            df, taxes = simulate_with_qqq_guard(
                close=close, fng=fng, qqq_close=qqq_close,
                period=cfg["period"],
                buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
                fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
                cooldown_3=cd3, cooldown_5=cd5,
            )
            perf = calc_perf(df, taxes)
            opt_results.append({
                "ticker":         ticker,
                "cooldown_3":     cd3,
                "cooldown_5":     cd5,
                "cagr_pct":       perf["cagr_pct"],
                "total_return":   perf["total_return_pct"],
                "mdd_pct":        perf["mdd_pct"],
                "final_assets":   perf["final_assets"],
                "win_rate":       perf["win_rate"],
                "cycles":         perf["cycles"],
                "sell_qqq":       perf["sell_qqq_count"],
                "total_tax":      perf["total_tax_paid"],
                "label":          f"3%→{cd3}일 / 5%→{cd5}일" if (cd3 > 0 or cd5 > 0) else "No Guard (기준선)",
            })
            done += 1
            if done % 20 == 0:
                print(f"    진행: {done}/{total}")

    opt_results.sort(key=lambda x: x["cagr_pct"], reverse=True)
    return opt_results


# ── Google Sheet 저장 ─────────────────────────────────────────────────────

def write_to_new_sheet(
    best_results:  dict[str, tuple[pd.DataFrame, dict, dict, int, int]],
    opt_all:       dict[str, list[dict]],
    baseline:      dict[str, dict],
):
    """
    새 Google Spreadsheet 생성 후 결과 저장.
    best_results[ticker] = (df, annual_taxes, perf, best_cd3, best_cd5)
    """
    from sheets_manager import SheetsManager
    from _env_loader import get_spreadsheet_id

    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc = sm._get_client()

    title = f"QQQ_CrashGuard_Backtest_{START_DATE[:4]}_{END_DATE[:4]}"
    print(f"\n[GoogleSheets] 새 스프레드시트 생성: {title}")
    ss  = gc.create(title)
    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    # ── 1. Summary 탭 ───────────────────────────────────────────────
    ws = ss.sheet1
    ws.update_title("Summary")

    rows = [
        [f"QQQ Crash Guard 백테스트  {START_DATE} ~ {END_DATE}  초기자본: ${CAPITAL:,.0f}"],
        [f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기본 알고리즘: RSI(2)+F&G  (TQQQ buy<15/sell>75  SOXL buy<15/sell>90  fear≤25/greed≥90)"],
        [f"QQQ 임계: {CRASH_PCT_3}% → cooldown_3일 매수금지 | {CRASH_PCT_5}% → cooldown_5일 매수금지"],
        [],
        ["[ 최적 파라미터 요약 ]"],
        ["종목", "최적 -3%쿨다운(일)", "최적 -5%쿨다운(일)",
         "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)",
         "승률(%)", "사이클수", "QQQ강제매도", "양도세($)"],
    ]
    for ticker, (df, taxes, perf, cd3, cd5) in best_results.items():
        rows.append([
            ticker, cd3, cd5,
            perf["total_return_pct"], perf["cagr_pct"], perf["mdd_pct"],
            perf["final_assets"], perf["win_rate"], perf["cycles"],
            perf["sell_qqq_count"], perf["total_tax_paid"],
        ])
    rows.append([])

    # 기준선 (No Guard)
    rows.append(["[ 기준선: QQQ 가드 없음 (RSI+F&G 단독) ]"])
    rows.append(["종목", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "승률(%)", "사이클수", "양도세($)"])
    for ticker, p in baseline.items():
        rows.append([
            ticker,
            p["total_return_pct"], p["cagr_pct"], p["mdd_pct"],
            p["final_assets"], p["win_rate"], p["cycles"], p["total_tax_paid"],
        ])
    rows.append([])

    # 연도별 수익률
    rows.append(["[ 연도별 수익률 (최적 파라미터 기준) ]"])
    year_labels: list[str] = []
    yearly_all:  dict[str, dict] = {}
    for ticker, (df, taxes, perf, cd3, cd5) in best_results.items():
        yr_dict = yearly_returns(df, taxes)
        yearly_all[ticker] = yr_dict
        for y in yr_dict:
            if y not in year_labels:
                year_labels.append(y)
    year_labels.sort()
    rows.append(["종목"] + year_labels)
    for ticker in best_results:
        rows.append([ticker] + [yearly_all[ticker].get(y, "") for y in year_labels])
    rows.append([])

    max_cols = max((len(r) for r in rows if r), default=1)
    col_letter = chr(64 + max_cols) if max_cols <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}{len(rows)}", values=rows)
    print("[GoogleSheets] Summary 저장 완료")

    # ── 2. 최적화 결과 탭 (각 종목) ────────────────────────────────
    for ticker, opt_list in opt_all.items():
        title_tab = f"{ticker}_최적화"
        ws_opt = ss.add_worksheet(title=title_tab, rows=max(200, len(opt_list) + 10), cols=15)

        hdr = ["순위", "라벨", "-3%쿨다운(일)", "-5%쿨다운(일)",
               "CAGR(%)", "총수익률(%)", "MDD(%)", "최종자산($)",
               "승률(%)", "사이클수", "QQQ강제매도", "양도세($)"]
        meta = [
            [f"{ticker}  QQQ Crash Guard 최적화 결과  {START_DATE} ~ {END_DATE}"],
            [f"CAGR 내림차순 정렬 | 기준선(No Guard) 포함"],
            [],
            hdr,
        ]
        data_rows = []
        for rank, r in enumerate(opt_list, 1):
            data_rows.append([
                rank, r["label"], r["cooldown_3"], r["cooldown_5"],
                r["cagr_pct"], r["total_return"], r["mdd_pct"],
                r["final_assets"], r["win_rate"], r["cycles"],
                r["sell_qqq"], r["total_tax"],
            ])
        col_l = chr(64 + len(hdr))
        ws_opt.update(range_name=f"A1:{col_l}{len(meta)}", values=meta)
        ws_opt.update(range_name=f"A{len(meta)+1}:{col_l}{len(meta)+len(data_rows)}", values=data_rows)
        print(f"[GoogleSheets] {title_tab} 저장 완료")

    # ── 3. 종목별 일별 상세 탭 ─────────────────────────────────────
    day_headers = [
        "date", "close", "chg_pct", "qqq_chg_pct", "fng", "rsi2",
        "fng_blocked", "cooldown_days",
        "buy_limit_expected_px", "sell_limit_expected_px",
        "action", "trade_qty", "buy_cash_used", "holdings",
        "cash", "total_assets", "return_pct", "annual_profit_ytd", "tax_deducted",
    ]
    for ticker, (df, taxes, perf, cd3, cd5) in best_results.items():
        tab_title = f"{ticker}_일별(최적)"
        ws_day = ss.add_worksheet(title=tab_title, rows=max(5000, len(df) + 10), cols=len(day_headers) + 2)
        meta = [
            [f"{ticker}  QQQ Crash Guard  최적: -3%→{cd3}일 / -5%→{cd5}일  {START_DATE}~{END_DATE}"],
            [f"총수익률: {perf['total_return_pct']}%  CAGR: {perf['cagr_pct']}%  MDD: {perf['mdd_pct']}%  최종: ${perf['final_assets']:,}"],
            [f"사이클: {perf['cycles']}회  승률: {perf['win_rate']}%  QQQ강제매도: {perf['sell_qqq_count']}회  양도세: ${perf['total_tax_paid']:,}"],
            [f"※ F&G 데이터 2011~2020 구간은 중립(50) 적용"],
            day_headers,
        ]
        data_rows = [[str(row.get(h, "")) for h in day_headers] for _, row in df.iterrows()]
        col_l = chr(64 + len(day_headers))
        ws_day.update(range_name=f"A1:{col_l}{len(meta)}", values=meta)
        if data_rows:
            ws_day.update(range_name=f"A{len(meta)+1}:{col_l}{len(meta)+len(data_rows)}", values=data_rows)
        print(f"[GoogleSheets] {tab_title} 저장 완료 ({len(df)}행)")

    # ── 4. 최적화 히트맵 탭 (cooldown_3 × cooldown_5 격자) ─────────
    for ticker, opt_list in opt_all.items():
        tab_title = f"{ticker}_히트맵"
        ws_hm = ss.add_worksheet(title=tab_title, rows=20, cols=20)

        # Pivot: rows = cooldown_3, cols = cooldown_5, values = CAGR
        cagr_grid: dict[int, dict[int, float]] = {}
        for r in opt_list:
            cd3, cd5, cagr = r["cooldown_3"], r["cooldown_5"], r["cagr_pct"]
            cagr_grid.setdefault(cd3, {})[cd5] = cagr

        hm_rows = [[f"{ticker} CAGR(%) 격자: 행=−3%쿨다운일 / 열=−5%쿨다운일"]]
        hm_rows.append(["\\−3%↓ −5%→"] + [str(c) for c in OPT_COOLDOWN_5])
        for cd3 in OPT_COOLDOWN_3:
            row = [str(cd3)] + [str(cagr_grid.get(cd3, {}).get(cd5, "")) for cd5 in OPT_COOLDOWN_5]
            hm_rows.append(row)

        col_l = chr(64 + len(OPT_COOLDOWN_5) + 1)
        ws_hm.update(range_name=f"A1:{col_l}{len(hm_rows)}", values=hm_rows)
        print(f"[GoogleSheets] {tab_title} 저장 완료")

    return url, ss.id


# ── main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 75)
    print(f"QQQ Crash Guard 백테스트  {START_DATE} ~ {END_DATE}")
    print(f"알고리즘: RSI(2)+F&G + QQQ 낙폭 감시 ({CRASH_PCT_3}% / {CRASH_PCT_5}%)")
    print("=" * 75)

    # F&G 데이터
    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
        print(f"F&G: {fng_base.index.min().date()} ~ {fng_base.index.max().date()} (이전 구간 50 적용)")
    except Exception as e:
        print(f"F&G 로드 실패: {e} → 전 기간 F&G=50")
        fng_base = pd.Series(dtype=float)

    # QQQ 다운로드
    print("\n[QQQ] 가격 데이터 다운로드...")
    qqq_close = download_close("QQQ")
    print(f"[QQQ] {len(qqq_close)}일 ({qqq_close.index[0].date()} ~ {qqq_close.index[-1].date()})")

    best_results: dict[str, tuple] = {}
    opt_all:      dict[str, list]  = {}
    baseline:     dict[str, dict]  = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n{'='*60}")
        print(f"[{ticker}] 가격 데이터 다운로드...")
        close = download_close(ticker)
        print(f"[{ticker}] {len(close)}일 ({close.index[0].date()} ~ {close.index[-1].date()})")
        fng = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        # 기준선 (No Guard)
        df_base, taxes_base = simulate_with_qqq_guard(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
            fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
            cooldown_3=0, cooldown_5=0,
        )
        baseline[ticker] = calc_perf(df_base, taxes_base)
        print(f"  [기준선] CAGR {baseline[ticker]['cagr_pct']:.1f}%  MDD {baseline[ticker]['mdd_pct']:.1f}%  총수익 {baseline[ticker]['total_return_pct']:.1f}%")

        # 최적화
        opt_list = run_optimization(close, fng, qqq_close, ticker, cfg)
        opt_all[ticker] = opt_list

        best = opt_list[0]
        best_cd3 = best["cooldown_3"]
        best_cd5 = best["cooldown_5"]
        print(f"\n  [{ticker}] 최적: -3%→{best_cd3}일 / -5%→{best_cd5}일")
        print(f"    CAGR {best['cagr_pct']:.1f}%  (기준선 {baseline[ticker]['cagr_pct']:.1f}%  "
              f"차이: {best['cagr_pct']-baseline[ticker]['cagr_pct']:+.1f}%p)")
        print(f"    MDD  {best['mdd_pct']:.1f}%  (기준선 {baseline[ticker]['mdd_pct']:.1f}%)")
        print(f"    사이클 {best['cycles']}회  QQQ강제매도 {best['sell_qqq']}회")

        # 최적 파라미터로 상세 시뮬레이션
        df_best, taxes_best = simulate_with_qqq_guard(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
            fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
            cooldown_3=best_cd3, cooldown_5=best_cd5,
        )
        perf_best = calc_perf(df_best, taxes_best)
        best_results[ticker] = (df_best, taxes_best, perf_best, best_cd3, best_cd5)

        # 연도별 수익률 출력 (최적 기준)
        yr_dict = yearly_returns(df_best, taxes_best)
        print(f"  연도별 수익률 (최적):")
        for yr_label, pct in sorted(yr_dict.items()):
            bar  = "█" * min(int(abs(pct) / 5), 20)
            sign = "+" if pct >= 0 else ""
            print(f"    {yr_label}: {sign}{pct:.1f}% {bar}")

        # Top 5 최적화 결과 출력
        print(f"\n  Top 5 파라미터 (CAGR 기준):")
        for i, r in enumerate(opt_list[:5], 1):
            vs_base = r["cagr_pct"] - baseline[ticker]["cagr_pct"]
            print(f"    #{i}  {r['label']:30s}  CAGR {r['cagr_pct']:.1f}%  "
                  f"({vs_base:+.1f}%p vs 기준)  MDD {r['mdd_pct']:.1f}%  "
                  f"QQQ매도 {r['sell_qqq']}회")

    # Google Sheets 저장
    print("\n" + "=" * 75)
    print("Google Sheet 저장 중...")
    url, sheet_id = write_to_new_sheet(best_results, opt_all, baseline)

    print("\n" + "=" * 75)
    print("[ 최종 결과 요약 ]")
    print(f"기간: {START_DATE} ~ {END_DATE}   초기자본: ${CAPITAL:,.0f}")
    print()
    for ticker in TICKER_CONFIG:
        _, _, perf, cd3, cd5 = best_results[ticker]
        bl = baseline[ticker]
        print(f"{ticker}:")
        print(f"  기준선: CAGR {bl['cagr_pct']:.1f}%  MDD {bl['mdd_pct']:.1f}%  최종 ${bl['final_assets']:,.0f}")
        print(f"  최적  : CAGR {perf['cagr_pct']:.1f}%  MDD {perf['mdd_pct']:.1f}%  최종 ${perf['final_assets']:,.0f}")
        print(f"  파라미터: QQQ -3%→{cd3}일  QQQ -5%→{cd5}일  QQQ강제매도 {perf['sell_qqq_count']}회")
    print()
    print(f"Google Sheet: {url}")
    print("=" * 75)


if __name__ == "__main__":
    main()
