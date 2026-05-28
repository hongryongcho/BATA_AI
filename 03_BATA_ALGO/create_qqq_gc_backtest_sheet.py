"""
QQQ 골든크로스 매도지연 알고리즘  백테스트 시트 생성
────────────────────────────────────────────────────
포맷: 기존 FnG 프로덕션 시트와 동일한 형식
탭  : Summary / TQQQ_매매기준가 / SOXL_매매기준가
GC지연 발생 행은 TQQQ·SOXL 탭에서 연보라색으로 표시

알고리즘:
  Base  : RSI(2) + F&G + QQQ Crash Guard (-5%→10일)
  GC변형: Base + 보유중 QQQ MA50>MA200 신규발생 시 SELL +12일 지연 (사이클당 1회)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from create_qqq_golden_cross_backtest import (
    download_close, compute_qqq_gc, simulate, calc_perf, yearly_returns,
    START_DATE, END_DATE, CAPITAL, TAX_RATE, TAX_EXEMPT,
    QQQ_CRASH_PCT, QQQ_COOLDOWN, GC_MA_FAST, GC_MA_SLOW, GC_DELAY_DAYS,
    TICKER_CONFIG,
)

# ── 시트 헤더 (프로덕션 + gc_on 추가) ────────────────────────────────────
GC_HEADERS = [
    "date", "close", "chg_pct", "fng", "rsi2",
    "gc_on",
    "fng_blocked",
    "buy_limit_expected_px", "sell_limit_expected_px",
    "action", "trade_qty", "buy_cash_used",
    "holdings", "cash", "total_assets",
    "return_pct", "annual_profit_ytd", "tax_deducted",
    "qqq_chg_pct", "cooldown_days",
]

# ── 색상 상수 (프로덕션과 동일) ───────────────────────────────────────────
C_TITLE_BG = {"red": 0.098, "green": 0.180, "blue": 0.298}
C_META_BG  = {"red": 0.855, "green": 0.914, "blue": 0.969}
C_SEC_BG   = {"red": 0.780, "green": 0.878, "blue": 0.996}
C_HDR_BG   = {"red": 0.267, "green": 0.447, "blue": 0.769}
C_HDR_FG   = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
C_PIN_BUY  = {"red": 0.714, "green": 0.933, "blue": 0.714}
C_PIN_SELL = {"red": 1.0,   "green": 0.800, "blue": 0.800}
C_PIN_HOLD = {"red": 1.0,   "green": 0.965, "blue": 0.804}
C_TAX_S    = {"red": 1.0,   "green": 1.0,   "blue": 0.600}
C_RET_POS  = {"red": 1.0,   "green": 0.878, "blue": 0.878}
C_RET_NEG  = {"red": 0.816, "green": 0.882, "blue": 1.0}
C_BUY      = {"red": 0.714, "green": 0.933, "blue": 0.714}
C_SELL     = {"red": 1.0,   "green": 0.800, "blue": 0.800}
C_QQQ      = {"red": 1.0,   "green": 0.600, "blue": 0.200}
C_TAX      = {"red": 1.0,   "green": 1.0,   "blue": 0.600}
C_GC_DELAY = {"red": 0.878, "green": 0.753, "blue": 1.0}   # 연보라 (GC지연)
C_WHITE    = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
C_BLACK    = {"red": 0.0,   "green": 0.0,   "blue": 0.0}


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ── 사이클 추출 (GC 지연 여부 포함) ─────────────────────────────────────

def _extract_cycles_gc(df: pd.DataFrame) -> tuple[list[dict], dict | None]:
    """BUY → SELL/SELL_QQQ 쌍 추출. GC 지연 발생 여부 포함."""
    completed = []
    current_buy: dict | None = None
    cycle_no = 0

    for _, row in df.iterrows():
        action  = str(row.get("action", ""))
        blocked = str(row.get("fng_blocked", ""))

        if action == "BUY":
            cycle_no += 1
            used = row.get("buy_cash_used", "")
            try:
                start_cash = float(used) if used not in ("", None) else CAPITAL
            except (ValueError, TypeError):
                start_cash = CAPITAL
            if start_cash <= 0:
                start_cash = CAPITAL
            current_buy = {
                "cycle_no":    cycle_no,
                "buy_date":    str(row["date"]),
                "buy_price":   float(row["close"]),
                "buy_rsi":     row.get("rsi2", ""),
                "start_cash":  round(float(start_cash), 2),
                "had_gc_delay": False,
            }
        elif current_buy is not None and action == "HOLD":
            if any(k in blocked for k in ("SELL지연(GC", "GC지연대기", "GC지연해제", "GC지연후매도")):
                current_buy["had_gc_delay"] = True
        elif action in ("SELL", "SELL_QQQ") and current_buy is not None:
            end_cash = float(row["cash"])
            tax_val  = row.get("tax_deducted", "")
            try:
                tax_num = float(tax_val) if tax_val not in ("", None) else 0.0
                if tax_num > 0:
                    end_cash += tax_num
            except (ValueError, TypeError):
                pass
            start_cash = float(current_buy["start_cash"])
            completed.append({
                **current_buy,
                "sell_date":           str(row["date"]),
                "sell_price":          float(row["close"]),
                "sell_rsi":            row.get("rsi2", ""),
                "is_qqq_guard":        action == "SELL_QQQ",
                "is_gc_delay_sell":    "GC지연후매도" in blocked,
                "end_cash":            round(end_cash, 2),
                "cycle_return_pct":    round((end_cash / start_cash - 1) * 100, 2),
                "cycle_return_amount": round(end_cash - start_cash, 2),
            })
            current_buy = None

    open_cycle: dict | None = None
    if current_buy is not None:
        current_assets = float(df.iloc[-1]["total_assets"])
        start_cash = float(current_buy["start_cash"])
        open_cycle = {
            **current_buy,
            "sell_date":           "진행중",
            "sell_price":          float(df.iloc[-1]["close"]),
            "sell_rsi":            "",
            "is_qqq_guard":        False,
            "is_gc_delay_sell":    False,
            "end_cash":            round(current_assets, 2),
            "cycle_return_pct":    round((current_assets / start_cash - 1) * 100, 2),
            "cycle_return_amount": round(current_assets - start_cash, 2),
        }

    return completed, open_cycle


# ── 성과 dict → 프로덕션 perf 키로 변환 ─────────────────────────────────

def _to_perf(p: dict) -> dict:
    return {
        "total_ret": p["total_return_pct"],
        "cagr":      p["cagr_pct"],
        "mdd":       p["mdd_pct"],
        "final":     p["final_assets"],
        "buy_cnt":   p["buy_count"],
        "sell_cnt":  p["sell_count"],
        "qqq_cnt":   p["sell_qqq_count"],
        "total_tax": p["total_tax_paid"],
        "gc_delay_initiated": p.get("gc_delay_initiated", 0),
        "gc_delay_executed":  p.get("gc_delay_executed", 0),
    }


# ── 현재 상태 (마지막 행 기준) ───────────────────────────────────────────

def _last_state(df: pd.DataFrame, ticker: str, cfg: dict, perf: dict) -> dict:
    last = df.iloc[-1]
    holdings  = float(last.get("holdings", 0))
    buy_limit = last.get("buy_limit_expected_px", "")
    sell_limit = last.get("sell_limit_expected_px", "")
    cd  = last.get("cooldown_days", "")
    gc  = str(last.get("gc_on", "")) == "Y"
    rsi = last.get("rsi2", "")
    qqq = last.get("qqq_chg_pct", "")

    if holdings > 0:
        base_state = "보유중"
        if gc:
            base_state += "(GC활성)"
        next_action = f"SELL 기준가 {sell_limit} 이상 시 예약매도"
    elif cd:
        base_state = f"현금(QQQ쿨다운 {cd}일 남음)"
        next_action = f"BUY 기준가 {buy_limit} 이하 시 예약매수"
    else:
        base_state = "현금"
        next_action = f"BUY 기준가 {buy_limit} 이하 시 예약매수"

    return {
        "ticker":        ticker,
        "current_state": base_state,
        "rsi":           rsi,
        "qqq_chg":       qqq,
        "buy_limit":     buy_limit,
        "sell_limit":    sell_limit,
        "next_action":   next_action,
    }


# ── 사이클 바 텍스트 ─────────────────────────────────────────────────────

def _bar_text(pct: float, max_pos: float, max_neg_abs: float, width: int = 28) -> str:
    center = width // 2
    bar_w  = center - 2
    label  = f"{pct:.2f}%"
    if pct > 0 and max_pos > 0:
        filled = max(0, int(round(min(pct / max_pos, 1.0) * bar_w)))
        return " " * (center - 1) + "|" + "█" * filled + "░" * (bar_w - filled) + " " + label
    elif pct < 0 and max_neg_abs > 0:
        filled = max(0, int(round(min(abs(pct) / max_neg_abs, 1.0) * bar_w)))
        return " " * (bar_w - filled) + "█" * filled + "|" + "░" * (center - 1) + " " + label
    else:
        return " " * (center - 1) + "|" + "░" * center + " " + label


# ── 타임라인 빌더 (사이클 + 양도세 행) ──────────────────────────────────

def _build_timeline(cycles: list[dict], taxes: dict) -> list[dict]:
    tax_events = []
    last_sell = max((str(c.get("sell_date", "")) for c in cycles if c.get("sell_date") != "진행중"),
                    default="") if cycles else ""
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


# ── 메인 시트 작성 ───────────────────────────────────────────────────────

def write_gc_backtest_sheet(
    results_base: dict[str, tuple],
    results_gc:   dict[str, tuple],
):
    from sheets_manager import SheetsManager
    from _env_loader import get_spreadsheet_id

    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc_client = sm._get_client()

    title = f"GC매도지연_백테스트_{START_DATE[:4]}_{END_DATE[:4]}"
    print(f"\n[GoogleSheets] 새 스프레드시트 생성: {title}")
    ss  = gc_client.create(title)
    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    cur_yr = datetime.now().year

    # ════════════════════════════════════════════════════════════════
    # ① Summary 탭
    # ════════════════════════════════════════════════════════════════
    ws_sum = ss.sheet1
    ws_sum.update_title("Summary")

    sum_rows: list[list] = []

    # ── 헤더 ──────────────────────────────────────────────────────
    sum_rows.append([
        f"TQQQ / SOXL  RSI(2)+F&G+QQQ가드 vs GC매도지연 백테스트  "
        f"({QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일 / GC MA{GC_MA_FAST}>MA{GC_MA_SLOW} +{GC_DELAY_DAYS}일지연)"
    ])
    sum_rows.append([
        f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   |   "
        f"기간: {START_DATE} ~ {END_DATE}   |   초기자본: ${CAPITAL:,.0f}   |   체결: LOC"
    ])
    sum_rows.append([
        f"GC변형: 보유중 QQQ MA{GC_MA_FAST}>MA{GC_MA_SLOW} 신규발생 → RSI SELL +{GC_DELAY_DAYS}일 지연 (사이클당1회)   |   "
        f"GC지연 행은 연보라(🔵)로 표시"
    ])
    sum_rows.append([])

    # ── 성과 비교표 ───────────────────────────────────────────────
    sum_rows.append([f"[ 전략 성과 비교: Base vs GC매도지연(+{GC_DELAY_DAYS}일) ]"])
    sum_rows.append([
        "종목", "전략", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)",
        "거래횟수", "QQQ강제매도", "GC지연발생", "GC지연→매도", "총양도세($)"
    ])
    for ticker in TICKER_CONFIG:
        df_b, taxes_b, perf_b = results_base[ticker]
        df_g, taxes_g, perf_g = results_gc[ticker]
        cfg_t = TICKER_CONFIG[ticker]
        strat = f"RSI2_{cfg_t['buy_below']}_{cfg_t['sell_above']}+F&G+QQQ가드"
        pb = _to_perf(perf_b)
        pg = _to_perf(perf_g)
        sum_rows.append([
            ticker, strat,
            pb["total_ret"], pb["cagr"], pb["mdd"], pb["final"],
            pb["buy_cnt"], pb["qqq_cnt"], 0, 0, pb["total_tax"],
        ])
        sum_rows.append([
            ticker, f"GC매도지연(+{GC_DELAY_DAYS}일)",
            pg["total_ret"], pg["cagr"], pg["mdd"], pg["final"],
            pg["buy_cnt"], pg["qqq_cnt"],
            pg["gc_delay_initiated"], pg["gc_delay_executed"], pg["total_tax"],
        ])
        diff = [
            "", "▲ 차이(GC-Base)",
            round(pg["total_ret"] - pb["total_ret"], 2),
            round(pg["cagr"]      - pb["cagr"],      2),
            round(pg["mdd"]       - pb["mdd"],        2),
            round(pg["final"]     - pb["final"],      0),
            "", "", "", "", round(pg["total_tax"] - pb["total_tax"], 0),
        ]
        sum_rows.append(diff)
        sum_rows.append([])

    # ── 현재 사이클 (GC알고리즘 기준 마지막 상태) ─────────────────
    sum_rows.append([f"[ 현재 사이클 & 다음날 예약 주문 (GC매도지연 기준) ]"])
    sum_rows.append([
        "종목", "전략명", "현재상태", "현재사이클", "오늘종가", "RSI(2)", "QQQ변화%",
        "다음장 BUY 기준가", "다음장 SELL 기준가", "추천 예약주문",
        "직전 사이클 정산현금($)", "총수익률(%)", "거래횟수",
    ])
    for ticker in TICKER_CONFIG:
        df_g, taxes_g, perf_g = results_gc[ticker]
        pg = _to_perf(perf_g)
        cfg_t = TICKER_CONFIG[ticker]
        state = _last_state(df_g, ticker, cfg_t, perf_g)
        completed, open_cyc = _extract_cycles_gc(df_g)
        settled_cash = completed[-1]["end_cash"] if completed else CAPITAL
        current_cycle_no = open_cyc["cycle_no"] if open_cyc else len(completed)
        today_close = float(df_g.iloc[-1]["close"])
        sum_rows.append([
            ticker,
            f"RSI2_{cfg_t['buy_below']}_{cfg_t['sell_above']}+F&G+QQQ가드+GC+{GC_DELAY_DAYS}일",
            state["current_state"],
            current_cycle_no,
            today_close,
            state["rsi"],
            state["qqq_chg"],
            state["buy_limit"],
            state["sell_limit"],
            state["next_action"],
            settled_cash,
            pg["total_ret"],
            pg["buy_cnt"],
        ])
        au = state["next_action"].upper()
        pin = f"📌 {state['next_action']}"
        sum_rows.append([pin])
    sum_rows.append([])

    # ── 연도별 수익률 (GC 알고리즘 기준, 프로덕션 동일 계산) ──────
    sum_rows.append([f"[ 연도별 수익률 (GC매도지연 / Base 비교) ]"])
    yr_labels: list[str] = []
    yearly_gc:   dict[str, dict] = {}
    yearly_base: dict[str, dict] = {}

    for ticker in TICKER_CONFIG:
        df_b, taxes_b, _ = results_base[ticker]
        df_g, taxes_g, _ = results_gc[ticker]

        def _calc_yr(df, taxes):
            df2 = df.copy()
            df2["year"] = pd.to_datetime(df2["date"]).dt.year
            df2["tax_num"] = pd.to_numeric(df2["tax_deducted"], errors="coerce").fillna(0.0)
            yd: dict[str, float] = {}
            for yr, grp in df2.groupby("year"):
                search = grp.iloc[:-1] if (yr == cur_yr and len(grp) > 1) else grp
                tax_rows = search[search["tax_num"] > 0]
                s = float(tax_rows.iloc[0]["total_assets"]) if not tax_rows.empty else float(grp.iloc[0]["total_assets"])
                if s <= 0:
                    s = CAPITAL
                e = float(grp.iloc[-1]["total_assets"])
                if yr == cur_yr:
                    lt = float(grp.iloc[-1]["tax_num"])
                    if lt > 0:
                        e += lt
                label = f"{yr}년(진행중)" if yr == cur_yr else f"{yr}년"
                yd[label] = round((e / s - 1) * 100, 2)
                if label not in yr_labels:
                    yr_labels.append(label)
            return yd

        yearly_gc[ticker]   = _calc_yr(df_g, taxes_g)
        yearly_base[ticker] = _calc_yr(df_b, taxes_b)

    yr_labels.sort()
    annual_ret_rows: list[dict] = []

    sum_rows.append(["종목", "전략"] + yr_labels)
    for ticker in TICKER_CONFIG:
        # GC 행
        row_idx_gc = len(sum_rows)
        vals_gc = [yearly_gc[ticker].get(y, "") for y in yr_labels]
        sum_rows.append([ticker, f"GC+{GC_DELAY_DAYS}일"] + vals_gc)
        annual_ret_rows.append({"row_idx": row_idx_gc, "values": vals_gc})
        # Base 행
        row_idx_b = len(sum_rows)
        vals_b = [yearly_base[ticker].get(y, "") for y in yr_labels]
        sum_rows.append([ticker, "Base"] + vals_b)
        annual_ret_rows.append({"row_idx": row_idx_b, "values": vals_b})
    sum_rows.append([])

    # ── 사이클 비교표 (GC 알고리즘 기준) ─────────────────────────
    sum_rows.append([f"[ 사이클 비교표 (GC매도지연 / 🔵=GC지연 / 🚨=QQQ강제매도) ]"])
    t_key = "TQQQ"
    s_key = "SOXL"
    sum_rows.append([
        "Cycle #",
        f"{t_key} 시작일", f"{t_key} 시작현금($)", f"{t_key} 매수가",
        f"{t_key} 종료일", f"{t_key} 매도가", f"{t_key} 종료현금($)", f"{t_key} 수익률/바",
        "",
        f"{s_key} 시작일", f"{s_key} 시작현금($)", f"{s_key} 매수가",
        f"{s_key} 종료일", f"{s_key} 매도가", f"{s_key} 종료현금($)", f"{s_key} 수익률/바",
    ])

    taxes_map:    dict[str, dict] = {}
    timeline_map: dict[str, list] = {}
    max_pos = 0.0
    max_neg_abs = 0.0

    for ticker in TICKER_CONFIG:
        df_g, taxes_g, _ = results_gc[ticker]
        completed, open_cyc = _extract_cycles_gc(df_g)
        all_cycles = completed + ([open_cyc] if open_cyc else [])
        taxes_map[ticker]    = taxes_g
        timeline_map[ticker] = _build_timeline(all_cycles, taxes_g)
        for c in completed:
            p = float(c["cycle_return_pct"])
            if p > 0:
                max_pos = max(max_pos, p)
            else:
                max_neg_abs = max(max_neg_abs, abs(p))

    tl_t = timeline_map.get(t_key, [])
    tl_s = timeline_map.get(s_key, [])

    cycle_bar_rows:  list[dict] = []
    cycle_gc_rows:   list[int]  = []   # GC지연 발생 사이클 행 인덱스
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
        this_row_gc = False

        if t_is_cycle:
            c = t_item["data"]
            pct = float(c["cycle_return_pct"])
            t_pct_val = pct
            gc_mark  = "🔵" if c.get("had_gc_delay") else ""
            qqq_mark = "🚨" if c.get("is_qqq_guard") else ""
            t_cells = [
                c["buy_date"], c["start_cash"], c["buy_price"],
                c["sell_date"], c["sell_price"], c["end_cash"],
                gc_mark + qqq_mark + _bar_text(pct, max_pos, max_neg_abs),
            ]
            if c.get("had_gc_delay"):
                this_row_gc = True
        elif t_is_tax:
            yr   = int(t_item["year"])
            info = taxes_map[t_key].get(yr, {})
            tax  = float(info.get("tax", 0))
            tot  = float(info.get("total_before", 0))
            pct_str = f"▼ -${tax:,.0f}  ({(-tax/tot*100):.2f}%)" if tot > 0 else f"▼ -${tax:,.0f}"
            t_cells = ["", "", "", f"{yr}-12-31 기준", "", round(-tax, 2), pct_str]
            left_label = f"★ {t_key} {yr}년 양도세"

        if s_is_cycle:
            c = s_item["data"]
            pct = float(c["cycle_return_pct"])
            s_pct_val = pct
            gc_mark  = "🔵" if c.get("had_gc_delay") else ""
            qqq_mark = "🚨" if c.get("is_qqq_guard") else ""
            s_cells = [
                c["buy_date"], c["start_cash"], c["buy_price"],
                c["sell_date"], c["sell_price"], c["end_cash"],
                gc_mark + qqq_mark + _bar_text(pct, max_pos, max_neg_abs),
            ]
            if c.get("had_gc_delay"):
                this_row_gc = True
        elif s_is_tax:
            yr   = int(s_item["year"])
            info = taxes_map[s_key].get(yr, {})
            tax  = float(info.get("tax", 0))
            tot  = float(info.get("total_before", 0))
            pct_str = f"▼ -${tax:,.0f}  ({(-tax/tot*100):.2f}%)" if tot > 0 else f"▼ -${tax:,.0f}"
            s_cells = [f"★ {s_key} {yr}년 양도세", "", "", f"{yr}-12-31 기준", "", round(-tax, 2), pct_str]

        row_label = left_label if left_label else cycle_cell
        row_idx   = len(sum_rows)
        sum_rows.append([
            row_label,
            t_cells[0], t_cells[1], t_cells[2],
            t_cells[3], t_cells[4], t_cells[5], t_cells[6],
            "",
            s_cells[0], s_cells[1], s_cells[2],
            s_cells[3], s_cells[4], s_cells[5], s_cells[6],
        ])
        if t_pct_val is not None or s_pct_val is not None:
            cycle_bar_rows.append({"row_idx": row_idx, "t_pct": t_pct_val, "s_pct": s_pct_val})
        if this_row_gc:
            cycle_gc_rows.append(row_idx)

    sum_rows.append([])

    # ── Summary 데이터 업로드 ─────────────────────────────────────
    col_l = _col_letter(max(len(r) for r in sum_rows if r))
    ws_sum.update(range_name=f"A1:{col_l}{len(sum_rows)}", values=sum_rows)
    ws_sum_id  = ws_sum.id
    sum_n_cols = max(len(r) for r in sum_rows if r)

    # ── Summary 서식 ──────────────────────────────────────────────
    TQQQ_END_COL   = 8
    SOXL_START_COL = 9
    SOXL_END_COL   = 16

    sum_fmt: list[dict] = [
        {"repeatCell": {   # 전체 초기화
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
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_TITLE_BG,
                    "textFormat": {"foregroundColor": C_HDR_FG, "bold": True, "fontSize": 14}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif ri in (1, 2):
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_META_BG,
                    "textFormat": {"fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif cell0.startswith("[ "):
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_SEC_BG,
                    "textFormat": {"bold": True, "fontSize": 11}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif cell0 in ("종목", "Cycle #"):
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_HDR_BG,
                    "textFormat": {"foregroundColor": C_HDR_FG, "bold": True, "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif cell0.startswith("📌"):
            au  = cell0.upper()
            pin_bg = C_PIN_BUY if "BUY" in au else (C_PIN_SELL if "SELL" in au else C_PIN_HOLD)
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": pin_bg,
                    "textFormat": {"bold": True, "fontSize": 11}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        else:
            if cell0.startswith("★"):
                sum_fmt.append({"repeatCell": {
                    "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                               "startColumnIndex": 0, "endColumnIndex": TQQQ_END_COL},
                    "cell": {"userEnteredFormat": {"backgroundColor": C_TAX_S}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})
            if cell9.startswith("★"):
                sum_fmt.append({"repeatCell": {
                    "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                               "startColumnIndex": SOXL_START_COL, "endColumnIndex": SOXL_END_COL},
                    "cell": {"userEnteredFormat": {"backgroundColor": C_TAX_S}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})

    # 연도별 수익률 셀 색상
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
            col_idx = 2 + ci   # col A=종목, col B=전략명, 값은 C부터
            sum_fmt.append({"repeatCell": {
                "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                           "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    # 사이클 바 색상
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

    # GC 지연 사이클 행 → 연보라색 (사이클 테이블에서만)
    for ri in cycle_gc_rows:
        sum_fmt.append({"repeatCell": {
            "range": {"sheetId": ws_sum_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                       "startColumnIndex": 0, "endColumnIndex": sum_n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": C_GC_DELAY}},
            "fields": "userEnteredFormat.backgroundColor",
        }})

    # 상단 3행 고정
    sum_fmt.append({"updateSheetProperties": {
        "properties": {"sheetId": ws_sum_id,
                       "gridProperties": {"frozenRowCount": 3}},
        "fields": "gridProperties.frozenRowCount",
    }})

    ss.batch_update({"requests": sum_fmt})
    print("[GoogleSheets] Summary 저장 및 서식 완료")

    # ════════════════════════════════════════════════════════════════
    # ② TQQQ / SOXL 일별 탭 (GC알고리즘 데이터)
    # ════════════════════════════════════════════════════════════════
    for ticker in TICKER_CONFIG:
        df_g, taxes_g, perf_g = results_gc[ticker]
        pg  = _to_perf(perf_g)
        cfg_t = TICKER_CONFIG[ticker]

        tab_name = f"{ticker}_매매기준가"
        ws = ss.add_worksheet(title=tab_name, rows=max(5500, len(df_g) + 10),
                               cols=len(GC_HEADERS) + 2)
        ws_id = ws.id

        meta = [
            [f"{ticker}  —  GC매도지연 백테스트  "
             f"매수: RSI<{cfg_t['buy_below']} & F&G<{cfg_t['greed_min']}  /  "
             f"매도: RSI>{cfg_t['sell_above']} & F&G>{cfg_t['fear_max']}  /  "
             f"QQQ≤-5%→강제매도+{QQQ_COOLDOWN}일  /  "
             f"GC발생시 SELL +{GC_DELAY_DAYS}일지연"],
            [f"총수익률: {pg['total_ret']}%   CAGR: {pg['cagr']}%"
             f"   MDD: {pg['mdd']}%   최종자산: ${pg['final']:,.0f}"],
            [f"기간: {START_DATE} ~ {END_DATE}   "
             f"거래: {pg['buy_cnt']}회   QQQ강제매도: {pg['qqq_cnt']}회   "
             f"GC지연발생: {pg['gc_delay_initiated']}회   GC지연→실매도: {pg['gc_delay_executed']}회   "
             f"총양도세: ${pg['total_tax']:,.0f}"],
            [f"🔵 연보라: GC지연 발생 행 (SELL지연·대기·해제·지연후매도)   "
             f"🟢 연두: BUY   🔴 연분홍: SELL   🟠 주황: QQQ강제매도   🟡 연노랑: 양도세"],
            GC_HEADERS,
        ]
        data_rows = [[str(row.get(h, "")) for h in GC_HEADERS] for _, row in df_g.iterrows()]
        n_meta = len(meta)
        col_l  = _col_letter(len(GC_HEADERS))
        ws.update(range_name=f"A1:{col_l}{n_meta}", values=meta)
        if data_rows:
            ws.update(range_name=f"A{n_meta+1}:{col_l}{n_meta+len(data_rows)}", values=data_rows)

        # ── 서식 ──────────────────────────────────────────────────
        n_cols = len(GC_HEADERS)
        fmt_requests = [
            {"repeatCell": {   # 타이틀
                "range": {"sheetId": ws_id, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_TITLE_BG,
                    "textFormat": {"foregroundColor": C_HDR_FG, "bold": True, "fontSize": 14}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            {"repeatCell": {   # 메타
                "range": {"sheetId": ws_id, "startRowIndex": 1, "endRowIndex": 4,
                           "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {"backgroundColor": C_META_BG}},
                "fields": "userEnteredFormat.backgroundColor",
            }},
            {"repeatCell": {   # 헤더
                "range": {"sheetId": ws_id, "startRowIndex": 4, "endRowIndex": 5,
                           "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": C_HDR_BG,
                    "textFormat": {"foregroundColor": C_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            {"updateSheetProperties": {   # 상단 5행 고정
                "properties": {"sheetId": ws_id,
                               "gridProperties": {"frozenRowCount": n_meta}},
                "fields": "gridProperties.frozenRowCount",
            }},
        ]

        # 행별 색상 (BUY/SELL/QQQ/세금/GC지연)
        GC_KEYWORDS = ("SELL지연(GC", "GC지연대기", "GC지연해제", "GC지연후매도")
        for i, row in enumerate(df_g.itertuples(index=False)):
            r_idx   = n_meta + i
            action  = str(getattr(row, "action", ""))
            blocked = str(getattr(row, "fng_blocked", ""))
            tax_val = getattr(row, "tax_deducted", "")
            has_tax = tax_val not in ("", None) and str(tax_val) not in ("", "0", "0.0")
            is_gc   = any(k in blocked for k in GC_KEYWORDS)

            if is_gc:
                bg = C_GC_DELAY
            elif action == "BUY":
                bg = C_BUY
            elif action == "SELL_QQQ":
                bg = C_QQQ
            elif action == "SELL":
                bg = C_SELL
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
        gc_cnt = sum(1 for _, r in df_g.iterrows()
                     if any(k in str(r.get("fng_blocked","")) for k in GC_KEYWORDS))
        print(f"[GoogleSheets] {tab_name} 저장 완료 ({len(df_g)}행  "
              f"BUY {pg['buy_cnt']}회  SELL {pg['sell_cnt']}회  "
              f"QQQ {pg['qqq_cnt']}회  GC지연 {gc_cnt}행)")

    print(f"\n[GoogleSheets] URL: {url}")
    return url, ss.id


# ── main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"GC 매도지연 백테스트 시트 생성  {START_DATE} ~ {END_DATE}")
    print(f"Base  : RSI(2)+F&G+QQQ가드 ({QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일)")
    print(f"GC변형: Base + MA{GC_MA_FAST}>MA{GC_MA_SLOW} 보유중 신규발생 시 SELL +{GC_DELAY_DAYS}일 지연")
    print("=" * 70)

    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
        print(f"F&G: {fng_base.index.min().date()} ~ {fng_base.index.max().date()} (이전 구간 50)")
    except Exception as e:
        print(f"F&G 로드 실패: {e} → 전구간 50")
        fng_base = pd.Series(dtype=float)

    print("\n[QQQ] 다운로드...")
    qqq_close = download_close("QQQ")
    print(f"[QQQ] {len(qqq_close)}일 ({qqq_close.index[0].date()} ~ {qqq_close.index[-1].date()})")
    qqq_gc = compute_qqq_gc(qqq_close)

    results_base: dict[str, tuple] = {}
    results_gc:   dict[str, tuple] = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n[{ticker}] 다운로드 및 시뮬레이션...")
        close = download_close(ticker)
        fng   = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        df_b, taxes_b = simulate(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"],
            sell_above=cfg["sell_above"], fear_max=cfg["fear_max"],
            greed_min=cfg["greed_min"], qqq_gc=None,
        )
        perf_b = calc_perf(df_b, taxes_b)
        results_base[ticker] = (df_b, taxes_b, perf_b)

        df_g, taxes_g = simulate(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"],
            sell_above=cfg["sell_above"], fear_max=cfg["fear_max"],
            greed_min=cfg["greed_min"], qqq_gc=qqq_gc, gc_delay_days=GC_DELAY_DAYS,
        )
        perf_g = calc_perf(df_g, taxes_g)
        results_gc[ticker] = (df_g, taxes_g, perf_g)

        pb = _to_perf(perf_b)
        pg = _to_perf(perf_g)
        print(f"  Base  : CAGR {pb['cagr']:.1f}%  MDD {pb['mdd']:.1f}%  최종 ${pb['final']:,.0f}")
        print(f"  GC+{GC_DELAY_DAYS}일: CAGR {pg['cagr']:.1f}%  MDD {pg['mdd']:.1f}%  최종 ${pg['final']:,.0f}  "
              f"GC지연 {pg['gc_delay_initiated']}회")

    print("\n" + "=" * 70)
    print("Google Sheet 저장 중...")
    url, sheet_id = write_gc_backtest_sheet(results_base, results_gc)

    print("\n" + "=" * 70)
    print(f"완료!  URL: {url}")
    print("=" * 70)


if __name__ == "__main__":
    main()
