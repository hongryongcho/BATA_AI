"""
RSI(2) + F&G + QQQ Crash Guard  —  일별 신호 시트 생성기
──────────────────────────────────────────────────────────────
• 기존 F&G 시트와 동일한 형태 (포맷·섹션 구조 동일)
• 성과 비교: RSI2+F&G(기존) vs RSI2+F&G+QQQ가드(신규)
• 기간: 2021-01-01 ~ 오늘 (F&G 데이터 유효 구간)
• 기존 QQQ Guard 시트(qqq_guard_sheet_id.txt) 업데이트

실행: python3 create_qqq_guard_sheet.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# ── 기존 모듈에서 필요한 것만 임포트 ────────────────────────────
from create_rsi_fng_sheet import (
    simulate_with_fng,
    write_fng_summary_tab,
    write_fng_daily_tab,
    _extract_cycle_state_fng,
    TICKER_CONFIG,
    CAPITAL,
)
import search_optimal_strategies as search_mod
from create_qqq_crash_guard_backtest import (
    download_close, _build_rsi_arrays, _build_next_day_limits,
    TAX_RATE, TAX_EXEMPT,
)
from fear_greed_history import load_fng_history
from fear_greed import fetch_fear_greed
from sheets_manager import SheetsManager

START_DATE    = "2021-01-01"
END_DATE      = datetime.today().strftime("%Y-%m-%d")
SHEET_ID_FILE = Path(__file__).parent / "qqq_guard_sheet_id.txt"

QQQ_CRASH_PCT = -5.0
QQQ_COOLDOWN  = 10


# ── QQQ Guard 시뮬레이션 ─────────────────────────────────────────

def simulate_guard(
    close: pd.Series,
    fng: pd.Series,
    qqq_close: pd.Series,
    cfg: dict,
) -> tuple[pd.DataFrame, dict]:
    """RSI(2) + F&G 필터 + QQQ Crash Guard 시뮬레이션."""
    period    = cfg["period"]
    buy_below = cfg["buy_below"]
    sell_above = cfg["sell_above"]
    fear_max  = cfg["fear_max"]
    greed_min = cfg["greed_min"]
    alpha     = 1.0 / period

    closes = close.values.astype(float)
    n      = len(closes)

    ma_up, ma_down, rsi = _build_rsi_arrays(closes, alpha)
    nbl, nsl = _build_next_day_limits(closes, ma_up, ma_down, buy_below, sell_above, alpha)

    qqq_al  = qqq_close.reindex(close.index, method="ffill").ffill().bfill()
    qqq_v   = qqq_al.values.astype(float)
    qqq_chg = np.zeros(n)
    for i in range(1, n):
        if qqq_v[i - 1] > 0:
            qqq_chg[i] = (qqq_v[i] / qqq_v[i - 1] - 1.0) * 100.0

    fng_aligned = fng.reindex(close.index, method="ffill").fillna(50).astype(int)
    fng_values  = fng_aligned.values.astype(int)

    cash = CAPITAL; holdings = 0.0; cash_at_buy = 0.0
    annual_realized_pnl = 0.0; annual_profit_ytd = 0.0
    current_tax_year = None; total_tax_paid = 0.0
    annual_taxes: dict = {}
    pending_tax = 0.0; pending_tax_year = None
    pending_tax_total_before = 0.0; pending_realized_pnl = 0.0
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

        action = "HOLD"; fng_blocked = ""
        trade_qty = 0.0; buy_cash_used = ""; tax_today = None

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
                    "tax": 0.0, "total_before": pending_tax_total_before,
                    "deducted_on": dt.strftime("%Y-%m-%d"),
                }
                annual_profit_ytd = 0.0
                pending_tax_year = None; pending_realized_pnl = 0.0
            annual_realized_pnl = 0.0
            current_tax_year    = dt.year

        if i > 0:
            # QQQ Guard (최우선)
            if q_chg <= QQQ_CRASH_PCT:
                new_until = dt + timedelta(days=QQQ_COOLDOWN)
                if cooldown_until is None or new_until > cooldown_until:
                    cooldown_until = new_until
                reason = f"QQQ{q_chg:.1f}%→강제매도+{QQQ_COOLDOWN}일"
                if holdings > 0:
                    realized = holdings * price - cash_at_buy
                    annual_realized_pnl += realized; annual_profit_ytd += realized
                    trade_qty = -holdings
                    cash += holdings * price; holdings = 0.0
                    t = _apply_pending_tax(); tax_today = t
                    action = "SELL_QQQ"; fng_blocked = reason
                else:
                    fng_blocked = reason

            # RSI + F&G 조건
            if action == "HOLD":
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
                        cash_at_buy = cash
                        buy_cash_used = round(float(cash), 2)
                        bought = cash / price; holdings = bought; cash = 0.0
                        trade_qty = bought; action = "BUY"

                elif holdings > 0 and not np.isnan(prev_sell) and float(price) >= float(prev_sell):
                    if fng_val <= fear_max:
                        fng_blocked = f"SELL차단(F&G={fng_val}≤{fear_max})"
                    else:
                        realized = holdings * price - cash_at_buy
                        annual_realized_pnl += realized; annual_profit_ytd += realized
                        trade_qty = -holdings
                        cash += holdings * price; holdings = 0.0
                        t = _apply_pending_tax(); tax_today = t
                        action = "SELL"

        total_assets = cash + holdings * float(price)
        prev_p    = float(closes[i - 1]) if i > 0 else float(price)
        daily_chg = round((float(price) / prev_p - 1) * 100, 2) if i > 0 else ""
        cd_rem    = max(0, (cooldown_until - dt).days) if cooldown_until and dt <= cooldown_until else 0

        show_buy  = (round(float(nbl[i]), 2) if not np.isnan(nbl[i]) else "") if holdings == 0.0 else ""
        show_sell = (round(float(nsl[i]), 2) if not np.isnan(nsl[i]) else "") if holdings > 0.0 else ""

        rows.append({
            "date":                   dt.strftime("%Y-%m-%d"),
            "close":                  round(float(price), 4),
            "chg_pct":                daily_chg,
            "fng":                    fng_val,
            f"rsi{period}":           round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "fng_blocked":            fng_blocked,
            "buy_limit_expected_px":  round(float(nbl[i - 1]), 2) if i > 0 and not np.isnan(nbl[i - 1]) else "",
            "sell_limit_expected_px": round(float(nsl[i - 1]), 2) if i > 0 and not np.isnan(nsl[i - 1]) else "",
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
            "qqq_chg_pct":            round(q_chg, 2) if i > 0 else "",
            "cooldown_days":          cd_rem if cd_rem > 0 else "",
        })

    # 마지막 연도 양도세
    taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPT)
    if rows:
        tax_final = round(taxable_final * TAX_RATE, 2) if taxable_final > 0 else 0.0
        if tax_final > 0:
            total_tax_paid += tax_final
            rows[-1]["cash"]          = round(rows[-1]["cash"] - tax_final, 2)
            rows[-1]["total_assets"]  = round(rows[-1]["total_assets"] - tax_final, 2)
            rows[-1]["return_pct"]    = round((rows[-1]["total_assets"] / CAPITAL - 1) * 100, 4)
            rows[-1]["annual_profit_ytd"] = 0.0
            existing = rows[-1].get("tax_deducted", "")
            rows[-1]["tax_deducted"] = round((float(existing) if existing != "" else 0.0) + tax_final, 2)
        annual_taxes[current_tax_year] = {
            "tax": tax_final if tax_final > 0 else 0.0,
            "total_before": (rows[-1]["total_assets"] + tax_final) if tax_final > 0 else rows[-1]["total_assets"],
            "deducted_on":  rows[-1]["date"] if tax_final > 0 else None,
        }

    df = pd.DataFrame(rows)
    df.index = close.index
    return df, annual_taxes


# ── 성과 계산 ─────────────────────────────────────────────────────

def _calc_perf(df: pd.DataFrame, annual_taxes: dict) -> dict:
    ta    = df["total_assets"].astype(float)
    final = float(ta.iloc[-1])
    dates = pd.to_datetime(df["date"])
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1 / 365.25)
    cagr  = ((final / CAPITAL) ** (1 / years) - 1) * 100
    peak  = CAPITAL; mdd = 0.0
    for v in ta:
        if v > peak:  peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd:  mdd = dd
    buy_cnt  = int((df["action"] == "BUY").sum())
    sell_cnt = int((df["action"].isin(["SELL", "SELL_QQQ"])).sum())
    qqq_cnt  = int((df["action"] == "SELL_QQQ").sum())
    total_tax = sum(v.get("tax", 0) for v in annual_taxes.values())
    return {
        "total_return_pct": round((final / CAPITAL - 1) * 100, 2),
        "cagr_pct":         round(cagr, 2),
        "mdd_pct":          round(mdd, 2),
        "final_assets":     round(final, 2),
        "total_trades":     buy_cnt + sell_cnt,
        "buy_cnt":          buy_cnt,
        "sell_cnt":         sell_cnt,
        "qqq_cnt":          qqq_cnt,
        "total_tax":        round(total_tax, 0),
        "taxes":            annual_taxes,
    }


# ── Summary 탭 ────────────────────────────────────────────────────

def write_guard_summary_tab(
    ss,
    results_guard: dict,
    results_fng: dict,
    best_params: dict,
):
    """원본 write_fng_summary_tab과 동일한 형태, QQQ Guard 데이터로 교체."""
    import create_rsi_price_target_sheet as rsi2

    COLOR_BUY        = rsi2.COLOR_BUY
    COLOR_SELL       = rsi2.COLOR_SELL
    COLOR_HDR_BG     = rsi2.COLOR_HDR_BG
    COLOR_HDR_FG     = rsi2.COLOR_HDR_FG
    COLOR_TITLE_BG   = rsi2.COLOR_TITLE_BG
    COLOR_SECTION_BG = rsi2.COLOR_SECTION_BG

    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=600, cols=18)

    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[list] = []
    style_rows: dict = {}
    summary_states: dict = {}

    def add_row(values: list):
        rows.append(values)
        return len(rows)

    # ── 타이틀 ──────────────────────────────────────────────────
    add_row(["TQQQ / SOXL  RSI(2) + F&G + QQQ Crash Guard 전략"])
    add_row([f"생성: {now}   |   기간: {START_DATE} ~ {END_DATE}   |   초기자본: ${CAPITAL:,.0f}   |   체결: LOC"])
    add_row([f"최적 F&G 파라미터:  Extreme Fear ≤ {best_params['fear_max']} (매도 보류)   |   "
             f"Extreme Greed ≥ {best_params['greed_min']} (매수 보류)   |   "
             f"QQQ -5% 이하 → 강제매도 + {QQQ_COOLDOWN}일 매수금지"])
    add_row([])

    # ── 성과 비교 ───────────────────────────────────────────────
    add_row(["[ 전략 성과 비교: RSI2+F&G(기존) vs RSI2+F&G+QQQ가드(신규) ]"])
    style_rows["compare_header"] = len(rows)
    add_row(["종목", "전략", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수"])
    style_rows["compare_data_start"] = len(rows) + 1

    for ticker in ["TQQQ", "SOXL"]:
        rf = results_fng[ticker]
        rg = results_guard[ticker]
        add_row([ticker,
                 f"RSI2+F&G(≤{best_params['fear_max']}/≥{best_params['greed_min']})",
                 rf["total_return_pct"], rf["cagr_pct"], rf["mdd_pct"],
                 rf["final_assets"], rf["total_trades"]])
        add_row([ticker,
                 f"RSI2+F&G+QQQ가드(≤-5%→{QQQ_COOLDOWN}일)",
                 rg["total_return_pct"], rg["cagr_pct"], rg["mdd_pct"],
                 rg["final_assets"], rg["total_trades"]])
    add_row([])

    # ── 현재 신호 & 다음날 주문 ─────────────────────────────────
    add_row(["[ 현재 사이클 & 다음날 예약 주문 (RSI2+F&G+QQQ가드 기준) ]"])
    style_rows["action_section"] = len(rows)
    add_row(["종목", "전략명", "현재상태", "현재사이클", "오늘종가", "RSI(2)", "F&G",
             "다음장 BUY 기준가", "다음장 SELL 기준가", "추천 예약주문",
             "직전 사이클 정산현금($)", "총수익률(%)", "거래횟수"])
    style_rows["action_header"] = len(rows)

    for ticker in ["TQQQ", "SOXL"]:
        cfg  = {**TICKER_CONFIG[ticker], **best_params}
        df   = results_guard[ticker]["df"]
        last = df.iloc[-1]

        holdings    = float(last["holdings"])
        today_close = float(last["close"])
        rsi_col     = f"rsi{cfg['period']}"
        current_rsi = float(last[rsi_col]) if last[rsi_col] != "" else np.nan
        current_fng = int(last["fng"])

        closes_a = df["close"].astype(float).values
        alpha_t  = 1.0 / cfg["period"]
        mu = np.zeros(len(closes_a)); md = np.zeros(len(closes_a))
        for i in range(1, len(closes_a)):
            d = closes_a[i] - closes_a[i - 1]
            mu[i] = alpha_t * max(d, 0.0) + (1 - alpha_t) * mu[i - 1]
            md[i] = alpha_t * max(-d, 0.0) + (1 - alpha_t) * md[i - 1]
        nb, ns = _build_next_day_limits(closes_a, mu, md, cfg["buy_below"], cfg["sell_above"], alpha_t)
        buy_next_px  = float(nb[-1]) if not np.isnan(nb[-1]) else ""
        sell_next_px = float(ns[-1]) if not np.isnan(ns[-1]) else ""

        completed, open_cycle = _extract_cycle_state_fng(df)
        settled_cash     = completed[-1]["end_cash"] if completed else CAPITAL
        current_cycle_no = open_cycle["cycle_no"] if open_cycle else len(completed)
        current_state    = "주식 보유" if holdings > 0 else "현금 보유"
        cd_days          = int(last.get("cooldown_days", 0) or 0)

        if holdings == 0:
            if cd_days > 0:
                next_action = (f"🔒 QQQ 쿨다운 {cd_days}일 남음. "
                               f"해제 후 LOC 매수 기준가 ${buy_next_px:.2f}"
                               if buy_next_px != "" else f"🔒 QQQ 쿨다운 {cd_days}일 남음")
            elif current_fng >= cfg["greed_min"]:
                next_action = (f"⛔ 매수 보류 (F&G={current_fng} ≥ {cfg['greed_min']}). "
                               f"F&G가 {cfg['greed_min']-1} 이하로 내려오면 LOC 매수 기준가 ${buy_next_px:.2f}"
                               if buy_next_px != "" else f"⛔ 매수 보류 (F&G={current_fng} ≥ {cfg['greed_min']})")
            else:
                next_action = (f"다음 장 시작 전에  LOC 매수 주문을  ${buy_next_px:.2f}  에 걸어주세요."
                               if buy_next_px != "" else "매수 기준가 계산불가")
        else:
            if current_fng <= cfg["fear_max"]:
                next_action = (f"⛔ 매도 보류 (F&G={current_fng} ≤ {cfg['fear_max']}). "
                               f"F&G가 {cfg['fear_max']+1} 이상으로 올라오면 LOC 매도 기준가 ${sell_next_px:.2f}"
                               if sell_next_px != "" else f"⛔ 매도 보류 (F&G={current_fng} ≤ {cfg['fear_max']})")
            else:
                next_action = (f"다음 장 시작 전에  LOC 매도 주문을  ${sell_next_px:.2f}  에 걸어주세요."
                               if sell_next_px != "" else "매도 기준가 계산불가")

        summary_states[ticker] = {
            "current_state": current_state, "next_action": next_action,
        }
        add_row([
            ticker,
            f"RSI2_{cfg['buy_below']}_{cfg['sell_above']}+F&G+QQQ가드",
            current_state, current_cycle_no, today_close,
            round(float(current_rsi), 2) if not np.isnan(current_rsi) else "",
            current_fng,
            round(float(buy_next_px), 2)  if buy_next_px  != "" else "",
            round(float(sell_next_px), 2) if sell_next_px != "" else "",
            next_action, settled_cash,
            results_guard[ticker]["total_return_pct"],
            results_guard[ticker]["total_trades"],
        ])
        style_rows[f"order_{ticker.lower()}"] = len(rows) + 1
        add_row([f"📌 {next_action}"])
    add_row([])

    # ── 연도별 수익률 ────────────────────────────────────────────
    add_row(["[ 연도별 수익률 (RSI2+F&G+QQQ가드) ]"])
    style_rows["yearly_section"] = len(rows)
    current_year = datetime.now().year
    all_year_labels: list[str] = []
    yearly_map: dict[str, dict] = {}

    for ticker in ["TQQQ", "SOXL"]:
        df   = results_guard[ticker]["df"]
        df_y = df.copy()
        df_y["year"] = pd.to_datetime(df_y["date"]).dt.year
        yr_dict: dict[str, float] = {}
        ticker_taxes = results_guard[ticker].get("taxes", {})
        for yr, grp in df_y.groupby("year"):
            yr_start = float(grp.iloc[0]["total_assets"])
            yr_end   = float(grp.iloc[-1]["total_assets"])
            if yr == current_year:
                # 진행중 연도: 마지막 행에 이미 차감된 예상 양도세를 더해 세전 기준으로 통일
                final_tax = float(ticker_taxes.get(yr, {}).get("tax", 0))
                yr_end += final_tax
            pct = round((yr_end / yr_start - 1) * 100, 2)
            label = f"{yr}년(진행중)" if yr == current_year else f"{yr}년"
            yr_dict[label] = pct
            if label not in all_year_labels:
                all_year_labels.append(label)
        yearly_map[ticker] = yr_dict
    all_year_labels = sorted(all_year_labels)

    add_row(["종목"] + all_year_labels)
    style_rows["yearly_header"] = len(rows)
    for ticker in ["TQQQ", "SOXL"]:
        add_row([ticker] + [yearly_map[ticker].get(y, "") for y in all_year_labels])
    style_rows["yearly_end"] = len(rows)
    add_row([])

    # ── 사이클 비교표 ─────────────────────────────────────────────
    add_row(["[ 사이클 비교표 (RSI2+F&G+QQQ가드) ]"])
    style_rows["cycle_section"] = len(rows)
    add_row([
        "Cycle #",
        "TQQQ 시작일", "TQQQ 시작현금($)", "TQQQ 매수가", "TQQQ 종료일", "TQQQ 매도가", "TQQQ 종료현금($)", "TQQQ 수익률/바",
        "",
        "SOXL 시작일", "SOXL 시작현금($)", "SOXL 매수가", "SOXL 종료일", "SOXL 매도가", "SOXL 종료현금($)", "SOXL 수익률/바",
    ])
    style_rows["cycle_header"] = len(rows)

    cycle_tables: dict = {}
    cycle_render_rows: list[dict] = []
    max_pos_ret = 0.0; max_neg_ret_abs = 0.0

    for ticker in ["TQQQ", "SOXL"]:
        completed, open_cycle = _extract_cycle_state_fng(results_guard[ticker]["df"])
        cycle_tables[ticker] = {
            "completed": completed, "open": open_cycle,
            "taxes": results_guard[ticker].get("taxes", {}),
        }
        for cyc in completed:
            p = float(cyc["cycle_return_pct"])
            if p >= 0: max_pos_ret = max(max_pos_ret, p)
            else:      max_neg_ret_abs = max(max_neg_ret_abs, abs(p))

    def _build_cycle_timeline(cycles: list[dict], taxes: dict) -> list[dict]:
        timeline: list[dict] = []
        tax_events: list[dict] = []
        last_sell = max((str(c.get("sell_date", "")) for c in cycles), default="") if cycles else ""
        for year, info in sorted(taxes.items()):
            d_on = str(info.get("deducted_on", ""))
            if not d_on:
                continue
            if last_sell and d_on > last_sell:
                continue
            tax_events.append({"kind": "tax", "year": int(year), "deducted_on": d_on})

        if not cycles:
            return tax_events

        inserts_after: dict[int, list[dict]] = {}
        pre_events: list[dict] = []
        first_buy = str(cycles[0].get("buy_date", ""))

        for ev in tax_events:
            td = ev["deducted_on"]; placed = False
            for i, cyc in enumerate(cycles):
                sd = str(cyc.get("sell_date", ""))
                nx = cycles[i+1] if i+1 < len(cycles) else None
                nb_d = str(nx.get("buy_date", "")) if nx else ""
                if sd and td >= sd and (not nb_d or td < nb_d):
                    inserts_after.setdefault(i, []).append(ev); placed = True; break
            if not placed:
                h = -1
                for i, cyc in enumerate(cycles):
                    bd = str(cyc.get("buy_date", ""))
                    if bd and bd <= td: h = i
                if h >= 0:
                    inserts_after.setdefault(h, []).append(ev); placed = True
            if not placed and first_buy and td < first_buy:
                pre_events.append(ev)

        for ev in pre_events:
            timeline.append(ev)
        for i, cyc in enumerate(cycles):
            timeline.append({"kind": "cycle", "data": cyc})
            for ev in inserts_after.get(i, []):
                timeline.append(ev)
        return timeline

    taxes_t = cycle_tables["TQQQ"]["taxes"]
    taxes_s = cycle_tables["SOXL"]["taxes"]
    timeline_t = _build_cycle_timeline(cycle_tables["TQQQ"]["completed"], taxes_t)
    timeline_s = _build_cycle_timeline(cycle_tables["SOXL"]["completed"], taxes_s)

    cycle_display_no = 0
    max_tl = max(len(timeline_t), len(timeline_s))
    for i in range(max_tl):
        t_item = timeline_t[i] if i < len(timeline_t) else None
        s_item = timeline_s[i] if i < len(timeline_s) else None

        t_cycle = t_item and t_item.get("kind") == "cycle"
        s_cycle = s_item and s_item.get("kind") == "cycle"
        t_tax   = t_item and t_item.get("kind") == "tax"
        s_tax   = s_item and s_item.get("kind") == "tax"

        if t_cycle or s_cycle:
            cycle_display_no += 1
            cycle_no_cell = cycle_display_no
        else:
            cycle_no_cell = ""

        t_cells = ["", "", "", "", "", "", ""]
        s_cells = ["", "", "", "", "", "", ""]
        t_pct = None; s_pct = None; is_tax_row = False

        if t_cycle:
            td = t_item["data"]
            t_pct = float(td["cycle_return_pct"])
            t_bar = rsi2._bar_text_centered(t_pct, max_pos_ret, max_neg_ret_abs, f"{t_pct:.2f}%")
            t_cells = [td["buy_date"], td["start_cash"], td["buy_price"],
                       td["sell_date"], td["sell_price"], td["end_cash"], t_bar]
        elif t_tax:
            yr = int(t_item["year"])
            ti = taxes_t.get(yr, {}); tax_t = float(ti.get("tax", 0)); tot_t = float(ti.get("total_before", 0))
            pct_t = round(-tax_t / tot_t * 100, 2) if tot_t > 0 else 0.0
            t_cells = ["", "", "", f"{yr}-12-31 기준", "", round(-tax_t, 2), f"▼ -${tax_t:,.0f}  ({pct_t:.2f}%)"]
            is_tax_row = True

        if s_cycle:
            sd = s_item["data"]
            s_pct = float(sd["cycle_return_pct"])
            s_bar = rsi2._bar_text_centered(s_pct, max_pos_ret, max_neg_ret_abs, f"{s_pct:.2f}%")
            s_cells = [sd["buy_date"], sd["start_cash"], sd["buy_price"],
                       sd["sell_date"], sd["sell_price"], sd["end_cash"], s_bar]
        elif s_tax:
            yr = int(s_item["year"])
            si = taxes_s.get(yr, {}); tax_s = float(si.get("tax", 0)); tot_s = float(si.get("total_before", 0))
            pct_s_tax = round(-tax_s / tot_s * 100, 2) if tot_s > 0 else 0.0
            s_cells = ["", "", "", f"{yr}-12-31 기준", "", round(-tax_s, 2), f"▼ -${tax_s:,.0f}  ({pct_s_tax:.2f}%)"]
            is_tax_row = True

        left_label = ""; right_label = ""; tax_side = "none"
        if t_tax and s_tax:
            left_label  = f"★ TQQQ {t_item['year']}년 양도세"
            right_label = f"★ SOXL {s_item['year']}년 양도세"; tax_side = "both"
        elif t_tax:
            left_label  = f"★ TQQQ {t_item['year']}년 양도세"; tax_side = "t"
        elif s_tax:
            right_label = f"★ SOXL {s_item['year']}년 양도세"; tax_side = "s"

        if right_label:
            s_cells[0] = right_label

        add_row([
            left_label if left_label else cycle_no_cell,
            t_cells[0], t_cells[1], t_cells[2], t_cells[3], t_cells[4], t_cells[5], t_cells[6],
            "",
            s_cells[0], s_cells[1], s_cells[2], s_cells[3], s_cells[4], s_cells[5], s_cells[6],
        ])
        cycle_render_rows.append({
            "row_no": len(rows), "t_pct": t_pct, "s_pct": s_pct,
            "is_tax": is_tax_row, "tax_side": tax_side,
        })
    add_row([])

    # ── QQQ Guard 파라미터 ───────────────────────────────────────
    add_row(["[ QQQ Crash Guard + F&G 파라미터 ]"])
    style_rows["opt_section"] = len(rows)
    add_row(["파라미터", "값", "설명"])
    add_row(["fear_max",   best_params["fear_max"],  f"F&G ≤ 이 값 이면 Extreme Fear → SELL 신호 보류"])
    add_row(["greed_min",  best_params["greed_min"], f"F&G ≥ 이 값 이면 Extreme Greed → BUY  신호 보류"])
    add_row(["QQQ 트리거", "-5.0%", f"QQQ 당일 -5% 이하 → 즉시 강제매도 + {QQQ_COOLDOWN}일 매수금지"])
    add_row(["쿨다운 기간", f"{QQQ_COOLDOWN}일", "QQQ 급락 후 매수 금지 기간 (캘린더 일수)"])

    # ── 저장 ─────────────────────────────────────────────────────
    ws.update(range_name=f"A1:P{len(rows)}", values=rows)
    print(f"[GoogleSheets] Summary 내용 저장 완료 ({len(rows)}행)")

    # ── 셀 서식 ───────────────────────────────────────────────────
    sid = ws.id
    requests = [
        # 타이틀 (1행)
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_TITLE_BG,
                "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True, "fontSize": 16},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # F&G/QQQ 파라미터 행 (3행)
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": 3,
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.95, "green": 0.85, "blue": 0.6},
                "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 성과비교 섹션 타이틀
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["compare_header"] - 1,
                      "endRowIndex":   style_rows["compare_header"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 성과비교 헤더
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["compare_data_start"] - 2,
                      "endRowIndex":   style_rows["compare_data_start"] - 1,
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_HDR_BG,
                "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 현재 신호 섹션 타이틀
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["action_section"] - 1,
                      "endRowIndex":   style_rows["action_section"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 현재 신호 헤더
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["action_header"] - 1,
                      "endRowIndex":   style_rows["action_header"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_HDR_BG,
                "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 연도별 섹션 타이틀
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["yearly_section"] - 1,
                      "endRowIndex":   style_rows["yearly_section"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 연도별 헤더
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["yearly_header"] - 1,
                      "endRowIndex":   style_rows["yearly_header"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_HDR_BG,
                "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 파라미터 섹션 타이틀
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["opt_section"] - 1,
                      "endRowIndex":   style_rows["opt_section"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.9, "green": 0.95, "blue": 0.8},
                "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 사이클 비교표 섹션 타이틀
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["cycle_section"] - 1,
                      "endRowIndex":   style_rows["cycle_section"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 사이클 헤더
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["cycle_header"] - 1,
                      "endRowIndex":   style_rows["cycle_header"],
                      "startColumnIndex": 0, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_HDR_BG,
                "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 사이클 데이터 흰색 초기화
        {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": style_rows["cycle_header"],
                      "endRowIndex":   style_rows["opt_section"] - 1,
                      "startColumnIndex": 0, "endColumnIndex": 16},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
            }},
            "fields": "userEnteredFormat.backgroundColor",
        }},
        # 구분 열 (열 I = 8번)
        {"repeatCell": {
            "range": {"sheetId": sid, "startColumnIndex": 8, "endColumnIndex": 9},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.965, "green": 0.965, "blue": 0.965},
            }},
            "fields": "userEnteredFormat.backgroundColor",
        }},
        # 열 너비
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 16},
            "properties": {"pixelSize": 130}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 9, "endIndex": 10},
            "properties": {"pixelSize": 380}, "fields": "pixelSize",
        }},
        # 프리즈
        {"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 3}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]

    # 현재 신호 행 색상
    ticker_data_rows = {
        "TQQQ": style_rows["action_header"] + 1,
        "SOXL": style_rows["action_header"] + 3,
    }
    for ticker, row_no in ticker_data_rows.items():
        na = summary_states[ticker]["next_action"]
        bg = ({"red": 0.97, "green": 0.97, "blue": 0.80} if "보류" in na
              else COLOR_BUY if "매수" in na else COLOR_SELL)
        requests.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": row_no - 1, "endRowIndex": row_no,
                      "startColumnIndex": 0, "endColumnIndex": 14},
            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
            "fields": "userEnteredFormat.backgroundColor",
        }})
        order_row = style_rows.get(f"order_{ticker.lower()}")
        if order_row:
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": order_row - 1, "endRowIndex": order_row,
                          "startColumnIndex": 0, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": bg,
                    "textFormat": {"bold": True, "fontSize": 13},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})

    # 연도별 수익률 색상
    for row_offset, ticker in enumerate(["TQQQ", "SOXL"]):
        yr_row = style_rows["yearly_header"] + 1 + row_offset
        for col_i, yr_label in enumerate(all_year_labels, start=1):
            pct = yearly_map[ticker].get(yr_label)
            if pct is not None:
                shade = ({"red": 0.98, "green": 0.55, "blue": 0.55} if pct < 0
                         else {"red": 0.55, "green": 0.75, "blue": 0.98})
                requests.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": yr_row - 1, "endRowIndex": yr_row,
                              "startColumnIndex": col_i, "endColumnIndex": col_i + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": shade,
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                }})

    # 사이클 바 셀 색상 + 양도세 행 색상
    TAX_BG  = {"red": 1.0, "green": 0.95, "blue": 0.6}
    TAX_FG  = {"red": 0.5, "green": 0.1,  "blue": 0.0}
    for rm in cycle_render_rows:
        rn = rm["row_no"]
        if rm["t_pct"] is not None:
            shade = rsi2._shade_for_centered(float(rm["t_pct"]))
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": rn - 1, "endRowIndex": rn,
                          "startColumnIndex": 7, "endColumnIndex": 8},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": shade,
                    "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        if rm["s_pct"] is not None:
            shade = rsi2._shade_for_centered(float(rm["s_pct"]))
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": rn - 1, "endRowIndex": rn,
                          "startColumnIndex": 15, "endColumnIndex": 16},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": shade,
                    "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        if rm["is_tax"]:
            side = rm.get("tax_side", "none")
            tax_cols = ([0, 4, 6, 7]          if side == "t"
                        else [9, 12, 14, 15]  if side == "s"
                        else [0, 4, 6, 7, 9, 12, 14, 15])
            for col in tax_cols:
                requests.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": rn - 1, "endRowIndex": rn,
                              "startColumnIndex": col, "endColumnIndex": col + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": TAX_BG,
                        "textFormat": {"bold": True, "foregroundColor": TAX_FG},
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }})

    ws.spreadsheet.batch_update({"requests": requests})
    print("[GoogleSheets] Summary 서식 적용 완료")


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ── Daily 탭 (기존 write_fng_daily_tab 재활용) ────────────────────

def write_guard_daily_tab(ss, ticker: str, df: pd.DataFrame, cfg: dict, perf: dict, best_params: dict):
    """기존 write_fng_daily_tab과 동일, 메타 행 1줄만 QQQ가드 반영."""
    headers = [c for c in df.columns if c not in ("qqq_chg_pct", "cooldown_days")]
    # QQQ 전용 컬럼은 끝에 추가
    headers += [c for c in ["qqq_chg_pct", "cooldown_days"] if c in df.columns]

    title = f"{ticker}_매매기준가"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1500, len(df) + 10), cols=len(headers) + 2)

    meta = [
        [f"{ticker}  —  RSI(2)+F&G+QQQ가드  "
         f"매수: RSI<{cfg['buy_below']} & F&G<{best_params['greed_min']}  /  "
         f"매도: RSI>{cfg['sell_above']} & F&G>{best_params['fear_max']}  /  "
         f"QQQ≤-5%→강제매도+{QQQ_COOLDOWN}일"],
        [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%"
         f"   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,.0f}"],
        [f"기간: {START_DATE} ~ {END_DATE}   거래: {perf['total_trades']}회   체결: LOC"
         f"   QQQ강제매도: {perf.get('qqq_cnt', 0)}회"],
        [f"F&G: Fear≤{best_params['fear_max']}→SELL보류  |  Greed≥{best_params['greed_min']}→BUY보류  |  "
         f"QQQ -5% 이하→강제매도+{QQQ_COOLDOWN}일매수금지"],
        headers,
    ]
    data_row0  = len(meta)
    col_letter = _col_letter(len(headers))
    ws.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)

    values = [
        [str(row.get(h, "")) if not (isinstance(row.get(h, ""), float) and np.isnan(row.get(h, 0.0))) else ""
         for h in headers]
        for _, row in df.iterrows()
    ]
    if values:
        ws.update(range_name=f"A{data_row0+1}:{col_letter}{data_row0+len(values)}", values=values)

    # 기본 서식 (헤더 색)
    sid = ws.id
    COLOR_HDR_BG = {"red": 0.267, "green": 0.447, "blue": 0.769}
    COLOR_HDR_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
    COLOR_BUY    = {"red": 0.714, "green": 0.933, "blue": 0.714}
    COLOR_SELL   = {"red": 1.0,   "green": 0.8,   "blue": 0.8}

    requests = [
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": data_row0 - 1, "endRowIndex": data_row0,
                      "startColumnIndex": 0, "endColumnIndex": len(headers)},
            "cell": {"userEnteredFormat": {
                "backgroundColor": COLOR_HDR_BG,
                "textFormat": {"bold": True, "foregroundColor": COLOR_HDR_FG},
            }},
            "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat",
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": data_row0}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]

    action_col = headers.index("action") if "action" in headers else -1
    if action_col >= 0:
        for row_idx, (_, row) in enumerate(df.iterrows()):
            act = str(row.get("action", ""))
            if act == "BUY":
                requests.append({"repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": data_row0 + row_idx,
                              "endRowIndex":   data_row0 + row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": len(headers)},
                    "cell": {"userEnteredFormat": {"backgroundColor": COLOR_BUY}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})
            elif act in ("SELL", "SELL_QQQ"):
                requests.append({"repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": data_row0 + row_idx,
                              "endRowIndex":   data_row0 + row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": len(headers)},
                    "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SELL}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})

    ws.spreadsheet.batch_update({"requests": requests})
    trades = int((df["action"].isin(["BUY", "SELL", "SELL_QQQ"])).sum())
    qqq_c  = int((df["action"] == "SELL_QQQ").sum())
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행, 거래 {trades}회, QQQ강제매도 {qqq_c}회)")


# ── main ─────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"RSI(2)+F&G+QQQ Crash Guard 시트 생성  {END_DATE}")
    print(f"기간: {START_DATE} ~ {END_DATE}  /  기존 F&G 시트와 동일 형태")
    print("=" * 70)

    # 가격 데이터 다운로드
    print("\n[데이터] 가격 다운로드...")
    import yfinance as yf

    def _download(ticker):
        raw = yf.download(ticker, start=START_DATE, end=END_DATE,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            s = raw["Close"][ticker]
        else:
            s = raw["Close"]
        s.index = pd.to_datetime(s.index)
        return s.dropna().rename(ticker)

    close_map = {t: _download(t) for t in ["TQQQ", "SOXL"]}
    qqq_close = _download("QQQ")
    for t, s in close_map.items():
        print(f"  {t}: {len(s)}일")
    print(f"  QQQ: {len(qqq_close)}일")

    # F&G 데이터
    print("\n[FnG] 히스토리 로딩...")
    fng_raw = load_fng_history()
    sample_dates = close_map["TQQQ"].index
    fng = fng_raw.reindex(sample_dates, method="ffill").fillna(50).astype(int)
    try:
        live = fetch_fear_greed()
        fng.iloc[-1] = int(live["value"])
        print(f"  실시간 동기화: {live['value']} ({live.get('source', 'cnn')})")
    except Exception as e:
        print(f"  실시간 동기화 실패: {e}")
    print(f"  F&G 준비 완료 ({fng.index.min().date()} ~ {fng.index.max().date()})")

    best_params = {"fear_max": 25, "greed_min": 90}

    # F&G 단독 시뮬레이션 (비교용)
    print("\n[RSI2+F&G] 시뮬레이션...")
    results_fng = {}
    for ticker in ["TQQQ", "SOXL"]:
        cfg = TICKER_CONFIG[ticker]
        df, taxes = simulate_with_fng(
            close_map[ticker], fng,
            period=cfg["period"], buy_below=cfg["buy_below"], sell_above=cfg["sell_above"],
            fear_max=best_params["fear_max"], greed_min=best_params["greed_min"],
        )
        from create_nonsplit_best_algo_sheet import calc_perf
        total_ret, cagr, mdd, final = calc_perf(df["total_assets"])
        trades = int((df["action"] != "HOLD").sum())
        results_fng[ticker] = {
            "total_return_pct": round(total_ret, 2), "cagr_pct": round(cagr, 2),
            "mdd_pct": round(mdd, 2), "final_assets": round(final, 2),
            "total_trades": trades, "df": df, "taxes": taxes,
        }
        print(f"  {ticker}: CAGR {cagr:.1f}%  MDD {mdd:.1f}%  {trades}회")

    # QQQ Guard 시뮬레이션
    print("\n[RSI2+F&G+QQQ가드] 시뮬레이션...")
    results_guard = {}
    for ticker in ["TQQQ", "SOXL"]:
        cfg = {**TICKER_CONFIG[ticker], **best_params}
        df, taxes = simulate_guard(close_map[ticker], fng, qqq_close, cfg)
        perf = _calc_perf(df, taxes)
        results_guard[ticker] = {**perf, "df": df}
        print(f"  {ticker}: CAGR {perf['cagr_pct']:.1f}%  MDD {perf['mdd_pct']:.1f}%"
              f"  QQQ강제매도 {perf['qqq_cnt']}회")

    # Google Sheet 업데이트
    print("\n[GoogleSheets] 시트 업데이트...")
    if SHEET_ID_FILE.exists():
        existing_id = SHEET_ID_FILE.read_text().strip()
    else:
        existing_id = None

    sm = SheetsManager(spreadsheet_id=None)
    gc = sm._get_client()

    sheet_title = f"TQQQ_SOXL_RSI2_FnG_QQQ가드_{END_DATE[:7]}"

    if existing_id:
        try:
            ss = gc.open_by_key(existing_id)
            for ws in ss.worksheets():
                ws.clear()
            print(f"  기존 시트 업데이트: {existing_id}")
        except Exception:
            ss = gc.create(sheet_title)
            SHEET_ID_FILE.write_text(ss.id)
            print(f"  새 시트 생성: {ss.id}")
    else:
        ss = gc.create(sheet_title)
        SHEET_ID_FILE.write_text(ss.id)
        print(f"  새 시트 생성: {ss.id}")

    write_guard_summary_tab(ss, results_guard, results_fng, best_params)

    for ticker in ["TQQQ", "SOXL"]:
        cfg  = {**TICKER_CONFIG[ticker], **best_params}
        df   = results_guard[ticker]["df"]
        perf = {k: v for k, v in results_guard[ticker].items() if k != "df"}
        write_guard_daily_tab(ss, ticker, df, cfg, perf, best_params)

    # Summary + 2개 탭만 유지
    keep = {"Summary", "TQQQ_매매기준가", "SOXL_매매기준가"}
    for ws in ss.worksheets():
        if ws.title not in keep:
            try:
                ss.del_worksheet(ws)
            except Exception:
                pass

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"\n시트 ID: {ss.id}")
    print(f"URL: {url}")
    print(f"\n앱 .env의 QQQ_GUARD_SPREADSHEET_ID를 이 ID로 업데이트:")
    print(f"QQQ_GUARD_SPREADSHEET_ID={ss.id}")
    print("=" * 70)
    return ss.id


if __name__ == "__main__":
    main()
