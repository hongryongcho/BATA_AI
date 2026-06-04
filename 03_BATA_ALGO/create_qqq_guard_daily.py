"""
QQQ Crash Guard 일별 신호 시트 생성기
──────────────────────────────────────────────────────────────
• RSI(2) + F&G 필터 + QQQ -5%→10일 가드 (세 조건 동시 적용)
• F&G 조건: 매수 시 F&G < greed_min, 매도 시 F&G > fear_max
• QQQ 가드: QQQ -5% 이하 → 즉시 매도 + 10일 매수 금지
• 매일 실행하여 Google Sheet 업데이트
• 신규 시트 ID는 qqq_guard_sheet_id.txt 에 자동 저장

실행: python3 create_qqq_guard_daily.py
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
    CAPITAL, TAX_RATE, TAX_EXEMPT, TICKER_CONFIG,
)
from fear_greed_history import get_fng_for_dates

START_DATE    = "2021-01-01"   # F&G 데이터 유효 구간 시작
END_DATE      = datetime.today().strftime("%Y-%m-%d")
SHEET_ID_FILE = Path(__file__).parent / "qqq_guard_sheet_id.txt"

# QQQ 가드 파라미터 (최적)
QQQ_CRASH_PCT = -5.0
QQQ_COOLDOWN  = 10    # 캘린더일

# QQQ 골든크로스 매도지연 (+12일, 사이클당 1회)
GC_MA_FAST    = 50
GC_MA_SLOW    = 200
GC_DELAY_DAYS = 12

# 기존 F&G 시트와 동일한 컬럼 순서 유지 + QQQ 가드 + GC 컬럼 추가
HEADERS = [
    "date", "close", "chg_pct", "fng", "rsi2",
    "gc_on",           # QQQ MA50>MA200 골든크로스 상태
    "fng_blocked",
    "buy_limit_expected_px", "sell_limit_expected_px",
    "buy_limit_px", "sell_limit_px",
    "action", "trade_qty", "buy_cash_used",
    "holdings", "cash", "total_assets",
    "return_pct", "annual_profit_ytd", "tax_deducted",
    "qqq_chg_pct", "cooldown_days",
]


# ── QQQ 골든크로스 계산 ─────────────────────────────────────────────────────

def compute_qqq_gc(qqq_close: pd.Series) -> pd.Series:
    """QQQ MA50 > MA200 골든크로스 상태 (bool Series, 인덱스=영업일)"""
    ma_fast = qqq_close.rolling(GC_MA_FAST).mean()
    ma_slow = qqq_close.rolling(GC_MA_SLOW).mean()
    return (ma_fast > ma_slow).fillna(False)


# ── 시뮬레이션 ───────────────────────────────────────────────────────────

def simulate(
    close: pd.Series,
    qqq_close: pd.Series,
    cfg: dict,
    qqq_gc: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict]:
    alpha          = 1.0 / cfg["period"]
    fear_max       = cfg["fear_max"]
    greed_min      = cfg["greed_min"]
    sell_above     = cfg["sell_above"]
    profit_target  = cfg.get("profit_target", None)  # % 수익목표 (None=미사용)
    closes      = close.values.astype(float)
    n           = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    nbl, nsl = _build_next_day_limits(closes, ma_up, ma_down,
                                      cfg["buy_below"], sell_above, alpha)

    qqq_al = qqq_close.reindex(close.index, method="ffill").ffill().bfill()
    qqq_v  = qqq_al.values.astype(float)
    qqq_chg = np.zeros(n)
    for i in range(1, n):
        if qqq_v[i - 1] > 0:
            qqq_chg[i] = (qqq_v[i] / qqq_v[i - 1] - 1.0) * 100.0

    # QQQ 골든크로스 배열
    if qqq_gc is not None:
        gc_aligned = qqq_gc.reindex(close.index, method="ffill").fillna(False)
        gc_arr     = gc_aligned.values.astype(bool)
    else:
        gc_arr = np.zeros(n, dtype=bool)

    # 실제 F&G 히스토리 데이터 로딩
    fng_series = get_fng_for_dates(close.index)
    fng_values = fng_series.values.astype(int)

    cash = CAPITAL; holdings = 0.0; cash_at_buy = 0.0
    annual_realized_pnl = 0.0; annual_profit_ytd = 0.0
    current_tax_year = None; total_tax_paid = 0.0
    annual_taxes: dict = {}
    pending_tax = 0.0; pending_tax_year = None
    pending_tax_total_before = 0.0; pending_realized_pnl = 0.0
    cooldown_until: datetime | None = None

    # GC 매도지연 상태 (사이클당 1회)
    gc_delay_until: datetime | None = None   # 재검토 날짜
    gc_delay_used: bool = False              # 이번 사이클 사용 여부
    gc_started_during_hold: bool = False     # 보유중 GC 신규 발생 여부

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
        pending_tax = 0.0; pending_tax_year = None
        pending_realized_pnl = 0.0; annual_profit_ytd = 0.0
        return tax

    for i, (dt, price) in enumerate(close.items()):
        rsi_val = rsi[i]
        q_chg   = float(qqq_chg[i])
        fng_val = int(fng_values[i])
        gc_on   = bool(gc_arr[i])

        action = "HOLD"; fng_blocked = ""
        trade_qty = 0.0; buy_cash_used = ""; tax_today = None

        # GC 지연 대기 중 표시 (만료 전)
        if gc_delay_until is not None and dt < gc_delay_until and holdings > 0:
            remaining_gc = (gc_delay_until - dt).days
            fng_blocked = f"GC지연대기({remaining_gc}일→{gc_delay_until.strftime('%m/%d')})"

        # 연간 양도세
        if current_tax_year is None:
            current_tax_year = dt.year
        elif dt.year != current_tax_year:
            taxable = max(0.0, annual_realized_pnl - TAX_EXEMPT)
            pending_tax_total_before = rows[-1]["total_assets"] if rows else 0.0
            pending_realized_pnl     = annual_realized_pnl
            pending_tax      = round(taxable * TAX_RATE, 2) if taxable > 0 else 0.0
            pending_tax_year = current_tax_year
            if pending_tax == 0.0:
                annual_taxes[pending_tax_year] = {
                    "tax": 0.0, "realized_pnl": annual_realized_pnl,
                    "total_before": pending_tax_total_before, "deducted_on": None,
                }
                annual_profit_ytd = 0.0
                pending_tax_year = None; pending_realized_pnl = 0.0
            annual_realized_pnl = 0.0
            current_tax_year    = dt.year

        if i > 0:
            # ── 보유중 GC 신규 발생 감지 (non-GC → GC 전환) ─────────────
            if holdings > 0 and gc_arr[i] and not gc_arr[i - 1]:
                gc_started_during_hold = True

            # ── [1] QQQ 가드 (항상 우선) ─────────────────────────────────
            if q_chg <= QQQ_CRASH_PCT:
                new_until = dt + timedelta(days=QQQ_COOLDOWN)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                reason = f"QQQ{q_chg:.1f}%≤-5%→{QQQ_COOLDOWN}일"
                if holdings > 0:
                    realized = holdings * price - cash_at_buy
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    trade_qty = -holdings
                    cash += holdings * price; holdings = 0.0
                    t = _apply_pending_tax(); tax_today = t
                    action = "SELL_QQQ"; fng_blocked = reason
                    gc_delay_until         = None
                    gc_delay_used          = False
                    gc_started_during_hold = False
                else:
                    fng_blocked = reason

            # ── [2] GC 지연 만료 재검토 ──────────────────────────────────
            if action == "HOLD" and gc_delay_until is not None and dt >= gc_delay_until and holdings > 0:
                prev_sell = nsl[i - 1]
                if not np.isnan(prev_sell) and float(price) >= float(prev_sell):
                    realized = holdings * price - cash_at_buy
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    trade_qty = -holdings
                    cash += holdings * price; holdings = 0.0
                    t = _apply_pending_tax(); tax_today = t
                    action      = "SELL"
                    fng_blocked = f"GC지연후매도(RSI≥{sell_above})"
                else:
                    fng_blocked = f"GC지연해제(RSI<{sell_above})"
                gc_delay_until = None

            # ── [3] 정상 RSI+F&G 로직 (GC 지연 대기 중 아닐 때만) ────────
            if action == "HOLD" and gc_delay_until is None:
                in_cd     = cooldown_until is not None and dt <= cooldown_until
                prev_buy  = nbl[i - 1]
                prev_sell = nsl[i - 1]

                if holdings == 0.0 and not np.isnan(prev_buy) and float(price) <= float(prev_buy):
                    if in_cd:
                        rem = (cooldown_until - dt).days
                        fng_blocked = f"QQQ차단({rem}일남음)"
                    elif fng_val >= greed_min:
                        fng_blocked = f"BUY차단(F&G={fng_val}≥{greed_min})"
                    else:
                        t = _apply_pending_tax(); tax_today = t
                        cash_at_buy   = cash
                        buy_cash_used = round(float(cash), 2)
                        bought        = cash / price; holdings = bought; cash = 0.0
                        trade_qty     = bought; action = "BUY"
                        gc_delay_until         = None
                        gc_delay_used          = False
                        gc_started_during_hold = False

                # ── 수익목표 매도 (RSI 조건과 독립, 별도 if) ─────────────
                if (action == "HOLD" and holdings > 0
                        and profit_target is not None and cash_at_buy > 0):
                    current_ret_pct = (holdings * float(price) / cash_at_buy - 1) * 100
                    if current_ret_pct >= profit_target:
                        realized = holdings * price - cash_at_buy
                        annual_realized_pnl += realized; annual_profit_ytd += realized
                        trade_qty = -holdings
                        cash += holdings * price; holdings = 0.0
                        t = _apply_pending_tax(); tax_today = t
                        action      = "SELL"
                        fng_blocked = f"수익목표({profit_target:.0f}%달성,+{current_ret_pct:.1f}%)"
                        gc_delay_until         = None
                        gc_delay_used          = False
                        gc_started_during_hold = False

                # ── RSI 매도 (수익목표와 독립, 별도 if) ──────────────────
                if action == "HOLD" and holdings > 0 and not np.isnan(prev_sell) and float(price) >= float(prev_sell):
                    if fng_val <= fear_max:
                        fng_blocked = f"SELL차단(F&G={fng_val}≤{fear_max})"
                    elif gc_on and gc_started_during_hold and not gc_delay_used:
                        # 보유중 GC 신규발생 + 현재 GC 상태 + 사이클 첫 지연
                        gc_delay_until = dt + timedelta(days=GC_DELAY_DAYS)
                        gc_delay_used  = True
                        fng_blocked    = f"SELL지연(GC+{GC_DELAY_DAYS}일→{gc_delay_until.strftime('%m/%d')})"
                    else:
                        realized = holdings * price - cash_at_buy
                        annual_realized_pnl += realized; annual_profit_ytd += realized
                        trade_qty = -holdings
                        cash += holdings * price; holdings = 0.0
                        t = _apply_pending_tax(); tax_today = t
                        action = "SELL"

        total_assets = cash + holdings * float(price)
        prev_p = float(closes[i - 1]) if i > 0 else float(price)
        daily_chg = round((float(price) / prev_p - 1) * 100, 2) if i > 0 else ""
        cd_rem = max(0, (cooldown_until - dt).days) if cooldown_until and dt <= cooldown_until else 0

        show_buy  = (round(float(nbl[i]), 2) if not np.isnan(nbl[i]) else "") if holdings == 0.0 else ""
        show_sell = (round(float(nsl[i]), 2) if not np.isnan(nsl[i]) else "") if holdings > 0.0 else ""

        rows.append({
            "date":                   dt.strftime("%Y-%m-%d"),
            "close":                  round(float(price), 4),
            "chg_pct":                daily_chg,
            "qqq_chg_pct":            round(q_chg, 2) if i > 0 else "",
            "fng":                    fng_val,
            "rsi2":                   round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "gc_on":                  "Y" if gc_on else "",
            "fng_blocked":            fng_blocked,
            "cooldown_days":          cd_rem if cd_rem > 0 else "",
            "buy_limit_expected_px":  round(float(nbl[i]), 2)  if not np.isnan(nbl[i])  else "",
            "sell_limit_expected_px": round(float(nsl[i]), 2) if not np.isnan(nsl[i]) else "",
            "buy_limit_px":           show_buy,
            "sell_limit_px":          show_sell,
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

    # 마지막 연도 양도세
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if rows:
        tax_final = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
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


# ── 성과 계산 ────────────────────────────────────────────────────────────

def _calc_perf(df: pd.DataFrame, annual_taxes: dict) -> dict:
    ta = df["total_assets"].astype(float)
    final = float(ta.iloc[-1])
    dates = pd.to_datetime(df["date"])
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1 / 365.25)
    cagr  = ((final / CAPITAL) ** (1 / years) - 1) * 100
    peak  = CAPITAL; mdd = 0.0
    for v in ta:
        if v > peak: peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd: mdd = dd
    buy_cnt = int((df["action"] == "BUY").sum())
    sell_cnt = int((df["action"] == "SELL").sum())
    qqq_cnt  = int((df["action"] == "SELL_QQQ").sum())
    total_tax = sum(v.get("tax", 0) for v in annual_taxes.values())
    return {
        "total_ret": round((final / CAPITAL - 1) * 100, 2),
        "cagr":      round(cagr, 2),
        "mdd":       round(mdd, 2),
        "final":     round(final, 0),
        "buy_cnt":   buy_cnt,
        "sell_cnt":  sell_cnt + qqq_cnt,
        "qqq_cnt":   qqq_cnt,
        "total_tax": round(total_tax, 0),
    }


# ── 현재 상태 추출 ───────────────────────────────────────────────────────

def _current_state(df: pd.DataFrame, ticker: str, cfg: dict) -> dict:
    last = df.iloc[-1]
    holding  = float(last["holdings"]) > 0
    rsi_val  = last["rsi2"]
    cd_days  = int(last["cooldown_days"]) if last["cooldown_days"] != "" else 0
    buy_lim  = last["buy_limit_expected_px"]
    sell_lim = last["sell_limit_expected_px"]
    qqq_chg  = last["qqq_chg_pct"]

    if cd_days > 0:
        cooldown_str = f"QQQ쿨다운 {cd_days}일 남음"
    else:
        cooldown_str = "정상"

    current_state = (
        f"RSI(2)={rsi_val}  "
        f"{'보유중' if holding else '현금보유'}  "
        f"{cooldown_str}"
    )

    # 수익목표 현황 (보유중일 때)
    pt = cfg.get("profit_target")
    pt_str = ""
    if holding and pt is not None:
        pt_str = f"  |  수익목표 {pt:.0f}% 달성 시 즉시매도"

    # 다음날 액션
    if cd_days > 0 and not holding:
        next_action = f"QQQ쿨다운 중 ({cd_days}일) — RSI 매수신호 무시"
    elif holding:
        if sell_lim != "":
            next_action = f"LOC매도예약: ${sell_lim} 이상 시 (RSI>{cfg['sell_above']}){pt_str}"
        else:
            next_action = f"홀드 (매도 조건 미충족){pt_str}"
    else:
        if buy_lim != "":
            next_action = f"LOC매수예약: ${buy_lim} 이하 시 (RSI<{cfg['buy_below']})"
        else:
            next_action = "홀드 (매수 조건 미충족)"

    return {
        "ticker":          ticker,
        "strategy":        "RSI(2)+QQQ가드(-5%→10일)",
        "current_state":   current_state,
        "rsi":             rsi_val,
        "qqq_chg":         qqq_chg,
        "cooldown_days":   cd_days,
        "holding":         holding,
        "buy_limit":       buy_lim,
        "sell_limit":      sell_lim,
        "next_action":     next_action,
    }


# ── 사이클 추출 ─────────────────────────────────────────────────────────

GC_DELAY_KEYWORDS = ("SELL지연(GC", "GC지연대기", "GC지연해제", "GC지연후매도")


def _extract_cycles(df: pd.DataFrame) -> tuple[list[dict], dict | None]:
    """BUY → SELL/SELL_QQQ 쌍 추출. 세전 정산금 기준. GC 지연 사이클 표시."""
    completed = []
    current_buy = None
    cycle_no = 0
    had_gc_delay_this_cycle = False

    for _, row in df.iterrows():
        action = str(row.get("action", ""))
        fng_blk = str(row.get("fng_blocked", ""))

        # BUY 사이에 GC 관련 fng_blocked 누적 감지
        if current_buy is not None and any(kw in fng_blk for kw in GC_DELAY_KEYWORDS):
            had_gc_delay_this_cycle = True

        if action == "BUY":
            cycle_no += 1
            had_gc_delay_this_cycle = False
            used = row.get("buy_cash_used", "")
            try:
                start_cash = float(used) if used not in ("", None) else CAPITAL
            except (ValueError, TypeError):
                start_cash = CAPITAL
            if start_cash <= 0:
                start_cash = CAPITAL
            current_buy = {
                "cycle_no":  cycle_no,
                "buy_date":  str(row["date"]),
                "buy_price": float(row["close"]),
                "buy_rsi":   row.get("rsi2", ""),
                "start_cash": round(float(start_cash), 2),
            }
        elif action in ("SELL", "SELL_QQQ") and current_buy is not None:
            if any(kw in fng_blk for kw in GC_DELAY_KEYWORDS):
                had_gc_delay_this_cycle = True
            end_cash = float(row["cash"])
            tax_val = row.get("tax_deducted", "")
            try:
                tax_num = float(tax_val) if tax_val not in ("", None) else 0.0
                if tax_num > 0:
                    end_cash += tax_num  # 세전 기준으로 표시
            except (ValueError, TypeError):
                pass
            start_cash = float(current_buy["start_cash"])
            completed.append({
                **current_buy,
                "sell_date":           str(row["date"]),
                "sell_price":          float(row["close"]),
                "sell_rsi":            row.get("rsi2", ""),
                "is_qqq_guard":        action == "SELL_QQQ",
                "had_gc_delay":        had_gc_delay_this_cycle,
                "end_cash":            round(end_cash, 2),
                "cycle_return_pct":    round((end_cash / start_cash - 1) * 100, 2),
                "cycle_return_amount": round(end_cash - start_cash, 2),
            })
            current_buy = None
            had_gc_delay_this_cycle = False

    open_cycle = None
    if current_buy is not None:
        current_assets = float(df.iloc[-1]["total_assets"])
        start_cash = float(current_buy["start_cash"])
        open_cycle = {
            **current_buy,
            "sell_date":           "진행중",
            "sell_price":          float(df.iloc[-1]["close"]),
            "sell_rsi":            "",
            "is_qqq_guard":        False,
            "end_cash":            round(current_assets, 2),
            "cycle_return_pct":    round((current_assets / start_cash - 1) * 100, 2),
            "cycle_return_amount": round(current_assets - start_cash, 2),
        }

    return completed, open_cycle


# ── Google Sheet 저장 ─────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_signal_sheet(
    results: dict[str, tuple[pd.DataFrame, dict, dict, dict]],
):
    """
    results[ticker] = (df, annual_taxes, perf, state)
    """
    from sheets_manager import SheetsManager

    # 기존 시트 ID 확인
    if SHEET_ID_FILE.exists():
        existing_id = SHEET_ID_FILE.read_text().strip()
    else:
        existing_id = None

    sm = SheetsManager(spreadsheet_id=None)
    gc = sm._get_client()

    sheet_title = f"TQQQ_SOXL_RSI2_QQQ가드_GC지연_{END_DATE[:4]}"

    if existing_id:
        try:
            ss = gc.open_by_key(existing_id)
            print(f"[GoogleSheets] 기존 시트 업데이트: {existing_id}")
            for ws in ss.worksheets()[1:]:
                ss.del_worksheet(ws)
            ss.sheet1.clear()
            ss.sheet1.update_title("Summary")
        except Exception:
            print("[GoogleSheets] 기존 시트 없음 → 새로 생성")
            ss = gc.create(sheet_title)
            existing_id = None

    if not existing_id:
        ss = gc.create(sheet_title)
        SHEET_ID_FILE.write_text(ss.id)
        print(f"[GoogleSheets] 새 시트 생성: {ss.id}")

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"

    # ── Summary 탭 ─────────────────────────────────────────────────
    ws_sum = ss.sheet1
    ws_sum.update_title("Summary")

    cur_yr = datetime.now().year
    sum_rows: list[list] = []

    # ── 1. 헤더 ───────────────────────────────────────────────
    sum_rows.append([f"TQQQ / SOXL  RSI(2) + F&G + QQQ Guard ({QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일) + GC 매도지연 MA{GC_MA_FAST}>MA{GC_MA_SLOW} +{GC_DELAY_DAYS}일  |  TQQQ 수익목표 15% 달성 시 즉시매도"])
    sum_rows.append([f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   |   기간: {START_DATE} ~ {END_DATE}   |   초기자본: ${CAPITAL:,.0f}   |   체결: LOC"])
    sum_rows.append([f"QQQ Crash Guard: QQQ {QQQ_CRASH_PCT}% 이하 → 즉시 강제매도 + {QQQ_COOLDOWN}일 매수금지   |   F&G: 매수<90 / 매도>25   |   GC지연: 보유중 QQQ MA{GC_MA_FAST}>MA{GC_MA_SLOW} 신규발생 → SELL +{GC_DELAY_DAYS}일 (사이클당1회)"])
    sum_rows.append([])

    # ── 2. 성과 비교표 ────────────────────────────────────────
    sum_rows.append(["[ 전략 성과 요약: RSI2+F&G+QQQ가드+GC지연 ]"])
    sum_rows.append(["종목", "전략", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수", "QQQ강제매도", "총양도세($)"])
    for ticker, (df, taxes, perf, state) in results.items():
        cfg_t = TICKER_CONFIG[ticker]
        sum_rows.append([
            ticker,
            f"RSI2_{cfg_t['buy_below']}_{cfg_t['sell_above']}+F&G+QQQ가드+GC지연{GC_DELAY_DAYS}일",
            perf["total_ret"], perf["cagr"], perf["mdd"],
            perf["final"], perf["buy_cnt"], perf["qqq_cnt"], perf["total_tax"],
        ])
    sum_rows.append([])

    # ── 3. 현재 사이클 & 다음날 주문 (load_qqq_guard_signals() 가 읽는 포맷) ──
    sum_rows.append(["[ 현재 사이클 & 다음날 예약 주문 (RSI2+F&G+QQQ가드+GC지연 기준) ]"])
    sum_rows.append([
        "종목", "전략명", "현재상태", "현재사이클", "오늘종가", "RSI(2)", "QQQ변화%",
        "다음장 BUY 기준가", "다음장 SELL 기준가", "추천 예약주문",
        "직전 사이클 정산현금($)", "총수익률(%)", "거래횟수",
    ])
    for ticker, (df, taxes, perf, state) in results.items():
        cfg_t = TICKER_CONFIG[ticker]
        completed, open_cycle = _extract_cycles(df)
        settled_cash = completed[-1]["end_cash"] if completed else CAPITAL
        current_cycle_no = open_cycle["cycle_no"] if open_cycle else len(completed)
        today_close = float(df.iloc[-1]["close"])
        sum_rows.append([
            state["ticker"],
            f"RSI2_{cfg_t['buy_below']}_{cfg_t['sell_above']}+F&G+QQQ가드+GC지연{GC_DELAY_DAYS}일",
            state["current_state"],
            current_cycle_no,
            today_close,
            state["rsi"],
            state["qqq_chg"],
            state["buy_limit"],
            state["sell_limit"],
            state["next_action"],
            settled_cash,
            perf["total_ret"],
            perf["buy_cnt"],
        ])
        sum_rows.append([f"📌 {state['next_action']}"])
    sum_rows.append([])

    # ── 4. 연도별 수익률 (전년도 양도세 제하고 이월된 금액 대비 해당연도 마지막 사이클 정산금) ──
    sum_rows.append(["[ 연도별 수익률 (RSI2+F&G+QQQ가드+GC지연) ]"])
    yr_labels: list[str] = []
    yearly_all: dict = {}
    for ticker, (df, taxes, perf, state) in results.items():
        df2 = df.copy()
        df2["year"] = pd.to_datetime(df2["date"]).dt.year
        df2["tax_deducted_num"] = pd.to_numeric(df2["tax_deducted"], errors="coerce").fillna(0.0)
        yd: dict = {}
        for yr, grp in df2.groupby("year"):
            # s = 전년도 양도세 차감 직후 이월금액
            # 전년도 세금이 차감된 첫 번째 거래 행의 total_assets 사용
            # 현재 연도의 마지막 행(추정 당기 세금 반영)은 제외하고 탐색
            search_grp = grp.iloc[:-1] if (yr == cur_yr and len(grp) > 1) else grp
            prev_tax_rows = search_grp[search_grp["tax_deducted_num"] > 0]
            if not prev_tax_rows.empty:
                s = float(prev_tax_rows.iloc[0]["total_assets"])
            else:
                s = float(grp.iloc[0]["total_assets"])
            if s <= 0:
                s = CAPITAL

            e = float(grp.iloc[-1]["total_assets"])
            # 현재 연도: 마지막 행에 추정 당기 세금이 이미 차감되어 있으면 환원
            # (세금은 내년에 실제 납부 예정이므로, 투자 수익률에서 제외)
            if yr == cur_yr:
                last_row_tax = float(grp.iloc[-1]["tax_deducted_num"])
                if last_row_tax > 0:
                    e += last_row_tax

            label = f"{yr}년(진행중)" if yr == cur_yr else f"{yr}년"
            yd[label] = round((e / s - 1) * 100, 2)
            if label not in yr_labels:
                yr_labels.append(label)
        yearly_all[ticker] = yd
    yr_labels.sort()
    annual_ret_rows: list[dict] = []
    sum_rows.append(["종목"] + yr_labels)
    for ticker in results:
        row_idx = len(sum_rows)
        values = [yearly_all[ticker].get(y, "") for y in yr_labels]
        sum_rows.append([ticker] + values)
        annual_ret_rows.append({"row_idx": row_idx, "values": values})
    sum_rows.append([])

    # ── 5. 사이클 비교표 (TQQQ/SOXL 나란히, 양도세 행 삽입, ASCII 막대) ──

    def _bar_text(pct: float, max_pos: float, max_neg_abs: float, width: int = 28) -> str:
        center = width // 2
        bar_w = center - 2
        label = f"{pct:.2f}%"
        if pct > 0 and max_pos > 0:
            filled = max(0, int(round(min(pct / max_pos, 1.0) * bar_w)))
            return " " * (center - 1) + "|" + "█" * filled + "░" * (bar_w - filled) + " " + label
        elif pct < 0 and max_neg_abs > 0:
            filled = max(0, int(round(min(abs(pct) / max_neg_abs, 1.0) * bar_w)))
            return " " * (bar_w - filled) + "█" * filled + "|" + "░" * (center - 1) + " " + label
        else:
            return " " * (center - 1) + "|" + "░" * center + " " + label

    def _build_timeline(cycles: list[dict], taxes: dict) -> list[dict]:
        """완료 사이클에 양도세 행을 실제 차감일 기준으로 삽입한 타임라인 생성."""
        tax_events = []
        last_sell = max((str(c.get("sell_date", "")) for c in cycles), default="") if cycles else ""
        for yr, info in sorted(taxes.items()):
            d_on = str(info.get("deducted_on") or "")
            if not d_on:
                continue
            if last_sell and d_on > last_sell:
                continue
            tax_events.append({"kind": "tax", "year": int(yr), "deducted_on": d_on})

        if not cycles:
            return tax_events

        inserts_after: dict[int, list] = {}
        pre_events: list = []
        first_buy = str(cycles[0].get("buy_date", ""))

        for ev in tax_events:
            td = ev["deducted_on"]
            placed = False
            for i, c in enumerate(cycles):
                sd = str(c.get("sell_date", ""))
                nx = cycles[i + 1] if i + 1 < len(cycles) else None
                nb = str(nx.get("buy_date", "")) if nx else ""
                if sd and td >= sd and (not nb or td < nb):
                    inserts_after.setdefault(i, []).append(ev)
                    placed = True
                    break
            if not placed:
                hi = -1
                for i, c in enumerate(cycles):
                    if str(c.get("buy_date", "")) <= td:
                        hi = i
                if hi >= 0:
                    inserts_after.setdefault(hi, []).append(ev)
                    placed = True
            if not placed and first_buy and td < first_buy:
                pre_events.append(ev)

        timeline: list[dict] = list(pre_events)
        for i, c in enumerate(cycles):
            timeline.append({"kind": "cycle", "data": c})
            for ev in inserts_after.get(i, []):
                timeline.append(ev)
        return timeline

    # 각 티커의 완료 사이클 및 타임라인
    ticker_list = list(results.keys())
    cycles_map: dict[str, list] = {}
    taxes_map: dict[str, dict] = {}
    timeline_map: dict[str, list] = {}

    max_pos = 0.0
    max_neg_abs = 0.0

    for ticker, (df, taxes, perf, state) in results.items():
        completed, _ = _extract_cycles(df)
        cycles_map[ticker] = completed
        taxes_map[ticker] = taxes
        timeline_map[ticker] = _build_timeline(completed, taxes)
        for c in completed:
            p = float(c["cycle_return_pct"])
            if p > 0:
                max_pos = max(max_pos, p)
            else:
                max_neg_abs = max(max_neg_abs, abs(p))

    t_key = ticker_list[0] if len(ticker_list) > 0 else "TQQQ"
    s_key = ticker_list[1] if len(ticker_list) > 1 else "SOXL"
    tl_t = timeline_map.get(t_key, [])
    tl_s = timeline_map.get(s_key, [])

    sum_rows.append(["[ 사이클 비교표 (RSI2+F&G+QQQ가드+GC지연) ]"])
    sum_rows.append([
        "Cycle #",
        f"{t_key} 시작일", f"{t_key} 시작현금($)", f"{t_key} 매수가",
        f"{t_key} 종료일", f"{t_key} 매도가", f"{t_key} 종료현금($)", f"{t_key} 수익률/바",
        "",
        f"{s_key} 시작일", f"{s_key} 시작현금($)", f"{s_key} 매수가",
        f"{s_key} 종료일", f"{s_key} 매도가", f"{s_key} 종료현금($)", f"{s_key} 수익률/바",
    ])

    cycle_bar_rows: list[dict] = []
    display_no = 0
    for i in range(max(len(tl_t), len(tl_s))):
        t_item = tl_t[i] if i < len(tl_t) else None
        s_item = tl_s[i] if i < len(tl_s) else None

        t_is_cycle = t_item and t_item.get("kind") == "cycle"
        s_is_cycle = s_item and s_item.get("kind") == "cycle"
        t_is_tax   = t_item and t_item.get("kind") == "tax"
        s_is_tax   = s_item and s_item.get("kind") == "tax"

        if t_is_cycle or s_is_cycle:
            display_no += 1
            cycle_cell = display_no
        else:
            cycle_cell = ""

        t_cells = ["", "", "", "", "", "", ""]
        s_cells = ["", "", "", "", "", "", ""]
        left_label = ""
        t_pct_val: float | None = None
        s_pct_val: float | None = None

        if t_is_cycle:
            c = t_item["data"]
            pct = float(c["cycle_return_pct"])
            t_pct_val = pct
            guard_note = "🚨" if c.get("is_qqq_guard") else ("🔵" if c.get("had_gc_delay") else "")
            t_cells = [
                c["buy_date"], c["start_cash"], c["buy_price"],
                c["sell_date"], c["sell_price"], c["end_cash"],
                guard_note + _bar_text(pct, max_pos, max_neg_abs),
            ]
        elif t_is_tax:
            yr = int(t_item["year"])
            info = taxes_map[t_key].get(yr, {})
            tax = float(info.get("tax", 0))
            tot = float(info.get("total_before", 0))
            pct_str = f"▼ -${tax:,.0f}  ({(-tax/tot*100):.2f}%)" if tot > 0 else f"▼ -${tax:,.0f}"
            t_cells = ["", "", "", f"{yr}-12-31 기준", "", round(-tax, 2), pct_str]
            left_label = f"★ {t_key} {yr}년 양도세"

        if s_is_cycle:
            c = s_item["data"]
            pct = float(c["cycle_return_pct"])
            s_pct_val = pct
            guard_note = "🚨" if c.get("is_qqq_guard") else ("🔵" if c.get("had_gc_delay") else "")
            s_cells = [
                c["buy_date"], c["start_cash"], c["buy_price"],
                c["sell_date"], c["sell_price"], c["end_cash"],
                guard_note + _bar_text(pct, max_pos, max_neg_abs),
            ]
        elif s_is_tax:
            yr = int(s_item["year"])
            info = taxes_map[s_key].get(yr, {})
            tax = float(info.get("tax", 0))
            tot = float(info.get("total_before", 0))
            pct_str = f"▼ -${tax:,.0f}  ({(-tax/tot*100):.2f}%)" if tot > 0 else f"▼ -${tax:,.0f}"
            s_cells = [f"★ {s_key} {yr}년 양도세", "", "", f"{yr}-12-31 기준", "", round(-tax, 2), pct_str]

        row_label = left_label if left_label else cycle_cell
        row_idx_cycle = len(sum_rows)
        sum_rows.append([
            row_label,
            t_cells[0], t_cells[1], t_cells[2], t_cells[3], t_cells[4], t_cells[5], t_cells[6],
            "",
            s_cells[0], s_cells[1], s_cells[2], s_cells[3], s_cells[4], s_cells[5], s_cells[6],
        ])
        if t_pct_val is not None or s_pct_val is not None:
            cycle_bar_rows.append({"row_idx": row_idx_cycle, "t_pct": t_pct_val, "s_pct": s_pct_val})

    sum_rows.append([])

    col_l = _col_letter(max(len(r) for r in sum_rows if r))
    ws_sum.update(range_name=f"A1:{col_l}{len(sum_rows)}", values=sum_rows)
    print("[GoogleSheets] Summary 저장 완료")

    # ── Summary 탭 서식 적용 ────────────────────────────────────────
    C_TITLE_BG_S = {"red": 0.098, "green": 0.180, "blue": 0.298}  # 진남색
    C_META_BG_S  = {"red": 0.855, "green": 0.914, "blue": 0.969}  # 연파랑
    C_SEC_BG     = {"red": 0.780, "green": 0.878, "blue": 0.996}  # 섹션헤더 파랑
    C_HDR_BG_S   = {"red": 0.267, "green": 0.447, "blue": 0.769}  # 열헤더 파랑
    C_HDR_FG_S   = {"red": 1.0,   "green": 1.0,   "blue": 1.0}    # 흰 글씨
    C_PIN_BUY_S  = {"red": 0.714, "green": 0.933, "blue": 0.714}  # 📌 BUY 연두
    C_PIN_SELL_S = {"red": 1.0,   "green": 0.800, "blue": 0.800}  # 📌 SELL 연분홍
    C_PIN_HOLD_S = {"red": 1.0,   "green": 0.965, "blue": 0.804}  # 📌 HOLD 연노랑
    C_TAX_S      = {"red": 1.0,   "green": 1.0,   "blue": 0.600}  # 양도세 연노랑
    C_RET_POS    = {"red": 1.0,   "green": 0.878, "blue": 0.878}  # 수익+ 연한 빨강
    C_RET_NEG    = {"red": 0.816, "green": 0.882, "blue": 1.0}    # 손절- 연한 파랑

    ws_sum_id  = ws_sum.id
    sum_n_cols = max(len(r) for r in sum_rows if r)
    C_WHITE    = {"red": 1.0, "green": 1.0, "blue": 1.0}
    C_BLACK    = {"red": 0.0, "green": 0.0, "blue": 0.0}

    # 사이클 테이블 열 경계 (16열 기준)
    # Col 0-7: TQQQ 영역 / Col 8: 구분자 / Col 9-15: SOXL 영역
    TQQQ_END_COL = 8   # endColumnIndex (exclusive) for TQQQ area
    SOXL_START_COL = 9  # startColumnIndex for SOXL area
    SOXL_END_COL = 16   # endColumnIndex (exclusive) for SOXL area

    sum_fmt: list[dict] = [
        # ① 기존 모든 서식 초기화 (잔여 색상 제거)
        {"repeatCell": {
            "range": {"sheetId": ws_sum_id},
            "cell": {"userEnteredFormat": {
                "backgroundColor": C_WHITE,
                "textFormat": {"bold": False, "foregroundColor": C_BLACK, "fontSize": 10}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
    ]

    for ri, row in enumerate(sum_rows):
        cell0 = str(row[0]) if row else ""
        cell9 = str(row[9]) if len(row) > 9 else ""

        if ri == 0:
            # 타이틀 행: 진남색 + 흰 굵은글씨 fontSize=14
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_TITLE_BG_S,
                    "textFormat": {"foregroundColor": C_HDR_FG_S, "bold": True, "fontSize": 14}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif ri in (1, 2):
            # 메타 행: 연파랑 배경
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_META_BG_S,
                    "textFormat": {"fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif cell0.startswith("[ "):
            # 섹션 헤더: 파랑 배경 + 굵은글씨 fontSize=11
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_SEC_BG,
                    "textFormat": {"bold": True, "fontSize": 11}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif cell0 in ("종목", "Cycle #"):
            # 열 헤더: 파랑 배경 + 흰 굵은글씨
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_HDR_BG_S,
                    "textFormat": {"foregroundColor": C_HDR_FG_S, "bold": True, "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif cell0.startswith("📌"):
            # 📌 행: 액션에 따라 색상
            au = cell0.upper()
            pin_bg = C_PIN_BUY_S if "BUY" in au else (C_PIN_SELL_S if "SELL" in au else C_PIN_HOLD_S)
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": pin_bg,
                    "textFormat": {"bold": True, "fontSize": 11}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        else:
            # 양도세 행: TQQQ(cell0=★) / SOXL(cell9=★) 각각 해당 열 영역만 색상 적용
            if cell0.startswith("★"):
                # TQQQ 양도세: col 0~7만 연노랑
                sum_fmt.append({"repeatCell": {
                    "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                               "startColumnIndex": 0, "endColumnIndex": TQQQ_END_COL},
                    "cell": {"userEnteredFormat": {"backgroundColor": C_TAX_S}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})
            if cell9.startswith("★"):
                # SOXL 양도세: col 9~15만 연노랑
                sum_fmt.append({"repeatCell": {
                    "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                               "startColumnIndex": SOXL_START_COL, "endColumnIndex": SOXL_END_COL},
                    "cell": {"userEnteredFormat": {"backgroundColor": C_TAX_S}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})

    # ── 연도별 수익률 셀별 색상 (양수=연빨강, 음수=연파랑) ──
    for ar in annual_ret_rows:
        ri = ar["row_idx"]
        for ci, val in enumerate(ar["values"]):
            if val == "":
                continue
            try:
                num = float(val)
            except (ValueError, TypeError):
                continue
            if num == 0:
                continue
            bg = C_RET_POS if num > 0 else C_RET_NEG
            col_idx = 1 + ci  # 값은 col 1부터 시작
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    # ── 사이클 수익률/바 셀 색상 (양수=연빨강, 음수=연파랑) ──
    # TQQQ 수익률/바: col 7 / SOXL 수익률/바: col 15
    for cb in cycle_bar_rows:
        ri = cb["row_idx"]
        if cb["t_pct"] is not None:
            bg = C_RET_POS if cb["t_pct"] > 0 else C_RET_NEG
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 7, "endColumnIndex": 8},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})
        if cb["s_pct"] is not None:
            bg = C_RET_POS if cb["s_pct"] > 0 else C_RET_NEG
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 15, "endColumnIndex": 16},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    # Summary 상단 3행 고정
    sum_fmt.append({"updateSheetProperties": {
        "properties": {"sheetId": ws_sum_id,
                       "gridProperties": {"frozenRowCount": 3}},
        "fields": "gridProperties.frozenRowCount",
    }})

    if sum_fmt:
        ss.batch_update({"requests": sum_fmt})
    print("[GoogleSheets] Summary 서식 적용 완료")

    # ── 색상 상수 ─────────────────────────────────────────────
    C_BUY      = {"red": 0.714, "green": 0.933, "blue": 0.714}   # 연두
    C_SELL     = {"red": 1.0,   "green": 0.8,   "blue": 0.8}     # 연분홍
    C_QQQ      = {"red": 1.0,   "green": 0.6,   "blue": 0.2}     # 주황 (QQQ 강제매도)
    C_TAX      = {"red": 1.0,   "green": 1.0,   "blue": 0.6}     # 연노랑 (양도세)
    C_GC_DELAY = {"red": 0.878, "green": 0.753, "blue": 1.0}     # 연보라 (GC 지연)
    C_HDR_BG   = {"red": 0.267, "green": 0.447, "blue": 0.769}   # 헤더 파랑
    C_HDR_FG   = {"red": 1.0,   "green": 1.0,   "blue": 1.0}     # 흰 글씨
    C_TITLE_BG = {"red": 0.098, "green": 0.180, "blue": 0.298}   # 진남색
    C_META_BG  = {"red": 0.855, "green": 0.914, "blue": 0.969}   # 연파랑
    GC_KEYWORDS = ("SELL지연(GC", "GC지연대기", "GC지연해제", "GC지연후매도")

    # ── 종목별 일별 탭 (TQQQ_매매기준가 형식) ─────────────────────
    for ticker, (df, taxes, perf, state) in results.items():
        tab_name = f"{ticker}_매매기준가"
        ws = ss.add_worksheet(title=tab_name, rows=max(5500, len(df) + 10), cols=len(HEADERS) + 2)
        ws_id = ws.id

        cfg_t = TICKER_CONFIG[ticker]
        pt = cfg_t.get("profit_target")
        pt_str = f"  /  수익목표 {pt:.0f}%달성시즉시매도" if pt else ""
        meta = [
            [f"{ticker}  —  RSI(2)+F&G+QQQ가드+GC지연{pt_str}  "
             f"매수: RSI<{cfg_t['buy_below']} & F&G<{cfg_t['greed_min']}  /  "
             f"매도: RSI>{cfg_t['sell_above']} & F&G>{cfg_t['fear_max']}{f' / 수익목표 {pt:.0f}%' if pt else ''}  /  "
             f"QQQ≤-5%→강제매도+{QQQ_COOLDOWN}일  /  GC지연 MA{GC_MA_FAST}>MA{GC_MA_SLOW} +{GC_DELAY_DAYS}일"],
            [f"총수익률: {perf['total_ret']}%   CAGR: {perf['cagr']}%"
             f"   MDD: {perf['mdd']}%   최종자산: ${perf['final']:,.0f}"],
            [f"기간: {START_DATE} ~ {END_DATE}   "
             f"거래: {perf['buy_cnt']}회   체결: LOC   QQQ강제매도: {perf['qqq_cnt']}회   총양도세: ${perf['total_tax']:,.0f}"],
            [f"F&G: Fear≤{cfg_t['fear_max']}→SELL보류 / Greed≥{cfg_t['greed_min']}→BUY보류   |   "
             f"QQQ {QQQ_CRASH_PCT}%→강제매도+{QQQ_COOLDOWN}일   |   "
             f"GC지연: 보유중 QQQ MA{GC_MA_FAST}>MA{GC_MA_SLOW} 신규발생 → +{GC_DELAY_DAYS}일 (사이클당1회)"],
            HEADERS,
        ]
        data_rows = [[str(row.get(h, "")) for h in HEADERS] for _, row in df.iterrows()]
        n_meta = len(meta)
        col_l = _col_letter(len(HEADERS))
        ws.update(range_name=f"A1:{col_l}{n_meta}", values=meta)
        if data_rows:
            ws.update(range_name=f"A{n_meta+1}:{col_l}{n_meta+len(data_rows)}", values=data_rows)

        # ── 행별 색상 포맷팅 ───────────────────────────────────
        n_cols = len(HEADERS)
        fmt_requests = [
            # 타이틀 행 (R1)
            {"repeatCell": {
                "range": {"sheetId": ws_id, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_TITLE_BG,
                    "textFormat": {"foregroundColor": C_HDR_FG, "bold": True, "fontSize": 14}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            # 메타 행 (R2-R4)
            {"repeatCell": {
                "range": {"sheetId": ws_id, "startRowIndex": 1, "endRowIndex": 4,
                           "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {"backgroundColor": C_META_BG}},
                "fields": "userEnteredFormat.backgroundColor",
            }},
            # 헤더 행 (R5)
            {"repeatCell": {
                "range": {"sheetId": ws_id, "startRowIndex": 4, "endRowIndex": 5,
                           "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_HDR_BG,
                    "textFormat": {"foregroundColor": C_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            # 행 고정 (메타+헤더)
            {"updateSheetProperties": {
                "properties": {"sheetId": ws_id,
                               "gridProperties": {"frozenRowCount": n_meta}},
                "fields": "gridProperties.frozenRowCount",
            }},
        ]

        # BUY / SELL / SELL_QQQ / GC지연 / 양도세 행 색상
        for i, row in enumerate(df.itertuples(index=False)):
            r_idx = n_meta + i  # 0-based
            action = str(getattr(row, "action", ""))
            tax_val = getattr(row, "tax_deducted", "")
            has_tax = tax_val not in ("", None) and str(tax_val) not in ("", "0", "0.0")
            fng_blk = str(getattr(row, "fng_blocked", ""))
            is_gc_row = any(kw in fng_blk for kw in GC_KEYWORDS)

            if action == "BUY":
                bg = C_BUY
            elif action == "SELL_QQQ":
                bg = C_QQQ
            elif action == "SELL":
                bg = C_SELL
            elif is_gc_row:
                bg = C_GC_DELAY
            elif has_tax:
                bg = C_TAX
            else:
                continue

            fmt_requests.append({"repeatCell": {
                "range": {"sheetId": ws_id,
                          "startRowIndex": r_idx, "endRowIndex": r_idx + 1,
                          "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

        ss.batch_update({"requests": fmt_requests})
        gc_init_cnt = int(df["fng_blocked"].astype(str).str.startswith("SELL지연(GC").sum())
        gc_rows_cnt = int(df["fng_blocked"].astype(str).str.contains("GC지연", na=False).sum())
        print(f"[GoogleSheets] {tab_name} 저장 완료 ({len(df)}행  "
              f"BUY {perf['buy_cnt']}회  SELL {perf['sell_cnt']}회  QQQ {perf['qqq_cnt']}회  "
              f"GC지연발생 {gc_init_cnt}회  GC관련행 {gc_rows_cnt}행)")

    print(f"[GoogleSheets] URL: {url}")
    return url, ss.id


# ── main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print(f"RSI(2) + F&G 필터 + QQQ Crash Guard 신호 시트 업데이트  {END_DATE}")
    print(f"알고리즘: RSI(2) + F&G(매수F&G<90, 매도F&G>25) + QQQ -5%→10일")
    print("=" * 65)

    import yfinance as yf

    def _dl(t):
        raw = yf.download(t, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        s = raw["Close"].squeeze()
        s.index = pd.to_datetime(s.index).normalize()
        return s.sort_index().dropna()

    print("\n[QQQ] 가격 다운로드...")
    qqq_close = _dl("QQQ")
    qqq_gc    = compute_qqq_gc(qqq_close)
    gc_days   = int(qqq_gc.sum())
    gc_total  = len(qqq_gc)
    print(f"[QQQ GC] MA{GC_MA_FAST}>MA{GC_MA_SLOW}: {gc_days}일/{gc_total}일 ({gc_days/gc_total*100:.1f}%) GC상태")

    results: dict = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n[{ticker}] 시뮬레이션...")
        close = _dl(ticker)
        df, annual_taxes = simulate(close, qqq_close, cfg, qqq_gc=qqq_gc)
        perf  = _calc_perf(df, annual_taxes)
        state = _current_state(df, ticker, cfg)
        results[ticker] = (df, annual_taxes, perf, state)

        gc_init = int(df["fng_blocked"].astype(str).str.startswith("SELL지연(GC").sum())
        gc_rows = int(df["fng_blocked"].astype(str).str.contains("GC지연", na=False).sum())
        print(f"  CAGR {perf['cagr']:.1f}%  MDD {perf['mdd']:.1f}%  최종 ${perf['final']:,.0f}")
        print(f"  QQQ강제매도 {perf['qqq_cnt']}회  GC지연발생 {gc_init}회 ({gc_rows}행)  양도세 ${perf['total_tax']:,.0f}")
        print(f"  현재상태: {state['current_state']}")
        print(f"  다음액션: {state['next_action']}")

    url, sheet_id = write_signal_sheet(results)
    print(f"\n시트 ID: {sheet_id}")
    print(f"URL: {url}")
    print(f"\n앱 .env 에 아래를 추가하세요:")
    print(f"QQQ_GUARD_SPREADSHEET_ID={sheet_id}")
    print("=" * 65)

    return sheet_id


if __name__ == "__main__":
    main()
