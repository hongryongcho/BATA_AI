"""
BATA_RSI2_FnG_ALGO
──────────────────────────────────────────────────────────────
RSI(2) 전략 + Fear & Greed 지수 필터

전략 원칙:
  • RSI(2) < buy_below   → BUY 신호  (단, F&G >= greed_min 이면 매수 보류)
  • RSI(2) > sell_above  → SELL 신호 (단, F&G <= fear_max  이면 매도 보류)

최적화:
  fear_max  : 10~45 범위 탐색 (이하면 Extreme Fear → 매도 보류)
  greed_min : 55~90 범위 탐색 (이상이면 Extreme Greed → 매수 보류)
  목적함수 : TQQQ + SOXL 총수익률 합계 최대화

결과:
  - 최적 파라미터 출력
  - RSI2 단독 vs RSI2+F&G 비교 Google Sheet 생성
"""

from __future__ import annotations

import itertools
from datetime import datetime

import numpy as np
import pandas as pd

import create_nonsplit_best_algo_sheet as base
import create_rsi_price_target_sheet as rsi2
import search_optimal_strategies as search_mod
from fear_greed_history import get_fng_for_dates
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

FILE_TITLE = "TQQQ_SOXL_RSI2_FnG_매매기준가"

TICKER_CONFIG = {
    "TQQQ": {"period": 2, "buy_below": 15, "sell_above": 75},
    "SOXL": {"period": 2, "buy_below": 15, "sell_above": 90},
}
CAPITAL = search_mod.CAPITAL

# 최적화 탐색 범위
FEAR_MAX_RANGE   = list(range(10, 46, 5))   # 10, 15, 20, 25, 30, 35, 40, 45
GREED_MIN_RANGE  = list(range(55, 91, 5))   # 55, 60, 65, 70, 75, 80, 85, 90

# Summary/Style 공용 상수 (RSI2 파일에서 가져옴)
COLOR_BUY      = rsi2.COLOR_BUY
COLOR_SELL     = rsi2.COLOR_SELL
COLOR_TITLE_BG = rsi2.COLOR_TITLE_BG
COLOR_HDR_BG   = rsi2.COLOR_HDR_BG
COLOR_HDR_FG   = rsi2.COLOR_HDR_FG
COLOR_SECTION_BG = rsi2.COLOR_SECTION_BG
COLOR_TQQQ_BG  = rsi2.COLOR_TQQQ_BG
COLOR_SOXL_BG  = rsi2.COLOR_SOXL_BG


# ─────────────────────────────────────────────────────────────
# F&G 필터 적용 시뮬레이션
# ─────────────────────────────────────────────────────────────

def simulate_with_fng(
    close: pd.Series,
    fng: pd.Series,
    period: int,
    buy_below: float,
    sell_above: float,
    fear_max: int,
    greed_min: int,
) -> pd.DataFrame:
    """
    RSI2 시뮬레이션에 F&G 필터 추가.
    fear_max  : F&G 가 이 값 이하이면 SELL 보류
    greed_min : F&G 가 이 값 이상이면 BUY  보류
    """
    alpha  = 1.0 / period
    closes = close.values.astype(float)
    n = len(closes)

    # Wilder EWM
    ma_up   = np.zeros(n)
    ma_down = np.zeros(n)
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        ma_up[i]   = alpha * max(delta, 0.0)  + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-delta, 0.0) + (1 - alpha) * ma_down[i - 1]

    with np.errstate(divide="ignore", invalid="ignore"):
        rs  = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[:1] = np.nan

    buy_limits, sell_limits = rsi2.compute_limit_prices(
        closes, ma_up, ma_down, buy_below, sell_above, alpha
    )
    next_buy_limits, next_sell_limits = rsi2.compute_next_day_limit_prices(
        closes, ma_up, ma_down, buy_below, sell_above, alpha
    )

    # F&G 값을 날짜로 매핑
    fng_aligned = fng.reindex(close.index, method="ffill").fillna(50).astype(int)

    cash     = CAPITAL
    holdings = 0.0
    rows     = []
    
    # 양도세 처리: 년도별 수익에서 22% 차감
    TAX_RATE = 0.22
    year_start_date = None
    year_start_assets = CAPITAL
    tax_paid_this_year = False

    for i, (dt, price) in enumerate(close.items()):
        rsi_val = rsi[i]
        fng_val = int(fng_aligned.iloc[i])
        pos_cash = (holdings == 0.0)

        # 실제 체결 판단은 "전일 계산 임계값"으로 수행
        prev_buy_trigger_px = next_buy_limits[i - 1] if i > 0 else np.nan
        prev_sell_trigger_px = next_sell_limits[i - 1] if i > 0 else np.nan

        action       = "HOLD"
        fng_blocked  = ""
        trade_qty    = 0.0

        if i > 0:
            if pos_cash and not np.isnan(prev_buy_trigger_px) and float(price) <= float(prev_buy_trigger_px):
                if fng_val >= greed_min:
                    action = "HOLD"
                    fng_blocked = f"BUY차단(F&G={fng_val}≥{greed_min})"
                else:
                    bought    = cash / price
                    holdings  = bought
                    cash      = 0.0
                    trade_qty = bought
                    action    = "BUY"
            elif (not pos_cash) and not np.isnan(prev_sell_trigger_px) and float(price) >= float(prev_sell_trigger_px):
                if fng_val <= fear_max:
                    action = "HOLD"
                    fng_blocked = f"SELL차단(F&G={fng_val}≤{fear_max})"
                else:
                    trade_qty = -holdings
                    cash      = holdings * price
                    holdings  = 0.0
                    action    = "SELL"

        total_assets = cash + holdings * price

        # 양도세 처리 로직: 년도별 수익의 22% 차감
        # 첫 행 또는 년도 변경 시
        if year_start_date is None:  # 첫 행
            year_start_date = dt
            year_start_assets = total_assets
            tax_paid_this_year = False
        elif dt.year != year_start_date.year:  # 년도 변경
            # 지난해 수익이 있으면 세금 차감 (현금 보유 상태)
            if holdings == 0:
                profit = cash - year_start_assets
                if profit > 0:
                    tax_amount = profit * TAX_RATE
                    cash -= tax_amount
                    total_assets = cash + holdings * price
            year_start_date = dt
            year_start_assets = total_assets
            tax_paid_this_year = False
        
        # SELL이 발생했을 때 세금 차감 (아직 미납 시)
        if action == "SELL" and not tax_paid_this_year:
            profit = total_assets - year_start_assets
            if profit > 0:
                tax_amount = profit * TAX_RATE
                cash -= tax_amount
                total_assets = cash + holdings * price
            tax_paid_this_year = True

        bl = buy_limits[i]
        sl = sell_limits[i]
        bl_expected = round(float(prev_buy_trigger_px), 2) if not np.isnan(prev_buy_trigger_px) else ""
        sl_expected = round(float(prev_sell_trigger_px), 2) if not np.isnan(prev_sell_trigger_px) else ""
        show_buy = round(float(prev_buy_trigger_px), 2) if pos_cash and not np.isnan(prev_buy_trigger_px) else ""
        show_sell = round(float(prev_sell_trigger_px), 2) if (not pos_cash) and not np.isnan(prev_sell_trigger_px) else ""

        prev_price = closes[i - 1] if i > 0 else float(price)
        daily_chg_pct = round((float(price) / prev_price - 1) * 100, 2) if i > 0 else ""

        rows.append({
            "date":           dt.strftime("%Y-%m-%d"),
            "close":          round(float(price), 4),
            "chg_pct":        daily_chg_pct,
            "fng":            fng_val,
            f"rsi{period}":   round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "fng_blocked":    fng_blocked,
            "buy_limit_expected_px":  bl_expected,
            "sell_limit_expected_px": sl_expected,
            "buy_limit_px":   show_buy,
            "sell_limit_px":  show_sell,
            "action":         action,
            "trade_qty":      round(float(trade_qty), 6),
            "holdings":       round(float(holdings), 6),
            "cash":           round(float(cash), 2),
            "total_assets":   round(float(total_assets), 2),
            "return_pct":     round(float((total_assets / CAPITAL - 1) * 100), 4),
        })

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


# ─────────────────────────────────────────────────────────────
# 최적 파라미터 탐색
# ─────────────────────────────────────────────────────────────

def optimize_fng_thresholds(close_map: dict[str, pd.Series], fng: pd.Series) -> dict:
    """
    fear_max × greed_min 그리드 탐색.
    Returns: {
        "fear_max": int, "greed_min": int,
        "best_score": float,  # TQQQ + SOXL 수익률 합계
        "results": {ticker: (total_ret, trades)}
    }
    """
    best = {"fear_max": 25, "greed_min": 75, "best_score": -9999, "results": {}}
    total = len(FEAR_MAX_RANGE) * len(GREED_MIN_RANGE)
    done  = 0

    print(f"[FnG 최적화] 탐색 조합: {total}개 (fear_max×greed_min)")

    for fear_max, greed_min in itertools.product(FEAR_MAX_RANGE, GREED_MIN_RANGE):
        score = 0.0
        results = {}
        for ticker, cfg in TICKER_CONFIG.items():
            close = close_map[ticker]
            df = simulate_with_fng(
                close, fng,
                period=cfg["period"],
                buy_below=cfg["buy_below"],
                sell_above=cfg["sell_above"],
                fear_max=fear_max,
                greed_min=greed_min,
            )
            total_ret, _, _, _ = base.calc_perf(df["total_assets"])
            trades = int((df["action"] != "HOLD").sum())
            results[ticker] = {"total_return_pct": round(total_ret, 2), "total_trades": trades}
            score += total_ret

        done += 1
        if done % 20 == 0:
            print(f"  진행: {done}/{total} | 현재 최고: fear≤{best['fear_max']} greed≥{best['greed_min']} score={best['best_score']:.1f}%")

        if score > best["best_score"]:
            best = {"fear_max": fear_max, "greed_min": greed_min, "best_score": round(score, 2), "results": results}

    print(f"\n[FnG 최적화 완료] 최적: fear_max={best['fear_max']}, greed_min={best['greed_min']}")
    for ticker, r in best["results"].items():
        print(f"  {ticker}: {r['total_return_pct']}%  {r['total_trades']}회")
    return best


# ─────────────────────────────────────────────────────────────
# Google Sheet 작성
# ─────────────────────────────────────────────────────────────

def write_fng_summary_tab(ss, results_fng: dict, results_rsi2: dict, best_params: dict):
    """Summary 탭: RSI2 단독 vs RSI2+F&G 비교 + 현재 상태"""
    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=500, cols=22)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[list] = []
    style_rows: dict = {}

    def add_row(values: list):
        rows.append(values)
        return len(rows)

    # ── 타이틀 ────────────────────────────────────────────────
    add_row(["TQQQ / SOXL  RSI(2) + Fear & Greed 필터 전략"])
    add_row([f"생성: {now}   |   기간: {search_mod.START_DATE} ~ {search_mod.END_DATE}   |   초기자본: $100,000   |   체결: LOC"])
    add_row([f"최적 F&G 파라미터:  Extreme Fear ≤ {best_params['fear_max']} (매도 보류)   |   Extreme Greed ≥ {best_params['greed_min']} (매수 보류)"])
    add_row([])

    # ── 성과 비교 ─────────────────────────────────────────────
    add_row(["[ 전략 성과 비교: RSI2 단독 vs RSI2+F&G ]"])
    style_rows["compare_header"] = len(rows)
    add_row(["종목", "전략", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수"])
    style_rows["compare_data_start"] = len(rows) + 1

    for ticker in search_mod.TICKERS:
        r2 = results_rsi2[ticker]
        rf = results_fng[ticker]
        add_row([ticker, "RSI2 단독", r2["total_return_pct"], r2["cagr_pct"], r2["mdd_pct"], r2["final_assets"], r2["total_trades"]])
        add_row([ticker, f"RSI2+F&G(≤{best_params['fear_max']}/≥{best_params['greed_min']})", rf["total_return_pct"], rf["cagr_pct"], rf["mdd_pct"], rf["final_assets"], rf["total_trades"]])

    add_row([])

    # ── 현재 신호 & 다음날 주문 ───────────────────────────────
    add_row(["[ 현재 사이클 & 다음날 예약 주문 (RSI2+F&G 기준) ]"])
    style_rows["action_section"] = len(rows)
    add_row(["종목", "전략명", "현재상태", "현재사이클", "오늘종가", "RSI(2)", "F&G",
             "다음장 BUY 기준가", "다음장 SELL 기준가", "추천 예약주문",
             "직전 사이클 정산현금($)", "총수익률(%)", "거래횟수"])
    style_rows["action_header"] = len(rows)

    summary_states = {}
    for ticker in search_mod.TICKERS:
        cfg = TICKER_CONFIG[ticker]
        df  = results_fng[ticker]["df"]
        last = df.iloc[-1]
        holdings     = float(last["holdings"])
        today_close  = float(last["close"])
        current_rsi  = float(last[f"rsi{cfg['period']}"]) if last[f"rsi{cfg['period']}"] != "" else np.nan
        current_fng  = int(last["fng"])

        close = df["close"].astype(float)
        alpha = 1.0 / cfg["period"]
        closes_arr = close.values.astype(float)
        ma_up = np.zeros(len(closes_arr))
        ma_down = np.zeros(len(closes_arr))
        for i in range(1, len(closes_arr)):
            delta = closes_arr[i] - closes_arr[i - 1]
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            ma_up[i] = alpha * gain + (1 - alpha) * ma_up[i - 1]
            ma_down[i] = alpha * loss + (1 - alpha) * ma_down[i - 1]

        next_buy_limits, next_sell_limits = rsi2.compute_next_day_limit_prices(
            closes_arr, ma_up, ma_down, cfg["buy_below"], cfg["sell_above"], alpha
        )
        buy_next_px = float(next_buy_limits[-1]) if not np.isnan(next_buy_limits[-1]) else ""
        sell_next_px = float(next_sell_limits[-1]) if not np.isnan(next_sell_limits[-1]) else ""

        completed, open_cycle = rsi2._extract_cycle_state(df)
        settled_cash = completed[-1]["end_cash"] if completed else CAPITAL
        current_cycle_no = open_cycle["cycle_no"] if open_cycle else len(completed)
        current_state = "주식 보유" if holdings > 0 else "현금 보유"

        # 다음날 주문: F&G 필터 반영
        if holdings == 0:
            if current_fng >= best_params["greed_min"]:
                if buy_next_px != "":
                    next_action = (
                        f"⛔ 매수 보류 (F&G={current_fng} ≥ {best_params['greed_min']}). "
                        f"F&G가 {best_params['greed_min'] - 1} 이하로 내려오면 LOC 매수 기준가 ${buy_next_px:.2f}"
                    )
                else:
                    next_action = f"⛔ 매수 보류 (F&G={current_fng} ≥ {best_params['greed_min']})"
            else:
                next_action = (
                    f"다음 장 시작 전에  LOC 매수 주문을  ${buy_next_px:.2f}  에 걸어주세요."
                    if buy_next_px != "" else "매수 기준가 계산불가"
                )
        else:
            if current_fng <= best_params["fear_max"]:
                if sell_next_px != "":
                    next_action = (
                        f"⛔ 매도 보류 (F&G={current_fng} ≤ {best_params['fear_max']}). "
                        f"F&G가 {best_params['fear_max'] + 1} 이상으로 올라오면 LOC 매도 기준가 ${sell_next_px:.2f}"
                    )
                else:
                    next_action = f"⛔ 매도 보류 (F&G={current_fng} ≤ {best_params['fear_max']})"
            else:
                next_action = (
                    f"다음 장 시작 전에  LOC 매도 주문을  ${sell_next_px:.2f}  에 걸어주세요."
                    if sell_next_px != "" else "매도 기준가 계산불가"
                )

        summary_states[ticker] = {
            "current_state": current_state,
            "current_cycle_no": current_cycle_no,
            "today_close": today_close,
            "current_rsi": current_rsi,
            "current_fng": current_fng,
            "buy_next_px": buy_next_px,
            "sell_next_px": sell_next_px,
            "next_action": next_action,
            "settled_cash": settled_cash,
            "total_return_pct": results_fng[ticker]["total_return_pct"],
            "total_trades": results_fng[ticker]["total_trades"],
        }

        add_row([
            ticker,
            f"RSI2_{cfg['buy_below']}_{cfg['sell_above']}+F&G",
            current_state, current_cycle_no, today_close,
            round(float(current_rsi), 2) if not np.isnan(current_rsi) else "",
            current_fng,
            round(float(buy_next_px), 2) if buy_next_px != "" else "",
            round(float(sell_next_px), 2) if sell_next_px != "" else "",
            next_action,
            settled_cash,
            results_fng[ticker]["total_return_pct"],
            results_fng[ticker]["total_trades"],
        ])
        # 주문 안내문
        order_is_buy = "매수" in next_action and "보류" not in next_action
        order_is_sell = "매도" in next_action and "보류" not in next_action
        if order_is_buy or order_is_sell:
            action_msg = next_action
        else:
            action_msg = next_action   # 보류 메시지도 표시
        style_rows[f"order_{ticker.lower()}"] = len(rows) + 1
        add_row([f"📌 {action_msg}"])

    add_row([])

    # ── 연도별 수익률 (FnG) ───────────────────────────────────
    add_row(["[ 연도별 수익률 (RSI2+F&G) ]"])
    style_rows["yearly_section"] = len(rows)
    current_year = datetime.now().year
    all_year_labels: list[str] = []
    yearly_map: dict[str, dict] = {}
    for ticker in search_mod.TICKERS:
        df = results_fng[ticker]["df"]
        df_y = df.copy()
        df_y["year"] = pd.to_datetime(df_y["date"]).dt.year
        yr_dict: dict[str, float] = {}
        for yr, grp in df_y.groupby("year"):
            pct = round((float(grp.iloc[-1]["total_assets"]) / float(grp.iloc[0]["total_assets"]) - 1) * 100, 2)
            label = f"{yr}년(진행중)" if yr == current_year else f"{yr}년"
            yr_dict[label] = pct
            if label not in all_year_labels:
                all_year_labels.append(label)
        yearly_map[ticker] = yr_dict
    all_year_labels = sorted(all_year_labels)

    add_row(["종목"] + all_year_labels)
    style_rows["yearly_header"] = len(rows)
    for ticker in search_mod.TICKERS:
        add_row([ticker] + [yearly_map[ticker].get(y, "") for y in all_year_labels])
    style_rows["yearly_end"] = len(rows)

    add_row([])

    # ── 사이클 비교표 (RSI2+F&G) ─────────────────────────────
    add_row(["[ 사이클 비교표 (RSI2+F&G) ]"])
    style_rows["cycle_section"] = len(rows)
    add_row([
        "Cycle #",
        "TQQQ 시작일", "TQQQ 시작현금($)", "TQQQ 매수가", "TQQQ 종료일", "TQQQ 매도가", "TQQQ 종료현금($)", "TQQQ 수익률/바",
        "",
        "SOXL 시작일", "SOXL 시작현금($)", "SOXL 매수가", "SOXL 종료일", "SOXL 매도가", "SOXL 종료현금($)", "SOXL 수익률/바",
    ])
    style_rows["cycle_header"] = len(rows)

    cycle_tables: dict[str, dict] = {}
    max_cycles = 0
    max_pos_cycle_ret = 0.0
    max_neg_cycle_ret_abs = 0.0

    for ticker in search_mod.TICKERS:
        completed, open_cycle = rsi2._extract_cycle_state(results_fng[ticker]["df"])
        cycle_tables[ticker] = {"completed": completed, "open": open_cycle}
        max_cycles = max(max_cycles, len(completed))
        for cyc in completed:
            pct = float(cyc["cycle_return_pct"])
            if pct >= 0:
                max_pos_cycle_ret = max(max_pos_cycle_ret, pct)
            else:
                max_neg_cycle_ret_abs = max(max_neg_cycle_ret_abs, abs(pct))

    t_cycles = cycle_tables["TQQQ"]["completed"]
    s_cycles = cycle_tables["SOXL"]["completed"]

    for i in range(max_cycles):
        t_row = t_cycles[i] if i < len(t_cycles) else None
        s_row = s_cycles[i] if i < len(s_cycles) else None
        t_pct = float(t_row["cycle_return_pct"]) if t_row else ""
        s_pct = float(s_row["cycle_return_pct"]) if s_row else ""
        t_bar = rsi2._bar_text_centered(float(t_pct), max_pos_cycle_ret, max_neg_cycle_ret_abs, f"{t_pct:.2f}%") if t_row else ""
        s_bar = rsi2._bar_text_centered(float(s_pct), max_pos_cycle_ret, max_neg_cycle_ret_abs, f"{s_pct:.2f}%") if s_row else ""
        add_row([
            i + 1,
            t_row["buy_date"] if t_row else "", t_row["start_cash"] if t_row else "",
            t_row["buy_price"] if t_row else "", t_row["sell_date"] if t_row else "",
            t_row["sell_price"] if t_row else "", t_row["end_cash"] if t_row else "",
            t_bar, "",
            s_row["buy_date"] if s_row else "", s_row["start_cash"] if s_row else "",
            s_row["buy_price"] if s_row else "", s_row["sell_date"] if s_row else "",
            s_row["sell_price"] if s_row else "", s_row["end_cash"] if s_row else "",
            s_bar,
        ])

    add_row([])

    # ── 최적화 결과 히트맵 요약 ───────────────────────────────
    add_row(["[ F&G 최적 파라미터 ]"])
    style_rows["opt_section"] = len(rows)
    add_row(["파라미터", "값", "설명"])
    add_row(["fear_max",  best_params["fear_max"],  f"F&G ≤ 이 값 이면 Extreme Fear → SELL 신호 보류"])
    add_row(["greed_min", best_params["greed_min"], f"F&G ≥ 이 값 이면 Extreme Greed → BUY  신호 보류"])
    add_row(["탐색 범위", f"fear: {FEAR_MAX_RANGE[0]}~{FEAR_MAX_RANGE[-1]}, greed: {GREED_MIN_RANGE[0]}~{GREED_MIN_RANGE[-1]}", f"총 {len(FEAR_MAX_RANGE)*len(GREED_MIN_RANGE)}개 조합 탐색"])
    add_row(["최적 합산 수익률", f"{best_params['best_score']:.2f}%", "TQQQ + SOXL 총수익률 합계"])

    ws.update(range_name=f"A1:P{len(rows)}", values=rows)

    # 스타일
    requests = [
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TITLE_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True, "fontSize": 16}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # F&G 파라미터 행 (3번 행)
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.95, "green": 0.85, "blue": 0.6}, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # 성과 비교 헤더
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["compare_header"] - 1, "endRowIndex": style_rows["compare_header"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["compare_data_start"] - 2, "endRowIndex": style_rows["compare_data_start"] - 1, "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # 현재 신호 섹션
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["action_section"] - 1, "endRowIndex": style_rows["action_section"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["action_header"] - 1, "endRowIndex": style_rows["action_header"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # 연도별 섹션
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["yearly_section"] - 1, "endRowIndex": style_rows["yearly_section"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["yearly_header"] - 1, "endRowIndex": style_rows["yearly_header"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # 최적화 섹션
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["opt_section"] - 1, "endRowIndex": style_rows["opt_section"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.9, "green": 0.95, "blue": 0.8}, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # 사이클 비교표 섹션 헤더
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["cycle_section"] - 1, "endRowIndex": style_rows["cycle_section"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["cycle_header"] - 1, "endRowIndex": style_rows["cycle_header"], "startColumnIndex": 0, "endColumnIndex": 18},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # 구분 컬럼 (Cycle# 뒤 separator)
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startColumnIndex": 8, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.965, "green": 0.965, "blue": 0.965}}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        },
    ]

    # 현재 신호 행 색상 (TQQQ, SOXL 각각)
    ticker_data_rows = {
        "TQQQ": style_rows["action_header"] + 1,
        "SOXL": style_rows["action_header"] + 3,
    }
    for ticker, row_no in ticker_data_rows.items():
        state = summary_states[ticker]
        na = state["next_action"]
        if "보류" in na:
            bg = {"red": 0.97, "green": 0.97, "blue": 0.80}  # 노랑 계열
        elif "매수" in na:
            bg = COLOR_BUY
        else:
            bg = COLOR_SELL
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 0, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
        # 주문 안내문
        order_row = style_rows.get(f"order_{ticker.lower()}")
        if order_row:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": order_row - 1, "endRowIndex": order_row, "startColumnIndex": 0, "endColumnIndex": 14},
                    "cell": {"userEnteredFormat": {"backgroundColor": bg, "textFormat": {"bold": True, "fontSize": 13}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })

    # 연도별 수익률 색상
    for row_offset, ticker in enumerate(search_mod.TICKERS):
        yr_row = style_rows["yearly_header"] + 1 + row_offset
        for col_i, yr_label in enumerate(all_year_labels, start=1):
            pct = yearly_map[ticker].get(yr_label)
            if pct is not None:
                shade = {"red": 0.98, "green": 0.55, "blue": 0.55} if pct >= 0 else {"red": 0.55, "green": 0.75, "blue": 0.98}
                requests.append({
                    "repeatCell": {
                        "range": {"sheetId": ws.id, "startRowIndex": yr_row - 1, "endRowIndex": yr_row, "startColumnIndex": col_i, "endColumnIndex": col_i + 1},
                        "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                    }
                })

    # 사이클 퍼센트바 셀 색칠
    cycle_data_start = style_rows["cycle_header"] + 1
    for i in range(max_cycles):
        row_no = cycle_data_start + i
        t_row = t_cycles[i] if i < len(t_cycles) else None
        s_row = s_cycles[i] if i < len(s_cycles) else None
        if t_row:
            shade = rsi2._shade_for_centered(float(t_row["cycle_return_pct"]))
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 7, "endColumnIndex": 8},
                    "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })
        if s_row:
            shade = rsi2._shade_for_centered(float(s_row["cycle_return_pct"]))
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 15, "endColumnIndex": 16},
                    "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })

    ws.spreadsheet.batch_update({"requests": requests})
    print(f"[GoogleSheets] {title} 저장 완료")


def write_fng_daily_tab(ss, ticker: str, df: pd.DataFrame, cfg: dict, perf: dict, best_params: dict):
    """BackTest 일별 탭"""
    title = f"{ticker}_매매기준가"
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 10), cols=len(headers) + 2)

    meta = [
        [f"{ticker}  —  RSI(2)+F&G  매수: RSI<{cfg['buy_below']} & F&G<{best_params['greed_min']}  /  매도: RSI>{cfg['sell_above']} & F&G>{best_params['fear_max']}"],
        [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,}"],
        [f"기간: {search_mod.START_DATE} ~ {search_mod.END_DATE}   거래: {perf['total_trades']}회   체결: LOC"],
        [f"F&G 파라미터: Extreme Fear ≤ {best_params['fear_max']} → SELL 보류   |   Extreme Greed ≥ {best_params['greed_min']} → BUY 보류"],
        headers,
    ]
    data_row0 = len(meta)
    col_letter = chr(64 + len(headers))

    ws.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)

    values = [
        ["" if (v == "" or (isinstance(v, float) and np.isnan(v))) else str(v) for v in row]
        for row in df.values.tolist()
    ]
    if values:
        ws.update(range_name=f"A{data_row0 + 1}:{col_letter}{data_row0 + len(values)}", values=values)

    col_idx = {c: i for i, c in enumerate(headers)}
    center_cols = [f"rsi{cfg['period']}", "chg_pct", "fng", "buy_limit_expected_px",
                   "sell_limit_expected_px", "trade_qty", "holdings", "return_pct"]
    left_cols = ["date", "close", "fng_blocked", "buy_limit_px", "sell_limit_px",
                 "action", "cash", "total_assets"]
    total_rows = data_row0 + len(values) + 1

    align_requests = [{
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": data_row0 - 1, "endRowIndex": data_row0, "startColumnIndex": 0, "endColumnIndex": len(headers)},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }]
    for c in center_cols:
        if c in col_idx:
            ci = col_idx[c]
            align_requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": data_row0, "endRowIndex": total_rows, "startColumnIndex": ci, "endColumnIndex": ci + 1},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            })
    for c in left_cols:
        if c in col_idx:
            ci = col_idx[c]
            align_requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": data_row0, "endRowIndex": total_rows, "startColumnIndex": ci, "endColumnIndex": ci + 1},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            })
    ws.spreadsheet.batch_update({"requests": align_requests})

    # BUY/SELL/HOLD 행 색상 + F&G 차단 행은 노란색
    requests = []
    for i, row in df.iterrows():
        row_idx = data_row0 + df.index.get_loc(i)
        if row["action"] == "BUY":
            bg = COLOR_BUY
        elif row["action"] == "SELL":
            bg = COLOR_SELL
        elif row["fng_blocked"] != "":
            bg = {"red": 1.0, "green": 0.98, "blue": 0.75}  # 연노랑: F&G 차단
        elif row["action"] == "HOLD":
            bg = {"red": 0.95, "green": 0.95, "blue": 0.95}  # 밝은 회색: HOLD
        else:
            continue
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 0, "endColumnIndex": len(headers)},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})

    trades = int((df["action"] != "HOLD").sum())
    blocked = int((df["fng_blocked"] != "").sum())
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행, BUY/SELL {trades}회, F&G차단 {blocked}회)")


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print(f"[BATA_RSI2_FnG_ALGO] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 가격 데이터 다운로드
    close_map: dict[str, pd.Series] = {}
    for ticker in search_mod.TICKERS:
        close_map[ticker] = base.download_close(ticker)
        print(f"[{ticker}] 가격 데이터 {len(close_map[ticker])}일")

    # F&G 역사 데이터
    fng = None
    try:
        from fear_greed_history import load_fng_history
        fng_series = load_fng_history()
        # 가격 데이터 날짜에 맞게 정렬
        sample_dates = close_map[search_mod.TICKERS[0]].index
        fng = fng_series.reindex(sample_dates, method="ffill").fillna(50).astype(int)
        print(f"[FnG] 데이터 준비 완료 ({fng.index.min().date()} ~ {fng.index.max().date()})")
    except Exception as e:
        print(f"[FnG] ⚠️ 데이터 로드 실패: {e}  → 중립값(50) 으로 진행")
        sample_dates = close_map[search_mod.TICKERS[0]].index
        fng = pd.Series(50, index=sample_dates, name="fng")

    # RSI2 단독 백테스트 (비교용)
    results_rsi2 = {}
    for ticker in search_mod.TICKERS:
        cfg  = TICKER_CONFIG[ticker]
        df   = rsi2.simulate_with_targets(close_map[ticker], cfg["period"], cfg["buy_below"], cfg["sell_above"])
        total_ret, cagr, mdd, final_assets = base.calc_perf(df["total_assets"])
        trades = int((df["action"] != "HOLD").sum())
        results_rsi2[ticker] = {
            "total_return_pct": round(total_ret, 2), "cagr_pct": round(cagr, 2),
            "mdd_pct": round(mdd, 2), "final_assets": round(final_assets, 2),
            "total_trades": trades,
        }
        print(f"[RSI2 단독 {ticker}]  {total_ret:.2f}%  {trades}회")

    # F&G 임계값 최적화
    print()
    best_params = optimize_fng_thresholds(close_map, fng)

    # 최적 파라미터로 최종 시뮬레이션
    results_fng = {}
    for ticker in search_mod.TICKERS:
        cfg = TICKER_CONFIG[ticker]
        df  = simulate_with_fng(
            close_map[ticker], fng,
            period=cfg["period"],
            buy_below=cfg["buy_below"],
            sell_above=cfg["sell_above"],
            fear_max=best_params["fear_max"],
            greed_min=best_params["greed_min"],
        )
        total_ret, cagr, mdd, final_assets = base.calc_perf(df["total_assets"])
        trades  = int((df["action"] != "HOLD").sum())
        blocked = int((df["fng_blocked"] != "").sum())
        perf = {
            "total_return_pct": round(total_ret, 2), "cagr_pct": round(cagr, 2),
            "mdd_pct": round(mdd, 2), "final_assets": round(final_assets, 2),
            "total_trades": trades, "df": df,
        }
        results_fng[ticker] = perf
        print(f"[RSI2+FnG {ticker}]  {total_ret:.2f}%  {trades}회  F&G차단 {blocked}회")

    # Google Sheet 갱신 (고정 스프레드시트)
    spreadsheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=spreadsheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(spreadsheet_id)

    write_fng_summary_tab(ss, results_fng, results_rsi2, best_params)
    for ticker in search_mod.TICKERS:
        cfg  = TICKER_CONFIG[ticker]
        df   = results_fng[ticker]["df"]
        perf = {k: v for k, v in results_fng[ticker].items() if k != "df"}
        write_fng_daily_tab(ss, ticker, df, cfg, perf, best_params)

    # FnG 전용 고정 폼 유지: Summary + TQQQ_매매기준가 + SOXL_매매기준가 만 남김
    keep_titles = {"Summary", "TQQQ_매매기준가", "SOXL_매매기준가"}
    for ws in ss.worksheets():
        if ws.title not in keep_titles:
            try:
                ss.del_worksheet(ws)
            except Exception:
                pass

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print("\n" + "=" * 80)
    print(f"[완료] 파일명: {ss.title}")
    print(f"[완료] 구글 시트 링크: {url}")
    tabs = " | ".join([ws.title for ws in ss.worksheets()])
    print(f"탭: {tabs}")
    print("=" * 80)


if __name__ == "__main__":
    main()
