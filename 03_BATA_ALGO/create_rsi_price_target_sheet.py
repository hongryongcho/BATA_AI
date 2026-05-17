"""
RSI(2) 최적 전략 — 실전 매매 가격 기준선(Buy/Sell Limit Price) 시트
────────────────────────────────────────────────────────────────
* BUY  Limit Price : 오늘 장마감 종가가 이 값 이하로 마감되면 매수 신호
* SELL Limit Price : 오늘 장마감 종가가 이 값 이상으로 마감되면 매도 신호

계산 원리 (Wilder EWM RSI 역산)
  alpha = 1 / period
  어제까지의 EWM 상태  mu = ma_up_prev,  md = ma_down_prev
  R = threshold / (100 - threshold)

  BUY  limit (오늘 종가 x 에서 RSI = buy_below):
      x_buy = prev_close - (mu - R_buy*md)*(1-α) / (R_buy*α)
      → x_buy 이하로 마감되면 BUY 신호

  SELL limit (오늘 종가 x 에서 RSI = sell_above):
      x_sell = prev_close + (R_sell*md - mu)*(1-α) / α
      → x_sell 이상으로 마감되면 SELL 신호
  (RSI 가 이미 임계값을 넘은 경우 기준가격이 현재가보다 낮을 수도 있음)

종목: TQQQ (RSI2_15_75), SOXL (RSI2_15_90)
기간: 2021-01-01 ~ 2026-05-16  |  체결: LOC
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

import create_nonsplit_best_algo_sheet as base
import search_optimal_strategies as search_mod
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

FILE_TITLE = "TQQQ_SOXL_RSI2_매매기준가"

TICKER_CONFIG = {
    "TQQQ": {"period": 2, "buy_below": 15, "sell_above": 75},
    "SOXL": {"period": 2, "buy_below": 15, "sell_above": 90},
}

CAPITAL = search_mod.CAPITAL  # 100_000


# ─────────────────────────────────────────────────────────────
# RSI 역산 핵심 함수
# ─────────────────────────────────────────────────────────────
def compute_limit_prices(
    close_arr: np.ndarray,
    mu_arr: np.ndarray,     # ma_up 전날 값 (인덱스 정렬)
    md_arr: np.ndarray,     # ma_down 전날 값
    buy_below: float,
    sell_above: float,
    alpha: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns
    -------
    buy_limits  : 종가 기준 BUY 임계 가격 배열  (NaN = 계산 불가)
    sell_limits : 종가 기준 SELL 임계 가격 배열 (NaN = 계산 불가)
    """
    R_buy  = buy_below  / (100.0 - buy_below)
    R_sell = sell_above / (100.0 - sell_above)
    beta   = 1.0 - alpha     # (1-α)

    n = len(close_arr)
    buy_limits  = np.full(n, np.nan)
    sell_limits = np.full(n, np.nan)

    for i in range(1, n):
        prev = close_arr[i - 1]
        mu   = mu_arr[i - 1]
        md   = md_arr[i - 1]

        # ── BUY limit ─────────────────────────────────────────
        # x_buy = prev - (mu - R_buy*md)*β / (R_buy*α)
        # 특수: md == 0 → 손실 없음, RSI 매우 높음 → BUY 불가 (NaN)
        if md == 0.0 and mu == 0.0:
            buy_limits[i] = prev            # 초기값 없음 시 flat 처리
        elif md == 0.0:
            # ma_down_new = d*α → RS = mu*β/(d*α) = R_buy
            # d = mu*β/(R_buy*α)
            d = mu * beta / (R_buy * alpha)
            buy_limits[i] = round(prev - d, 2)
        else:
            # 일반 공식: 가격 상승/하락 어느 쪽이든 단일 수식
            # 가격이 상승하면 → loss=0
            #   RS = (mu*β + g*α) / (md*β) = R_buy → g = (R_buy*md - mu)*β/α
            # 가격이 하락하면 → gain=0
            #   RS = mu*β / (md*β + d*α) = R_buy   → d = (mu/R_buy - md)*β/α
            # 두 경우를 통합: x_buy = prev + (R_buy*md - mu)*β/α
            #   (양수면 상승 중에도 매수 가능, 음수면 해당 하락까지 필요)
            x = prev + (R_buy * md - mu) * beta / alpha
            buy_limits[i] = round(x, 2)

        # ── SELL limit ────────────────────────────────────────
        # x_sell = prev + (R_sell*md - mu)*β/α
        # (음수 오프셋 = 가격이 하락해도 이 수준 이상이면 매도 신호)
        if mu == 0.0 and md == 0.0:
            sell_limits[i] = prev
        elif mu == 0.0:
            # RSI ≈ 0, 매도 신호 불가능
            sell_limits[i] = np.nan
        else:
            x = prev + (R_sell * md - mu) * beta / alpha
            sell_limits[i] = round(x, 2)

    return buy_limits, sell_limits


# ─────────────────────────────────────────────────────────────
# 시뮬레이션 (EWM 상태 추적 포함)
# ─────────────────────────────────────────────────────────────
def simulate_with_targets(
    close: pd.Series,
    period: int,
    buy_below: float,
    sell_above: float,
) -> pd.DataFrame:
    alpha = 1.0 / period
    closes = close.values.astype(float)
    n = len(closes)

    # ── Wilder EWM 수동 계산 (ma_up / ma_down 배열) ──────────
    ma_up   = np.zeros(n)
    ma_down = np.zeros(n)
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        gain  = max(delta, 0.0)
        loss  = max(-delta, 0.0)
        ma_up[i]   = alpha * gain  + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * loss  + (1 - alpha) * ma_down[i - 1]

    # RSI 계산
    with np.errstate(divide="ignore", invalid="ignore"):
        rs  = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[:1] = np.nan   # 첫 행은 diff 불가

    # BUY / SELL 기준가 역산
    buy_limits, sell_limits = compute_limit_prices(
        closes, ma_up, ma_down, buy_below, sell_above, alpha
    )

    # ── 시뮬레이션 ─────────────────────────────────────────────
    cash     = CAPITAL
    holdings = 0.0
    rows     = []

    for i, (dt, price) in enumerate(close.items()):
        rsi_val  = rsi[i]
        pos_cash = (holdings == 0.0)   # 거래 전 포지션

        action    = "HOLD"
        trade_qty = 0.0

        if not np.isnan(rsi_val):
            if pos_cash and rsi_val < buy_below:
                bought   = cash / price
                holdings = bought
                cash     = 0.0
                trade_qty = bought
                action   = "BUY"
            elif (not pos_cash) and rsi_val > sell_above:
                trade_qty = -holdings
                cash      = holdings * price
                holdings  = 0.0
                action    = "SELL"

        total_assets = cash + holdings * price
        bl = buy_limits[i]
        sl = sell_limits[i]
        bl_expected = round(float(bl), 2) if not np.isnan(bl) else ""
        sl_expected = round(float(sl), 2) if not np.isnan(sl) else ""
        buy_met = "Y" if (not np.isnan(bl) and float(price) <= float(bl)) else ("N" if not np.isnan(bl) else "")
        sell_met = "Y" if (not np.isnan(sl) and float(price) >= float(sl)) else ("N" if not np.isnan(sl) else "")
        buy_gap = round(float(price - bl), 2) if not np.isnan(bl) else ""
        sell_gap = round(float(sl - price), 2) if not np.isnan(sl) else ""

        # 현금 구간: BUY limit 표시 / 주식 구간: SELL limit 표시
        show_buy  = round(float(bl), 2) if pos_cash  and not np.isnan(bl) else ""
        show_sell = round(float(sl), 2) if not pos_cash and not np.isnan(sl) else ""

        prev_price = closes[i - 1] if i > 0 else float(price)
        daily_chg_pct = round((float(price) / prev_price - 1) * 100, 2) if i > 0 else ""

        rows.append({
            "date":         dt.strftime("%Y-%m-%d"),
            "close":        round(float(price), 4),
            "chg_pct":      daily_chg_pct,
            f"rsi{period}": round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "buy_limit_expected_px": bl_expected,
            "sell_limit_expected_px": sl_expected,
            "buy_met": buy_met,
            "sell_met": sell_met,
            "buy_gap_close_minus_limit": buy_gap,
            "sell_gap_limit_minus_close": sell_gap,
            "buy_limit_px": show_buy,    # 이 가격 이하로 마감 → BUY 신호
            "sell_limit_px": show_sell,  # 이 가격 이상으로 마감 → SELL 신호
            "action":       action,
            "trade_qty":    round(float(trade_qty), 6),
            "holdings":     round(float(holdings), 6),
            "cash":         round(float(cash), 2),
            "total_assets": round(float(total_assets), 2),
            "return_pct":   round(float((total_assets / CAPITAL - 1) * 100), 4),
        })

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


# ─────────────────────────────────────────────────────────────
# Google Sheets 출력
# ─────────────────────────────────────────────────────────────
COLOR_BUY    = {"red": 0.714, "green": 0.933, "blue": 0.714}
COLOR_SELL   = {"red": 1.0,   "green": 0.8,   "blue": 0.8}
COLOR_HDR_BG = {"red": 0.267, "green": 0.447, "blue": 0.769}
COLOR_HDR_FG = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
COLOR_TITLE_BG = {"red": 0.098, "green": 0.180, "blue": 0.298}
COLOR_SECTION_BG = {"red": 0.855, "green": 0.914, "blue": 0.969}
COLOR_TQQQ_BG = {"red": 0.925, "green": 0.973, "blue": 0.925}
COLOR_SOXL_BG = {"red": 0.992, "green": 0.953, "blue": 0.902}


def _format_money(value) -> str:
    if value is None or value == "":
        return ""
    return f"${float(value):,.2f}"


def _format_pct(value) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value):.2f}%"


def _build_threshold_state(close: pd.Series, period: int, buy_below: float, sell_above: float):
    alpha = 1.0 / period
    closes = close.values.astype(float)
    n = len(closes)

    ma_up = np.zeros(n)
    ma_down = np.zeros(n)
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        ma_up[i] = alpha * gain + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * loss + (1 - alpha) * ma_down[i - 1]

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[:1] = np.nan

    buy_limits, sell_limits = compute_limit_prices(closes, ma_up, ma_down, buy_below, sell_above, alpha)
    return rsi, buy_limits, sell_limits


def _extract_cycle_state(df: pd.DataFrame) -> tuple[list[dict], dict | None]:
    completed = []
    current_buy = None
    cycle_no = 0
    rows = list(df.itertuples(index=False))

    for i, row in enumerate(rows):
        if row.action == "BUY":
            cycle_no += 1
            if i == 0:
                start_cash = CAPITAL
            else:
                prev_cash = float(rows[i - 1].cash)
                prev_assets = float(rows[i - 1].total_assets)
                start_cash = prev_cash if prev_cash > 0 else prev_assets
            current_buy = {
                "cycle_no": cycle_no,
                "buy_date": row.date,
                "buy_price": float(row.close),
                "buy_rsi": getattr(row, "rsi2", ""),
                "start_cash": round(start_cash, 2),
            }
        elif row.action == "SELL" and current_buy is not None:
            end_cash = float(row.cash)
            start_cash = float(current_buy["start_cash"])
            completed.append({
                **current_buy,
                "sell_date": row.date,
                "sell_price": float(row.close),
                "sell_rsi": getattr(row, "rsi2", ""),
                "end_cash": round(end_cash, 2),
                "cycle_return_pct": round((end_cash / start_cash - 1) * 100, 2),
                "cycle_return_amount": round(end_cash - start_cash, 2),
            })
            current_buy = None

    open_cycle = None
    if current_buy is not None:
        current_assets = float(df.iloc[-1]["total_assets"])
        start_cash = float(current_buy["start_cash"])
        open_cycle = {
            **current_buy,
            "sell_date": "진행중",
            "sell_price": float(df.iloc[-1]["close"]),
            "sell_rsi": "",
            "end_cash": round(current_assets, 2),
            "cycle_return_pct": round((current_assets / start_cash - 1) * 100, 2),
            "cycle_return_amount": round(current_assets - start_cash, 2),
        }

    return completed, open_cycle


def _bar_text_centered(value_pct: float, max_pos: float, max_neg_abs: float, pct_str: str = "", width: int = 28) -> str:
    """중심(|)을 기준으로 양쪽 대칭 바. 손실은 좌측(파랑), 수익은 우측(빨강)"""
    center = width // 2
    bar_width = center - 2
    
    if value_pct > 0 and max_pos > 0:
        ratio = max(0.0, min(float(value_pct) / max_pos, 1.0))
        filled = max(0, int(round(ratio * bar_width)))
        left_pad = center - 1
        right_bar = "█" * filled
        right_pad = bar_width - filled
        return " " * left_pad + "|" + right_bar + "░" * right_pad + " " + pct_str
    elif value_pct < 0 and max_neg_abs > 0:
        ratio = max(0.0, min(abs(float(value_pct)) / max_neg_abs, 1.0))
        filled = max(0, int(round(ratio * bar_width)))
        left_pad = bar_width - filled
        left_bar = "█" * filled
        right_pad = center - 1
        return " " * left_pad + left_bar + "|" + "░" * right_pad + " " + pct_str
    else:
        left_pad = center - 1
        right_pad = center
        return " " * left_pad + "|" + "░" * right_pad + " " + pct_str


def _shade_for_centered(value_pct: float) -> dict:
    """중심 기준 바 색상: 수익(+)는 밝은 빨강, 손실(-)은 밝은 파랑"""
    if value_pct > 0:
        return {"red": 0.98, "green": 0.55, "blue": 0.55}
    elif value_pct < 0:
        return {"red": 0.55, "green": 0.75, "blue": 0.98}
    else:
        return {"red": 0.95, "green": 0.95, "blue": 0.95}


def _batch_row_colors(ws, df: pd.DataFrame, data_row0: int):
    num_cols = len(df.columns)
    requests = []
    for i, action in enumerate(df["action"]):
        if action not in ("BUY", "SELL"):
            continue
        r  = data_row0 + i
        bg = COLOR_BUY if action == "BUY" else COLOR_SELL
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": r, "endRowIndex": r + 1,
                    "startColumnIndex": 0, "endColumnIndex": num_cols,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def write_summary_tab(ss, results: dict):
    title = "Summary_RSI2"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=450, cols=22)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[list] = []
    style_rows = {"title": 1, "action_section": 4, "action_header": 5, "compare_section": None, "compare_header": None}

    def add_row(values: list):
        rows.append(values)
        return len(rows)

    add_row(["TQQQ / SOXL  RSI(2) 최적 전략  —  실전 매매 기준가 시트"])
    add_row([f"생성: {now}   |   기간: {search_mod.START_DATE} ~ {search_mod.END_DATE}   |   초기자본: $100,000   |   체결: LOC"])
    add_row([])

    add_row(["[ 현재 사이클 & 다음날 예약 주문 기준 ]"])
    style_rows["action_section"] = len(rows)
    add_row([
        "종목", "전략명", "현재상태", "현재사이클", "오늘종가", "RSI(2)",
        "다음장 BUY 기준가", "다음장 SELL 기준가", "오늘 BUY 충족", "오늘 SELL 충족",
        "추천 예약주문", "직전 사이클 정산현금($)", "총수익률(%)", "거래횟수",
    ])
    style_rows["action_header"] = len(rows)
    style_rows["order_tqqq"] = None
    style_rows["order_soxl"] = None

    cycle_tables = {}
    summary_states = {}
    max_cycles = 0
    max_pos_cycle_ret = 0.0
    max_neg_cycle_ret_abs = 0.0

    for ticker in search_mod.TICKERS:
        cfg = TICKER_CONFIG[ticker]
        df = results[ticker]["df"]
        close = df["close"].astype(float)
        rsi_series, buy_limits, sell_limits = _build_threshold_state(close, cfg["period"], cfg["buy_below"], cfg["sell_above"])
        completed, open_cycle = _extract_cycle_state(df)
        cycle_tables[ticker] = {"completed": completed, "open": open_cycle}
        max_cycles = max(max_cycles, len(completed))
        for cycle in completed:
            pct = float(cycle["cycle_return_pct"])
            if pct >= 0:
                max_pos_cycle_ret = max(max_pos_cycle_ret, pct)
            else:
                max_neg_cycle_ret_abs = max(max_neg_cycle_ret_abs, abs(pct))

        last = df.iloc[-1]
        holdings = float(last["holdings"])
        today_close = float(last["close"])
        current_rsi = float(last[f"rsi{cfg['period']}"]) if last[f"rsi{cfg['period']}"] != "" else np.nan

        buy_next_px = float(buy_limits[-1]) if not np.isnan(buy_limits[-1]) else ""
        sell_next_px = float(sell_limits[-1]) if not np.isnan(sell_limits[-1]) else ""
        buy_met_today = "Y" if (buy_next_px != "" and today_close <= buy_next_px) else "N"
        sell_met_today = "Y" if (sell_next_px != "" and today_close >= sell_next_px) else "N"

        if holdings > 0:
            next_action = f"내일 LOC 매도: 종가 >= {sell_next_px:.2f}" if sell_next_px != "" else "매도 기준가 계산불가"
        else:
            next_action = f"내일 LOC 매수: 종가 <= {buy_next_px:.2f}" if buy_next_px != "" else "매수 기준가 계산불가"

        current_cycle_no = open_cycle["cycle_no"] if open_cycle else len(completed)
        current_state = "주식 보유" if holdings > 0 else "현금 보유"
        settled_cash = completed[-1]["end_cash"] if completed else CAPITAL

        # 연도별 수익률 계산
        df_y = df.copy()
        df_y["year"] = pd.to_datetime(df_y["date"]).dt.year
        current_year = datetime.now().year
        yearly_returns = {}
        for yr, grp in df_y.groupby("year"):
            yr_start = float(grp.iloc[0]["total_assets"])
            yr_end   = float(grp.iloc[-1]["total_assets"])
            pct = round((yr_end / yr_start - 1) * 100, 2)
            label = f"{yr}년(진행중)" if yr == current_year else f"{yr}년"
            yearly_returns[label] = pct

        summary_states[ticker] = {
            "strategy": f"RSI2_{cfg['buy_below']}_{cfg['sell_above']}",
            "current_state": current_state,
            "current_cycle_no": current_cycle_no,
            "today_close": today_close,
            "next_action": next_action,
            "buy_next_px": buy_next_px,
            "sell_next_px": sell_next_px,
            "buy_met_today": buy_met_today,
            "sell_met_today": sell_met_today,
            "settled_cash": settled_cash,
            "total_return_pct": results[ticker]["total_return_pct"],
            "total_trades": results[ticker]["total_trades"],
            "current_rsi": current_rsi,
            "df": df,
            "yearly_returns": yearly_returns,
        }

    for ticker in search_mod.TICKERS:
        s = summary_states[ticker]
        add_row([
            ticker,
            s["strategy"],
            s["current_state"],
            s["current_cycle_no"],
            s["today_close"],
            round(float(s["current_rsi"]), 2) if not np.isnan(s["current_rsi"]) else "",
            round(float(s["buy_next_px"]), 2) if s["buy_next_px"] != "" else "",
            round(float(s["sell_next_px"]), 2) if s["sell_next_px"] != "" else "",
            s["buy_met_today"],
            s["sell_met_today"],
            s["next_action"],
            s["settled_cash"],
            s["total_return_pct"],
            s["total_trades"],
        ])

        # 다음날 주문 안내문
        buy_px  = s["buy_next_px"]
        sell_px = s["sell_next_px"]
        if s["current_state"] == "현금 보유":
            order_msg = (
                f"📌 다음 장 시작 전에  LOC 매수 주문을  ${buy_px:.2f}  에 걸어주세요."
                if buy_px != "" else "매수 기준가 계산불가"
            )
        else:
            order_msg = (
                f"📌 다음 장 시작 전에  LOC 매도 주문을  ${sell_px:.2f}  에 걸어주세요."
                if sell_px != "" else "매도 기준가 계산불가"
            )
        if ticker == "TQQQ":
            style_rows["order_tqqq"] = len(rows) + 1
        else:
            style_rows["order_soxl"] = len(rows) + 1
        add_row([order_msg])

    add_row([])
    add_row(["[ 연도별 수익률 ]"])
    style_rows["yearly_section"] = len(rows)
    # 헤더: 연도 레이블
    t_yr = summary_states["TQQQ"]["yearly_returns"]
    s_yr = summary_states["SOXL"]["yearly_returns"]
    all_years = sorted(set(list(t_yr.keys()) + list(s_yr.keys())))
    add_row(["종목"] + all_years)
    style_rows["yearly_header"] = len(rows)
    add_row(["TQQQ"] + [t_yr.get(y, "") for y in all_years])
    style_rows["yearly_tqqq"] = len(rows)
    add_row(["SOXL"] + [s_yr.get(y, "") for y in all_years])
    style_rows["yearly_soxl"] = len(rows)

    add_row([])
    add_row(["[ 사이클 비교표 ]"])
    style_rows["compare_section"] = len(rows)
    add_row([
        "Cycle #",
        "TQQQ 시작일", "TQQQ 시작현금($)", "TQQQ 매수가", "TQQQ 종료일", "TQQQ 매도가", "TQQQ 종료현금($)", "TQQQ 수익률/바",
        "",
        "SOXL 시작일", "SOXL 시작현금($)", "SOXL 매수가", "SOXL 종료일", "SOXL 매도가", "SOXL 종료현금($)", "SOXL 수익률/바",
    ])
    style_rows["compare_header"] = len(rows)

    t_cycles = cycle_tables["TQQQ"]["completed"]
    s_cycles = cycle_tables["SOXL"]["completed"]

    for i in range(max_cycles):
        t_row = t_cycles[i] if i < len(t_cycles) else None
        s_row = s_cycles[i] if i < len(s_cycles) else None
        t_pct = float(t_row["cycle_return_pct"]) if t_row else ""
        s_pct = float(s_row["cycle_return_pct"]) if s_row else ""
        t_bar_with_pct = _bar_text_centered(float(t_pct), max_pos_cycle_ret, max_neg_cycle_ret_abs, f"{t_pct:.2f}%") if t_row else ""
        s_bar_with_pct = _bar_text_centered(float(s_pct), max_pos_cycle_ret, max_neg_cycle_ret_abs, f"{s_pct:.2f}%") if s_row else ""
        add_row([
            i + 1,
            t_row["buy_date"] if t_row else "",
            t_row["start_cash"] if t_row else "",
            t_row["buy_price"] if t_row else "",
            t_row["sell_date"] if t_row else "",
            t_row["sell_price"] if t_row else "",
            t_row["end_cash"] if t_row else "",
            t_bar_with_pct,
            "",
            s_row["buy_date"] if s_row else "",
            s_row["start_cash"] if s_row else "",
            s_row["buy_price"] if s_row else "",
            s_row["sell_date"] if s_row else "",
            s_row["sell_price"] if s_row else "",
            s_row["end_cash"] if s_row else "",
            s_bar_with_pct,
        ])

    add_row([])
    add_row(["[ RSI(2) 기준가 해설 ]"])
    add_row(["BUY 기준가", "내일 종가가 다음장 BUY 기준가 이하이면 RSI(2)<15 조건 충족으로 LOC 매수 예약"])
    add_row(["SELL 기준가", "내일 종가가 다음장 SELL 기준가 이상이면 RSI(2)>임계값 조건 충족으로 LOC 매도 예약"])
    add_row(["BackTest 검증", "buy_limit_expected_px / close / buy_met 컬럼으로 기대치 대비 실제 미충족 여부 확인 가능"])
    add_row(["퍼센트바", "수익(+)은 좌→우 빨강, 손실(-)은 우→좌 파랑으로 표시"])

    ws.update(range_name=f"A1:S{len(rows)}", values=rows)

    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": ws.id,
                    "gridProperties": {"frozenRowCount": 5},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TITLE_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True, "fontSize": 16}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 4, "endRowIndex": 5, "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 5, "endRowIndex": 6, "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TQQQ_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 6, "endRowIndex": 7, "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SOXL_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["compare_section"] - 1, "endRowIndex": style_rows["compare_section"], "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": style_rows["compare_header"] - 1, "endRowIndex": style_rows["compare_header"], "startColumnIndex": 0, "endColumnIndex": 19},
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startColumnIndex": 9, "endColumnIndex": 10},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.965, "green": 0.965, "blue": 0.965}}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        },
    ]

    # 현재 액션 행 강조 (TQQQ: row6, SOXL: row8 — 각 ticker 뒤에 order 행이 1개씩 추가됨)
    ticker_data_rows = {"TQQQ": style_rows["action_header"] + 1, "SOXL": style_rows["action_header"] + 3}
    for ticker, idx in ticker_data_rows.items():
        state = summary_states[ticker]
        bg = COLOR_BUY if "매수" in state["next_action"] else COLOR_SELL
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": idx - 1, "endRowIndex": idx, "startColumnIndex": 0, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": idx - 1, "endRowIndex": idx, "startColumnIndex": 6, "endColumnIndex": 12},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat",
            }
        })

    # 주문 안내문 스타일 (굵게 + 큰 글자 + 배경색)
    for key, ticker in [("order_tqqq", "TQQQ"), ("order_soxl", "SOXL")]:
        order_row = style_rows.get(key)
        if order_row:
            state = summary_states[ticker]
            bg = COLOR_BUY if "매수" in state["next_action"] else COLOR_SELL
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": order_row - 1, "endRowIndex": order_row, "startColumnIndex": 0, "endColumnIndex": 14},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": bg,
                        "textFormat": {"bold": True, "fontSize": 14},
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })

    # 연도별 수익률 섹션 스타일
    requests.append({
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_rows["yearly_section"] - 1, "endRowIndex": style_rows["yearly_section"], "startColumnIndex": 0, "endColumnIndex": 19},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })
    requests.append({
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_rows["yearly_header"] - 1, "endRowIndex": style_rows["yearly_header"], "startColumnIndex": 0, "endColumnIndex": 19},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })
    # 연도별 수익률 수치 색상 (양수=연한빨강, 음수=연한파랑)
    for yr_key, ticker in [("yearly_tqqq", "TQQQ"), ("yearly_soxl", "SOXL")]:
        yr_row = style_rows[yr_key]
        yr_data = summary_states[ticker]["yearly_returns"]
        all_yr_keys = sorted(set(list(summary_states["TQQQ"]["yearly_returns"].keys()) + list(summary_states["SOXL"]["yearly_returns"].keys())))
        for col_i, yr_label in enumerate(all_yr_keys, start=1):
            pct = yr_data.get(yr_label, None)
            if pct is not None:
                shade = {"red": 0.98, "green": 0.55, "blue": 0.55} if pct >= 0 else {"red": 0.55, "green": 0.75, "blue": 0.98}
                requests.append({
                    "repeatCell": {
                        "range": {"sheetId": ws.id, "startRowIndex": yr_row - 1, "endRowIndex": yr_row, "startColumnIndex": col_i, "endColumnIndex": col_i + 1},
                        "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                    }
                })

    # 사이클 비교표 데이터셀의 수익률/퍼센트바(통합)를 수익률에 따라 색칠
    compare_start = style_rows["compare_header"] + 1
    for i in range(max_cycles):
        row_number = compare_start + i
        t_row = t_cycles[i] if i < len(t_cycles) else None
        s_row = s_cycles[i] if i < len(s_cycles) else None
        if t_row:
            shade = _shade_for_centered(float(t_row["cycle_return_pct"]))
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": row_number - 1, "endRowIndex": row_number, "startColumnIndex": 7, "endColumnIndex": 8},
                    "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })
        if s_row:
            shade = _shade_for_centered(float(s_row["cycle_return_pct"]))
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": row_number - 1, "endRowIndex": row_number, "startColumnIndex": 15, "endColumnIndex": 16},
                    "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })

    ws.spreadsheet.batch_update({"requests": requests})
    print(f"[GoogleSheets] {title} 저장 완료")


def write_daily_tab(ss, ticker: str, df: pd.DataFrame, cfg: dict, perf: dict):
    title = f"{ticker}_매매기준가"
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 10), cols=len(headers))

    meta = [
        [f"{ticker}  —  RSI(2)  매수 기준: RSI < {cfg['buy_below']}  /  매도 기준: RSI > {cfg['sell_above']}"],
        [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,}"],
        [f"기간: {search_mod.START_DATE} ~ {search_mod.END_DATE}   거래: {perf['total_trades']}회   체결: LOC"],
        [
            "◀ buy_limit_expected_px / sell_limit_expected_px: 임계 기대치, "
            "close 와 비교해 buy_met/sell_met 으로 충족 여부 확인 ▶"
        ],
        headers,
    ]
    data_row0 = len(meta)   # 0-indexed
    col_letter = chr(64 + len(headers))

    ws.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)

    values = [
        ["" if (v == "" or (isinstance(v, float) and np.isnan(v))) else str(v) for v in row]
        for row in df.values.tolist()
    ]
    if values:
        ws.update(
            range_name=f"A{data_row0 + 1}:{col_letter}{data_row0 + len(values)}",
            values=values,
        )

    # 헤더 행 진한 색
    # 컬럼 인덱스 맵
    col_idx = {c: i for i, c in enumerate(headers)}
    # 계산값(수치): CENTER 정렬 컬럼 목록
    center_cols = [
        f"rsi{cfg['period']}", "chg_pct", "buy_limit_expected_px", "sell_limit_expected_px",
        "buy_met", "sell_met", "buy_gap_close_minus_limit", "sell_gap_limit_minus_close",
        "trade_qty", "holdings", "return_pct",
    ]
    # 데이터/금액: LEFT 정렬 컬럼 목록
    left_cols = ["date", "close", "buy_limit_px", "sell_limit_px", "action", "cash", "total_assets"]
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

    _batch_row_colors(ws, df, data_row0)
    trades = int((df["action"] != "HOLD").sum())
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행, BUY/SELL {trades}회)")


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print(f"[RSI 기준가 시트 생성] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    all_results = {}
    all_dfs     = {}

    for ticker in search_mod.TICKERS:
        cfg   = TICKER_CONFIG[ticker]
        close = base.download_close(ticker)
        df    = simulate_with_targets(close, cfg["period"], cfg["buy_below"], cfg["sell_above"])

        total_ret, cagr, mdd, final_assets = base.calc_perf(df["total_assets"])
        total_trades = int((df["action"] != "HOLD").sum())
        perf = {
            "total_return_pct": round(total_ret, 2),
            "cagr_pct":         round(cagr, 2),
            "mdd_pct":          round(mdd, 2),
            "final_assets":     round(final_assets, 2),
            "total_trades":     total_trades,
        }
        all_results[ticker] = {**perf, "df": df}
        all_dfs[ticker]     = df

        print(
            f"[{ticker}]  수익 {total_ret:.2f}%  CAGR {cagr:.2f}%  "
            f"MDD {mdd:.2f}%  최종 ${final_assets:,.2f}  거래 {total_trades}회"
        )

        # 최신 5행 미리보기
        preview = df[["date", "close", f"rsi{cfg['period']}", "buy_limit_px", "sell_limit_px", "action"]].tail(10)
        print(preview.to_string(index=False))
        print()

    spreadsheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=spreadsheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(spreadsheet_id)

    write_summary_tab(ss, all_results)
    for ticker in search_mod.TICKERS:
        write_daily_tab(ss, ticker, all_dfs[ticker], TICKER_CONFIG[ticker], all_results[ticker])

    try:
        ss.del_worksheet(ss.worksheet("Sheet1"))
    except Exception:
        pass

    print("=" * 80)
    print(f"[완료] 파일명: {ss.title}")
    print(f"[완료] 구글 시트 링크: {ss.url}")
    print(f"탭: {' | '.join(ws.title for ws in ss.worksheets())}")
    print("=" * 80)


if __name__ == "__main__":
    main()
