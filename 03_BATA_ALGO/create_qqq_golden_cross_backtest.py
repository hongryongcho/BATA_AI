"""
TQQQ / SOXL  QQQ 골든크로스 매도지연 변형 백테스트  (2011-01-01 ~ 오늘)
─────────────────────────────────────────────────────────────────────────
Base 알고리즘:  RSI(2) + Fear&Greed + QQQ Crash Guard (-5%→10일)  ← 프로덕션과 동일
GC 변형  :      Base + QQQ MA50 > MA200 (골든크로스) 구간에서
                RSI SELL 신호 발생 시 → +5일 지연 후 RSI 재확인 (사이클당 1회만)

결과: 새 Google Spreadsheet에 두 알고리즘 비교 저장
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
START_DATE       = "2011-01-01"
END_DATE         = datetime.today().strftime("%Y-%m-%d")
CAPITAL          = 100_000.0
TAX_RATE         = 0.22
TAX_EXEMPT       = 1_900.0      # ~250만원 ($1,900 ≒ KRW 2,500,000 / 1,300)

# 프로덕션과 동일한 QQQ Crash Guard 파라미터
QQQ_CRASH_PCT    = -5.0
QQQ_COOLDOWN     = 10           # 캘린더일

# QQQ 골든크로스 이평선
GC_MA_FAST       = 50
GC_MA_SLOW       = 200

# GC 지연 일수 (사이클당 1회)
GC_DELAY_DAYS    = 12

TICKER_CONFIG = {
    "TQQQ": {"period": 2, "buy_below": 15, "sell_above": 75,  "fear_max": 25, "greed_min": 90},
    "SOXL": {"period": 2, "buy_below": 15, "sell_above": 90,  "fear_max": 25, "greed_min": 90},
}


# ── 주가 다운로드 ─────────────────────────────────────────────────────────

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


# ── RSI(2) (Wilder EWM, 프로덕션 동일) ───────────────────────────────────

def _build_rsi_arrays(closes: np.ndarray, alpha: float):
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
    if mu == 0.0 and md == 0.0:
        return round(prev, 2)
    beta     = 1.0 - alpha
    r_target = target_rsi / (100.0 - target_rsi)
    x_down   = prev + (md - mu / r_target) * beta / alpha
    if x_down <= prev:
        return round(x_down, 2)
    x_up = prev + (r_target * md - mu) * beta / alpha
    return round(x_up, 2)


def _build_next_day_limits(closes: np.ndarray, ma_up: np.ndarray, ma_down: np.ndarray,
                            buy_below: float, sell_above: float, alpha: float):
    n   = len(closes)
    nbl = np.full(n, np.nan)
    nsl = np.full(n, np.nan)
    for i in range(n):
        nbl[i] = _solve_rsi_target_close(closes[i], ma_up[i], ma_down[i], buy_below,  alpha)
        nsl[i] = _solve_rsi_target_close(closes[i], ma_up[i], ma_down[i], sell_above, alpha)
    return nbl, nsl


# ── 핵심 시뮬레이션 ───────────────────────────────────────────────────────

def simulate(
    close:         pd.Series,
    fng:           pd.Series,
    qqq_close:     pd.Series,
    period:        int,
    buy_below:     float,
    sell_above:    float,
    fear_max:      int,
    greed_min:     int,
    qqq_gc:        pd.Series | None = None,  # None → Base, Series(bool) → GC 변형
    gc_delay_days: int | None = GC_DELAY_DAYS,
) -> tuple[pd.DataFrame, dict[int, dict]]:
    """
    Base 모드 (qqq_gc=None):
        RSI(2) + F&G + QQQ Crash Guard

    GC 변형 (qqq_gc=Series):
        Base + GC구간에서 RSI SELL 신호 발생 시
        → +gc_delay_days일 지연 후 RSI 재확인 (사이클당 1회)
        → 재확인 시 SELL 조건 충족이면 매도, 아니면 해제 후 정상 거래 재개
    """
    alpha  = 1.0 / period
    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    next_buy_limits, next_sell_limits = _build_next_day_limits(
        closes, ma_up, ma_down, buy_below, sell_above, alpha
    )

    fng_aligned = fng.reindex(close.index, method="ffill").fillna(50).astype(int)

    qqq_aligned = qqq_close.reindex(close.index, method="ffill").ffill().bfill()
    qqq_vals    = qqq_aligned.values.astype(float)
    qqq_chg_arr = np.full(n, 0.0)
    for i in range(1, n):
        if qqq_vals[i - 1] > 0:
            qqq_chg_arr[i] = (qqq_vals[i] / qqq_vals[i - 1] - 1.0) * 100.0

    if qqq_gc is not None:
        gc_aligned = qqq_gc.reindex(close.index, method="ffill").fillna(False)
        gc_arr     = gc_aligned.values.astype(bool)
    else:
        gc_arr = np.zeros(n, dtype=bool)

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
    cooldown_until: datetime | None = None

    # GC 지연 상태 (사이클당 1회)
    gc_delay_until: datetime | None = None  # 이 날 이후 재검토
    gc_delay_used: bool = False             # 이 사이클에서 이미 사용했나
    gc_started_during_hold: bool = False    # 보유중 GC가 새로 발생(전환)했는지

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

    def _do_sell(price_val: float):
        nonlocal holdings, cash, annual_realized_pnl, annual_profit_ytd
        realized = holdings * price_val - cash_at_buy
        annual_realized_pnl += realized
        annual_profit_ytd   += realized
        qty   = -holdings
        cash += holdings * price_val
        holdings = 0.0
        return qty, _apply_pending_tax()

    for i, (dt, price) in enumerate(close.items()):
        rsi_val = rsi[i]
        fng_val = int(fng_aligned.iloc[i])
        qqq_chg = float(qqq_chg_arr[i])
        gc_on   = bool(gc_arr[i])

        action        = "HOLD"
        fng_blocked   = ""
        trade_qty     = 0.0
        buy_cash_used = ""
        tax_today     = None

        # GC 지연 대기 중 표시 (만료 전)
        if gc_delay_until is not None and dt < gc_delay_until and holdings > 0:
            remaining_gc = (gc_delay_until - dt).days
            fng_blocked = f"GC지연대기({remaining_gc}일→{gc_delay_until.strftime('%m/%d')})"

        # ── 연간 양도세 처리 ─────────────────────────────────────────
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
            # ── 보유중 GC 신규 발생 감지 (non-GC → GC 전환) ─────────
            if holdings > 0 and gc_arr[i] and not gc_arr[i - 1]:
                gc_started_during_hold = True

            # ── [1] QQQ Crash Guard (항상 우선) ──────────────────────
            if qqq_chg <= QQQ_CRASH_PCT:
                new_until = dt + timedelta(days=QQQ_COOLDOWN)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                if holdings > 0:
                    trade_qty, t = _do_sell(float(price))
                    tax_today    = t
                    action       = "SELL_QQQ"
                    fng_blocked  = f"QQQ{qqq_chg:.1f}%≤-5%→{QQQ_COOLDOWN}일"
                    # GC 지연 초기화 (강제매도로 사이클 종료)
                    gc_delay_until         = None
                    gc_delay_used          = False
                    gc_started_during_hold = False
                else:
                    fng_blocked = f"QQQ{qqq_chg:.1f}%≤-5%(쿨다운연장)"

            # ── [2] GC 지연 만료 재검토 ──────────────────────────────
            if action == "HOLD" and gc_delay_until is not None and dt >= gc_delay_until and holdings > 0:
                prev_sell_trigger = next_sell_limits[i - 1]
                if not np.isnan(prev_sell_trigger) and float(price) >= float(prev_sell_trigger):
                    # RSI 여전히 매도 영역 → 매도 실행
                    trade_qty, t = _do_sell(float(price))
                    tax_today    = t
                    action       = "SELL"
                    fng_blocked  = f"GC지연후매도(RSI≥{sell_above})"
                else:
                    # RSI 조건 미충족 → 지연 해제, 정상 거래 재개
                    fng_blocked  = f"GC지연해제(RSI<{sell_above})"
                gc_delay_until = None  # 만료 처리

            # ── [3] 정상 RSI+FnG 로직 (GC 지연 대기 중 아닐 때만) ───
            if action == "HOLD" and gc_delay_until is None:
                prev_buy_trigger  = next_buy_limits[i - 1]
                prev_sell_trigger = next_sell_limits[i - 1]
                in_cooldown = (cooldown_until is not None and dt <= cooldown_until)

                if holdings == 0.0 and not np.isnan(prev_buy_trigger) and float(price) <= float(prev_buy_trigger):
                    if in_cooldown:
                        remaining = (cooldown_until - dt).days
                        fng_blocked = f"QQQ차단({remaining}일남음)"
                    elif fng_val >= greed_min:
                        fng_blocked = f"BUY차단(F&G={fng_val}≥{greed_min})"
                    else:
                        t = _apply_pending_tax()
                        tax_today     = t
                        cash_at_buy   = cash
                        buy_cash_used = round(float(cash), 2)
                        bought        = cash / float(price)
                        holdings      = bought
                        cash          = 0.0
                        trade_qty     = bought
                        action        = "BUY"
                        # 사이클 시작 → GC 지연 상태 초기화
                        gc_delay_until         = None
                        gc_delay_used          = False
                        gc_started_during_hold = False

                elif holdings > 0 and not np.isnan(prev_sell_trigger) and float(price) >= float(prev_sell_trigger):
                    if fng_val <= fear_max:
                        fng_blocked = f"SELL차단(F&G={fng_val}≤{fear_max})"
                    elif (gc_on and gc_started_during_hold
                          and qqq_gc is not None and gc_delay_days is not None
                          and not gc_delay_used):
                        # 보유중 GC 신규발생 + 현재 GC 상태 + 사이클 내 첫 번째 지연
                        gc_delay_until = dt + timedelta(days=gc_delay_days)
                        gc_delay_used  = True
                        fng_blocked    = f"SELL지연(GC+{gc_delay_days}일→{gc_delay_until.strftime('%m/%d')})"
                    else:
                        # GC 아님 or 이미 지연 사용 → 정상 매도
                        trade_qty, t = _do_sell(float(price))
                        tax_today    = t
                        action       = "SELL"

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
            f"rsi{period}":           round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "gc_on":                  "Y" if gc_on else "",
            "fng_blocked":            fng_blocked,
            "cooldown_days":          cd_rem if cd_rem > 0 else "",
            "buy_limit_expected_px":  round(float(next_buy_limits[i]),  2) if not np.isnan(next_buy_limits[i])  else "",
            "sell_limit_expected_px": round(float(next_sell_limits[i]), 2) if not np.isnan(next_sell_limits[i]) else "",
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

    # ── 마지막 연도 양도세 ──────────────────────────────────────────
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if rows:
        tax_final = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
        if tax_final > 0:
            total_tax_paid += tax_final
            rows[-1]["total_assets"] = round(rows[-1]["total_assets"] - tax_final, 2)
            rows[-1]["return_pct"]   = round((rows[-1]["total_assets"] / CAPITAL - 1) * 100, 4)
            rows[-1]["annual_profit_ytd"] = 0.0
            existing     = rows[-1].get("tax_deducted", "")
            existing_num = float(existing) if existing != "" else 0.0
            rows[-1]["tax_deducted"] = round(existing_num + tax_final, 2)
            annual_taxes[current_tax_year] = {
                "tax":          tax_final,
                "total_before": rows[-1]["total_assets"] + tax_final,
                "deducted_on":  rows[-1]["date"],
            }

    return pd.DataFrame(rows), annual_taxes


# ── 성과 계산 ─────────────────────────────────────────────────────────────

def calc_perf(df: pd.DataFrame, annual_taxes: dict) -> dict:
    ta    = df["total_assets"].astype(float)
    final = float(ta.iloc[-1])
    dates = pd.to_datetime(df["date"])
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1 / 365.25)
    cagr  = ((final / CAPITAL) ** (1 / years) - 1) * 100

    peak = CAPITAL
    mdd  = 0.0
    for v in ta:
        if v > peak:
            peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd:
            mdd = dd

    cycles, in_pos = [], False
    buy_date = buy_px = None
    buy_count = sell_count = sell_qqq_count = 0
    gc_delay_initiated = 0
    gc_delay_executed  = 0

    for _, row in df.iterrows():
        act     = str(row["action"])
        blocked = str(row.get("fng_blocked", ""))
        if "SELL지연(GC" in blocked:
            gc_delay_initiated += 1
        if "GC지연후매도" in blocked:
            gc_delay_executed  += 1
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

    return {
        "total_return_pct":   round((final / CAPITAL - 1) * 100, 2),
        "cagr_pct":           round(cagr, 2),
        "mdd_pct":            round(mdd, 2),
        "final_assets":       round(final, 0),
        "buy_count":          buy_count,
        "sell_count":         sell_count,
        "sell_qqq_count":     sell_qqq_count,
        "gc_delay_initiated": gc_delay_initiated,
        "gc_delay_executed":  gc_delay_executed,
        "cycles":             len(cycles),
        "win_rate":           round(len(wins) / len(rets) * 100, 1) if rets else 0,
        "avg_ret_pct":        round(sum(rets) / len(rets), 2) if rets else 0,
        "avg_hold_days":      round(sum(c["hold_days"] for c in cycles) / len(cycles), 1) if cycles else 0,
        "total_tax_paid":     round(total_tax, 0),
        "cycle_list":         cycles,
    }


# ── 연도별 수익률 ─────────────────────────────────────────────────────────

def yearly_returns(df: pd.DataFrame, annual_taxes: dict) -> dict[str, float]:
    df2 = df.copy()
    df2["year"] = pd.to_datetime(df2["date"]).dt.year
    cur    = datetime.now().year
    result = {}
    for yr, grp in df2.groupby("year"):
        if "tax_deducted" in grp.columns:
            tax_mask = grp["tax_deducted"].apply(
                lambda x: float(x) > 0 if str(x) not in ("", "nan") else False
            )
            first_tax_rows = grp[tax_mask]
        else:
            first_tax_rows = pd.DataFrame()

        if not first_tax_rows.empty:
            s = float(first_tax_rows.iloc[0]["total_assets"])
        else:
            s = float(grp.iloc[0]["total_assets"])
        if s <= 0:
            s = CAPITAL

        e = float(grp.iloc[-1]["total_assets"])
        if yr == cur:
            last_tax = grp.iloc[-1].get("tax_deducted", "")
            last_tax_num = float(last_tax) if str(last_tax) not in ("", "nan") else 0.0
            if last_tax_num > 0:
                e += last_tax_num

        label = f"{yr}{'(진행중)' if yr == cur else ''}"
        result[label] = round((e / s - 1) * 100, 2)
    return result


# ── QQQ 골든크로스 시리즈 계산 ───────────────────────────────────────────

def compute_qqq_gc(qqq_close: pd.Series) -> pd.Series:
    ma_fast = qqq_close.rolling(GC_MA_FAST,  min_periods=GC_MA_FAST).mean()
    ma_slow = qqq_close.rolling(GC_MA_SLOW, min_periods=GC_MA_SLOW).mean()
    gc = (ma_fast > ma_slow).fillna(False)
    total_days = len(qqq_close)
    gc_days    = int(gc.sum())
    print(f"[QQQ GC] MA{GC_MA_FAST}>MA{GC_MA_SLOW}: {gc_days}일/{total_days}일 ({gc_days/total_days*100:.1f}%) GC상태")
    gc_starts = int(((gc) & (~gc.shift(1, fill_value=False))).sum())
    print(f"  GC 에피소드: {gc_starts}회  평균 {gc_days/max(gc_starts,1):.0f}일 지속")
    return gc


# ── Google Sheet 저장 ─────────────────────────────────────────────────────

def write_to_new_sheet(
    results_base: dict[str, tuple[pd.DataFrame, dict, dict]],
    results_gc:   dict[str, tuple[pd.DataFrame, dict, dict]],
    qqq_gc_stats: dict,
):
    from sheets_manager import SheetsManager
    from _env_loader import get_spreadsheet_id

    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc_client = sm._get_client()

    title = f"QQQ_GoldenCross_Backtest_{START_DATE[:4]}_{END_DATE[:4]}"
    print(f"\n[GoogleSheets] 새 스프레드시트 생성: {title}")
    ss  = gc_client.create(title)
    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    # ── 1. 비교요약 탭 ───────────────────────────────────────────────
    ws = ss.sheet1
    ws.update_title("비교요약")

    rows: list[list] = [
        [f"QQQ 골든크로스 매도지연 변형  백테스트  {START_DATE} ~ {END_DATE}  초기자본: ${CAPITAL:,.0f}"],
        [f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"Base  : RSI(2)+F&G + QQQ Crash Guard ({QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일)  ← 현재 프로덕션"],
        [f"GC변형: Base + QQQ MA{GC_MA_FAST}>MA{GC_MA_SLOW} 골든크로스 구간에서 RSI SELL 발생 시 "
         f"+{GC_DELAY_DAYS}일 지연 후 RSI 재확인 (사이클당 1회)"],
        [f"알고리즘: TQQQ buy<15/sell>75  SOXL buy<15/sell>90  F&G fear≤25/greed≥90"],
        [],
        ["[ 성과 비교 요약 ]"],
        ["종목", "알고리즘", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)",
         "사이클수", "승률(%)", "평균수익률(%)", "평균보유일",
         f"GC지연발생", "GC지연후매도", "QQQ강제매도", "양도세($)"],
    ]

    for ticker in TICKER_CONFIG:
        df_b, taxes_b, perf_b = results_base[ticker]
        df_g, taxes_g, perf_g = results_gc[ticker]
        for label, perf in [("Base (프로덕션)", perf_b), (f"GC변형 (+{GC_DELAY_DAYS}일지연)", perf_g)]:
            rows.append([
                ticker, label,
                perf["total_return_pct"], perf["cagr_pct"], perf["mdd_pct"],
                perf["final_assets"], perf["cycles"], perf["win_rate"],
                perf["avg_ret_pct"], perf["avg_hold_days"],
                perf.get("gc_delay_initiated", 0),
                perf.get("gc_delay_executed",  0),
                perf["sell_qqq_count"], perf["total_tax_paid"],
            ])
        rows.append([
            ticker, f"▲ 차이 (GC - Base)",
            round(perf_g["total_return_pct"] - perf_b["total_return_pct"], 2),
            round(perf_g["cagr_pct"] - perf_b["cagr_pct"], 2),
            round(perf_g["mdd_pct"] - perf_b["mdd_pct"], 2),
            round(perf_g["final_assets"] - perf_b["final_assets"], 0),
            perf_g["cycles"] - perf_b["cycles"],
            round(perf_g["win_rate"] - perf_b["win_rate"], 1),
            round(perf_g["avg_ret_pct"] - perf_b["avg_ret_pct"], 2),
            round(perf_g["avg_hold_days"] - perf_b["avg_hold_days"], 1),
            "", "", "", "",
        ])
        rows.append([])

    # QQQ GC 통계
    rows.append([f"[ QQQ 골든크로스 구간 통계: MA{GC_MA_FAST}>MA{GC_MA_SLOW} ]"])
    rows.append(["총거래일", "GC구간일수", "GC구간비율(%)", "GC에피소드수", "GC평균지속(일)"])
    rows.append([
        qqq_gc_stats["total_days"], qqq_gc_stats["gc_days"],
        qqq_gc_stats["gc_pct"], qqq_gc_stats["gc_episodes"], qqq_gc_stats["avg_gc_days"],
    ])
    rows.append([])

    # 연도별 수익률 비교
    rows.append(["[ 연도별 수익률 비교 ]"])
    year_labels: list[str] = []
    yearly_base: dict[str, dict] = {}
    yearly_gc:   dict[str, dict] = {}

    for ticker in TICKER_CONFIG:
        df_b, taxes_b, _ = results_base[ticker]
        df_g, taxes_g, _ = results_gc[ticker]
        yb = yearly_returns(df_b, taxes_b)
        yg = yearly_returns(df_g, taxes_g)
        yearly_base[ticker] = yb
        yearly_gc[ticker]   = yg
        for y in list(yb.keys()) + list(yg.keys()):
            if y not in year_labels:
                year_labels.append(y)

    year_labels.sort()
    rows.append(["종목", "알고리즘"] + year_labels)
    for ticker in TICKER_CONFIG:
        rows.append([ticker, "Base"] + [yearly_base[ticker].get(y, "") for y in year_labels])
        rows.append([ticker, f"GC변형"] + [yearly_gc[ticker].get(y, "") for y in year_labels])
        rows.append([ticker, "차이(GC-Base)"] + [
            round(yearly_gc[ticker].get(y, 0) - yearly_base[ticker].get(y, 0), 2)
            if (yearly_base[ticker].get(y) is not None and yearly_gc[ticker].get(y) is not None)
            else ""
            for y in year_labels
        ])
        rows.append([])

    max_cols   = max((len(r) for r in rows if r), default=1)
    col_letter = _col_letter(max_cols)
    ws.update(range_name=f"A1:{col_letter}{len(rows)}", values=rows)
    print("[GoogleSheets] 비교요약 저장 완료")

    # ── 2. 종목별 Base / GC 일별 탭 ─────────────────────────────────
    day_headers = [
        "date", "close", "chg_pct", "qqq_chg_pct", "fng", "rsi2",
        "gc_on", "fng_blocked", "cooldown_days",
        "buy_limit_expected_px", "sell_limit_expected_px",
        "action", "trade_qty", "buy_cash_used", "holdings",
        "cash", "total_assets", "return_pct", "annual_profit_ytd", "tax_deducted",
    ]

    for ticker in TICKER_CONFIG:
        for label, (df, taxes, perf) in [
            ("Base",  results_base[ticker]),
            ("GC변형", results_gc[ticker]),
        ]:
            tab_title = f"{ticker}_{label}_일별"
            ws_day = ss.add_worksheet(
                title=tab_title,
                rows=max(5000, len(df) + 10),
                cols=len(day_headers) + 2,
            )
            gc_line = (
                f"  GC지연발생: {perf['gc_delay_initiated']}회  "
                f"GC지연후매도: {perf['gc_delay_executed']}회"
                if label != "Base" else ""
            )
            meta = [
                [f"{ticker}  [{label}]  {START_DATE} ~ {END_DATE}"],
                [f"총수익률: {perf['total_return_pct']}%  CAGR: {perf['cagr_pct']}%  "
                 f"MDD: {perf['mdd_pct']}%  최종: ${perf['final_assets']:,}"],
                [f"사이클: {perf['cycles']}회  승률: {perf['win_rate']}%  "
                 f"평균보유: {perf['avg_hold_days']}일  "
                 f"QQQ강제매도: {perf['sell_qqq_count']}회{gc_line}  양도세: ${perf['total_tax_paid']:,}"],
                ["※ F&G 데이터 2011~2020 구간은 중립(50) 적용"],
                day_headers,
            ]
            data_rows = [[str(row.get(h, "")) for h in day_headers] for _, row in df.iterrows()]
            col_l = _col_letter(len(day_headers))
            ws_day.update(range_name=f"A1:{col_l}{len(meta)}", values=meta)
            if data_rows:
                ws_day.update(
                    range_name=f"A{len(meta)+1}:{col_l}{len(meta)+len(data_rows)}",
                    values=data_rows,
                )
            print(f"[GoogleSheets] {tab_title} 저장 완료 ({len(df)}행)")

    # ── 3. GC 지연 이벤트 목록 탭 ────────────────────────────────────
    for ticker in TICKER_CONFIG:
        df_g, _, perf_g = results_gc[ticker]
        gc_rows = df_g[df_g["fng_blocked"].astype(str).str.contains("GC지연|GC지연후", na=False)]
        if gc_rows.empty:
            continue
        tab_title = f"{ticker}_GC지연이벤트"
        ws_gc = ss.add_worksheet(title=tab_title, rows=max(500, len(gc_rows) + 10), cols=10)
        hdr = ["date", "close", "rsi2", "gc_on", "fng", "fng_blocked",
               "sell_limit_expected_px", "holdings", "total_assets", "action"]
        meta = [
            [f"{ticker}  GC 지연 이벤트 목록  (지연발생 {perf_g['gc_delay_initiated']}회 / 지연후매도 {perf_g['gc_delay_executed']}회)"],
            [f"SELL지연: GC구간에서 RSI SELL 발생 시 +{GC_DELAY_DAYS}일 지연 설정 (사이클당 1회)"],
            [f"GC지연대기: 대기중인 날  |  GC지연해제: 5일후 RSI 미충족  |  GC지연후매도: 5일후 RSI 충족→매도"],
            hdr,
        ]
        col_l = _col_letter(len(hdr))
        data_rows = [[str(row.get(h, "")) for h in hdr] for _, row in gc_rows.iterrows()]
        ws_gc.update(range_name=f"A1:{col_l}{len(meta)}", values=meta)
        if data_rows:
            ws_gc.update(range_name=f"A{len(meta)+1}:{col_l}{len(meta)+len(data_rows)}",
                         values=data_rows)
        print(f"[GoogleSheets] {tab_title} 저장 완료 ({len(gc_rows)}행)")

    return url, ss.id


def _col_letter(n: int) -> str:
    if n <= 26:
        return chr(64 + n)
    hi = (n - 1) // 26
    lo = (n - 1) %  26 + 1
    return chr(64 + hi) + chr(64 + lo)


# ── main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 75)
    print(f"QQQ 골든크로스 매도지연 변형  백테스트  {START_DATE} ~ {END_DATE}")
    print(f"Base  : RSI(2)+F&G + QQQ Crash Guard ({QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일)")
    print(f"GC변형: Base + QQQ MA{GC_MA_FAST}>MA{GC_MA_SLOW} 골든크로스 구간 SELL → +{GC_DELAY_DAYS}일 지연 (사이클당1회)")
    print("=" * 75)

    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
        print(f"F&G: {fng_base.index.min().date()} ~ {fng_base.index.max().date()} (이전 구간 50 적용)")
    except Exception as e:
        print(f"F&G 로드 실패: {e} → 전 기간 F&G=50")
        fng_base = pd.Series(dtype=float)

    print("\n[QQQ] 가격 데이터 다운로드...")
    qqq_close = download_close("QQQ")
    print(f"[QQQ] {len(qqq_close)}일 ({qqq_close.index[0].date()} ~ {qqq_close.index[-1].date()})")

    qqq_gc = compute_qqq_gc(qqq_close)

    total_days  = len(qqq_close)
    gc_days     = int(qqq_gc.sum())
    gc_episodes = int(((qqq_gc) & (~qqq_gc.shift(1, fill_value=False))).sum())
    avg_gc_days = round(gc_days / max(gc_episodes, 1), 1)
    gc_pct      = round(gc_days / total_days * 100, 1)
    qqq_gc_stats = {
        "total_days":  total_days,
        "gc_days":     gc_days,
        "gc_pct":      gc_pct,
        "gc_episodes": gc_episodes,
        "avg_gc_days": avg_gc_days,
    }

    results_base: dict[str, tuple] = {}
    results_gc:   dict[str, tuple] = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n{'='*60}")
        print(f"[{ticker}] 가격 데이터 다운로드...")
        close = download_close(ticker)
        print(f"[{ticker}] {len(close)}일 ({close.index[0].date()} ~ {close.index[-1].date()})")

        fng = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        print(f"  [{ticker}] Base 시뮬레이션...")
        df_b, taxes_b = simulate(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
            fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
            qqq_gc=None,
        )
        perf_b = calc_perf(df_b, taxes_b)
        results_base[ticker] = (df_b, taxes_b, perf_b)

        print(f"  [{ticker}] GC변형 시뮬레이션 (+{GC_DELAY_DAYS}일지연)...")
        df_g, taxes_g = simulate(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
            fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
            qqq_gc=qqq_gc, gc_delay_days=GC_DELAY_DAYS,
        )
        perf_g = calc_perf(df_g, taxes_g)
        results_gc[ticker] = (df_g, taxes_g, perf_g)

        # 결과 출력
        print(f"\n  [{ticker}] 비교 결과:")
        fmt = "  {:<22} {:>12} {:>12} {:>10}"
        print(fmt.format("항목", "Base", f"GC(+{GC_DELAY_DAYS}일)", "차이"))
        print("  " + "-" * 58)
        def row(label, b, g, is_money=False):
            diff = g - b
            if is_money:
                return fmt.format(label, f"${b:,.0f}", f"${g:,.0f}", f"${diff:+,.0f}")
            return fmt.format(label, f"{b:.1f}", f"{g:.1f}", f"{diff:+.1f}")
        print(row("총수익률 (%)",    perf_b["total_return_pct"], perf_g["total_return_pct"]))
        print(row("CAGR (%)",        perf_b["cagr_pct"],         perf_g["cagr_pct"]))
        print(row("MDD (%)",         perf_b["mdd_pct"],          perf_g["mdd_pct"]))
        print(fmt.format("최종자산 ($)",
                          f"${perf_b['final_assets']:,.0f}",
                          f"${perf_g['final_assets']:,.0f}",
                          f"${perf_g['final_assets']-perf_b['final_assets']:+,.0f}"))
        print(fmt.format("사이클 수",
                          str(perf_b["cycles"]), str(perf_g["cycles"]),
                          f"{perf_g['cycles']-perf_b['cycles']:+d}"))
        print(row("승률 (%)",        perf_b["win_rate"],         perf_g["win_rate"]))
        print(row("평균수익률 (%)",  perf_b["avg_ret_pct"],      perf_g["avg_ret_pct"]))
        print(row("평균보유일",       perf_b["avg_hold_days"],    perf_g["avg_hold_days"]))
        print(fmt.format(f"GC지연발생(회)", "-", str(perf_g["gc_delay_initiated"]), ""))
        print(fmt.format(f"GC지연후매도(회)", "-", str(perf_g["gc_delay_executed"]), ""))
        print(fmt.format("QQQ강제매도(회)", str(perf_b["sell_qqq_count"]), str(perf_g["sell_qqq_count"]), ""))
        print(fmt.format("양도세 ($)",
                          f"${perf_b['total_tax_paid']:,.0f}",
                          f"${perf_g['total_tax_paid']:,.0f}",
                          f"${perf_g['total_tax_paid']-perf_b['total_tax_paid']:+,.0f}"))

        # 연도별 수익률
        yr_b = yearly_returns(df_b, taxes_b)
        yr_g = yearly_returns(df_g, taxes_g)
        print(f"\n  [{ticker}] 연도별 수익률:")
        print(f"  {'연도':<18} {'Base':>8} {'GC변형':>8} {'차이':>7}")
        print("  " + "-" * 43)
        for yr_label in sorted(set(list(yr_b.keys()) + list(yr_g.keys()))):
            b_val = yr_b.get(yr_label, 0)
            g_val = yr_g.get(yr_label, 0)
            diff  = g_val - b_val
            print(f"  {yr_label:<18} {b_val:>+8.1f} {g_val:>+8.1f} {diff:>+7.1f}")

    print("\n" + "=" * 75)
    print("Google Sheet 저장 중...")
    url, sheet_id = write_to_new_sheet(results_base, results_gc, qqq_gc_stats)

    print("\n" + "=" * 75)
    print("[ 최종 결과 요약 ]")
    print(f"기간: {START_DATE} ~ {END_DATE}   초기자본: ${CAPITAL:,.0f}")
    print()
    for ticker in TICKER_CONFIG:
        _, _, perf_b = results_base[ticker]
        _, _, perf_g = results_gc[ticker]
        dc = perf_g["cagr_pct"] - perf_b["cagr_pct"]
        dm = perf_g["mdd_pct"]  - perf_b["mdd_pct"]
        dh = perf_g["avg_hold_days"] - perf_b["avg_hold_days"]
        print(f"{ticker}:")
        print(f"  Base  : CAGR {perf_b['cagr_pct']:.1f}%  MDD {perf_b['mdd_pct']:.1f}%  "
              f"최종 ${perf_b['final_assets']:,.0f}  사이클 {perf_b['cycles']}회  "
              f"평균보유 {perf_b['avg_hold_days']:.1f}일")
        print(f"  GC변형: CAGR {perf_g['cagr_pct']:.1f}%  MDD {perf_g['mdd_pct']:.1f}%  "
              f"최종 ${perf_g['final_assets']:,.0f}  사이클 {perf_g['cycles']}회  "
              f"평균보유 {perf_g['avg_hold_days']:.1f}일")
        print(f"  변화  : CAGR {dc:+.1f}%p  MDD {dm:+.1f}%p  평균보유 {dh:+.1f}일  "
              f"GC지연발생 {perf_g['gc_delay_initiated']}회  GC지연후매도 {perf_g['gc_delay_executed']}회")
    print()
    print(f"Google Sheet: {url}")
    print("=" * 75)


if __name__ == "__main__":
    main()
