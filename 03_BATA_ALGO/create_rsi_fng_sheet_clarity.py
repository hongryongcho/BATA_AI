from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

import create_nonsplit_best_algo_sheet as base
import create_rsi_price_target_sheet as rsi2
from fear_greed import fetch_fear_greed
from fear_greed_history import load_fng_history
from sheets_manager import SheetsManager

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

START_DATE = "2021-01-01"
END_DATE = datetime.now(ET).strftime("%Y-%m-%d")
CAPITAL = 100_000.0
TICKER_CONFIG = {
    "TQQQ": {"period": 2, "buy_below": 15, "sell_above": 75},
    "SOXL": {"period": 2, "buy_below": 15, "sell_above": 90},
}
FNG_FEAR_MAX = 20
FNG_GREED_MIN = 80

COLOR_BUY = rsi2.COLOR_BUY
COLOR_SELL = rsi2.COLOR_SELL
COLOR_TITLE_BG = rsi2.COLOR_TITLE_BG
COLOR_HDR_BG = rsi2.COLOR_HDR_BG
COLOR_HDR_FG = rsi2.COLOR_HDR_FG
COLOR_SECTION_BG = rsi2.COLOR_SECTION_BG


def download_close(ticker: str) -> pd.Series:
    end_plus = (pd.Timestamp(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START_DATE, end=end_plus, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"주가 데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna().astype(float)
    close.index = pd.to_datetime(close.index)
    return close


def _simulate_one_ticker(close: pd.Series, fng_series: pd.Series, cfg: dict) -> pd.DataFrame:
    period = cfg["period"]
    buy_below = cfg["buy_below"]
    sell_above = cfg["sell_above"]
    alpha = 1.0 / period

    closes = close.values.astype(float)
    n = len(closes)
    ma_up = np.zeros(n)
    ma_down = np.zeros(n)
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        ma_up[i] = alpha * max(delta, 0.0) + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-delta, 0.0) + (1 - alpha) * ma_down[i - 1]

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[:1] = np.nan

    next_buy_limits, next_sell_limits = rsi2.compute_next_day_limit_prices(
        closes, ma_up, ma_down, buy_below, sell_above, alpha
    )
    apply_buy = np.full(n, np.nan)
    apply_sell = np.full(n, np.nan)
    for i in range(1, n):
        apply_buy[i] = next_buy_limits[i - 1]
        apply_sell[i] = next_sell_limits[i - 1]

    fng_aligned = fng_series.reindex(close.index, method="ffill").fillna(50).astype(int)

    cash = CAPITAL
    holdings = 0.0
    rows = []
    for i, (dt, price) in enumerate(close.items()):
        price = float(price)
        fng_val = int(fng_aligned.iloc[i])
        rsi_val = rsi[i]
        action = "HOLD"
        fng_blocked = ""
        trade_qty = 0.0

        if i > 0:
            b_lim = apply_buy[i]
            s_lim = apply_sell[i]
            if holdings == 0.0 and not np.isnan(b_lim) and price <= float(b_lim):
                if fng_val >= FNG_GREED_MIN:
                    fng_blocked = f"BUY차단(F&G={fng_val}>={FNG_GREED_MIN})"
                else:
                    qty = cash / price
                    holdings = qty
                    cash = 0.0
                    trade_qty = qty
                    action = "BUY"
            elif holdings > 0.0 and not np.isnan(s_lim) and price >= float(s_lim):
                if fng_val <= FNG_FEAR_MAX:
                    fng_blocked = f"SELL차단(F&G={fng_val}<={FNG_FEAR_MAX})"
                else:
                    trade_qty = -holdings
                    cash = holdings * price
                    holdings = 0.0
                    action = "SELL"

        total_assets = cash + holdings * price
        prev_price = closes[i - 1] if i > 0 else price
        daily_chg_pct = round((price / prev_price - 1) * 100, 2) if i > 0 else ""

        rows.append({
            "date": dt.strftime("%Y-%m-%d"),
            "close": round(price, 4),
            "chg_pct": daily_chg_pct,
            "fng": fng_val,
            f"rsi{period}": round(float(rsi_val), 2) if not np.isnan(rsi_val) else "",
            "fng_blocked": fng_blocked,
            "buy_limit_expected_px": round(float(apply_buy[i]), 2) if not np.isnan(apply_buy[i]) else "",
            "sell_limit_expected_px": round(float(apply_sell[i]), 2) if not np.isnan(apply_sell[i]) else "",
            "next_day_buy_limit_px": round(float(next_buy_limits[i]), 2) if not np.isnan(next_buy_limits[i]) else "",
            "next_day_sell_limit_px": round(float(next_sell_limits[i]), 2) if not np.isnan(next_sell_limits[i]) else "",
            "action": action,
            "trade_qty": round(float(trade_qty), 6),
            "holdings": round(float(holdings), 6),
            "cash": round(float(cash), 2),
            "total_assets": round(float(total_assets), 2),
            "return_pct": round((float(total_assets) / CAPITAL - 1) * 100, 4),
        })

    df = pd.DataFrame(rows)
    df.index = close.index
    return df


def _extract_completed_cycles(df: pd.DataFrame) -> list[dict]:
    completed = []
    buy_row = None
    cycle_no = 0
    for row in df.itertuples(index=False):
        row = row._asdict()
        if row["action"] == "BUY":
            cycle_no += 1
            buy_row = row
        elif row["action"] == "SELL" and buy_row is not None:
            start_cash = float(buy_row["total_assets"])
            end_cash = float(row["cash"])
            pct = (end_cash / start_cash - 1) * 100 if start_cash else 0.0
            completed.append({
                "cycle_no": cycle_no,
                "buy_date": buy_row["date"],
                "buy_price": float(buy_row["close"]),
                "start_cash": start_cash,
                "sell_date": row["date"],
                "sell_price": float(row["close"]),
                "end_cash": end_cash,
                "cycle_return_pct": round(pct, 2),
            })
            buy_row = None
    return completed


def _yearly_returns(df: pd.DataFrame) -> dict[str, float]:
    out = {}
    tmp = df.copy()
    tmp["year"] = pd.to_datetime(tmp["date"]).dt.year
    current_year = datetime.now(ET).year
    for yr, grp in tmp.groupby("year"):
        start_assets = float(grp.iloc[0]["total_assets"])
        end_assets = float(grp.iloc[-1]["total_assets"])
        pct = round((end_assets / start_assets - 1) * 100, 2) if start_assets else 0.0
        label = f"{yr}년(진행중)" if yr == current_year else f"{yr}년"
        out[label] = pct
    return out


def _perf(df: pd.DataFrame) -> dict:
    total_return_pct, cagr_pct, mdd_pct, final_assets = base.calc_perf(df["total_assets"])
    trades = int((df["action"] != "HOLD").sum())
    return {
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "mdd_pct": round(mdd_pct, 2),
        "final_assets": round(final_assets, 2),
        "total_trades": trades,
    }


def _write_summary(ss, result_map: dict[str, pd.DataFrame], perf_map: dict[str, dict], last_fng: int):
    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=400, cols=22)

    rows = []
    style_rows = {}

    def add_row(values):
        rows.append(values)
        return len(rows)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    add_row(["TQQQ / SOXL  RSI(2) + FnG 명확화 시트 (전일계산→금일적용)"])
    add_row([f"생성: {now}   |   기간: {START_DATE} ~ {END_DATE}   |   초기자본: $100,000   |   체결: LOC"])
    add_row([f"FnG 기준: CNN 실시간 동기화(마지막 행)   |   매도보류 ≤ {FNG_FEAR_MAX}   |   매수보류 ≥ {FNG_GREED_MIN}"])
    add_row([])

    add_row(["[ 전략 성과 요약 ]"])
    style_rows["perf_section"] = len(rows)
    add_row(["종목", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수", "완료사이클", "연평균수익률(CAGR, %)"])
    style_rows["perf_header"] = len(rows)
    for ticker in ["TQQQ", "SOXL"]:
        df = result_map[ticker]
        cycles = _extract_completed_cycles(df)
        p = perf_map[ticker]
        add_row([ticker, p["total_return_pct"], p["cagr_pct"], p["mdd_pct"], p["final_assets"], p["total_trades"], len(cycles), p["cagr_pct"]])
    add_row([])

    add_row(["[ 현재 사이클 & 다음날 예약 주문 ]"])
    style_rows["action_section"] = len(rows)
    add_row(["종목", "현재상태", "오늘종가", "RSI(2)", "FnG", "금일적용 BUY", "금일적용 SELL", "다음장 BUY 기준가", "다음장 SELL 기준가", "추천 예약주문"])
    style_rows["action_header"] = len(rows)
    for ticker in ["TQQQ", "SOXL"]:
        df = result_map[ticker]
        last = df.iloc[-1]
        holdings = float(last["holdings"])
        current_state = "주식 보유" if holdings > 0 else "현금 보유"
        buy_next = last["next_day_buy_limit_px"]
        sell_next = last["next_day_sell_limit_px"]
        if holdings == 0:
            if int(last["fng"]) >= FNG_GREED_MIN:
                next_action = f"⛔ 매수 보류 (F&G={int(last['fng'])} ≥ {FNG_GREED_MIN})"
            else:
                next_action = f"다음 장 시작 전에  LOC 매수 주문을  ${float(buy_next):.2f}  에 걸어주세요." if buy_next != "" else "매수 기준가 계산불가"
        else:
            if int(last["fng"]) <= FNG_FEAR_MAX:
                next_action = f"⛔ 매도 보류 (F&G={int(last['fng'])} ≤ {FNG_FEAR_MAX})"
            else:
                next_action = f"다음 장 시작 전에  LOC 매도 주문을  ${float(sell_next):.2f}  에 걸어주세요." if sell_next != "" else "매도 기준가 계산불가"
        add_row([ticker, current_state, last["close"], last["rsi2"], int(last["fng"]), last["buy_limit_expected_px"], last["sell_limit_expected_px"], buy_next, sell_next, next_action])
        add_row([f"📌 {next_action}"])
    add_row([])

    add_row(["[ 연도별 수익률 ]"])
    style_rows["yearly_section"] = len(rows)
    yearly_map = {ticker: _yearly_returns(result_map[ticker]) for ticker in ["TQQQ", "SOXL"]}
    all_years = sorted({y for ym in yearly_map.values() for y in ym.keys()})
    add_row(["종목"] + all_years)
    style_rows["yearly_header"] = len(rows)
    for ticker in ["TQQQ", "SOXL"]:
        add_row([ticker] + [yearly_map[ticker].get(y, "") for y in all_years])
    add_row([])

    add_row(["[ 사이클 비교표 ]"])
    style_rows["cycle_section"] = len(rows)
    add_row(["Cycle #", "TQQQ 시작일", "TQQQ 시작현금($)", "TQQQ 매수가", "TQQQ 종료일", "TQQQ 매도가", "TQQQ 종료현금($)", "TQQQ 수익률(%)", "", "SOXL 시작일", "SOXL 시작현금($)", "SOXL 매수가", "SOXL 종료일", "SOXL 매도가", "SOXL 종료현금($)", "SOXL 수익률(%)"])
    style_rows["cycle_header"] = len(rows)

    t_cycles = _extract_completed_cycles(result_map["TQQQ"])
    s_cycles = _extract_completed_cycles(result_map["SOXL"])
    max_cycles = max(len(t_cycles), len(s_cycles))
    for i in range(max_cycles):
        t = t_cycles[i] if i < len(t_cycles) else None
        s = s_cycles[i] if i < len(s_cycles) else None
        add_row([
            i + 1,
            t["buy_date"] if t else "", t["start_cash"] if t else "", t["buy_price"] if t else "", t["sell_date"] if t else "", t["sell_price"] if t else "", t["end_cash"] if t else "", t["cycle_return_pct"] if t else "",
            "",
            s["buy_date"] if s else "", s["start_cash"] if s else "", s["buy_price"] if s else "", s["sell_date"] if s else "", s["sell_price"] if s else "", s["end_cash"] if s else "", s["cycle_return_pct"] if s else "",
        ])

    ws.update(range_name=f"A1:P{len(rows)}", values=rows)
    requests = [
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 16}, "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TITLE_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True, "fontSize": 14}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}}
    ]
    for key in ["perf_section", "action_section", "yearly_section", "cycle_section"]:
        requests.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": style_rows[key] - 1, "endRowIndex": style_rows[key], "startColumnIndex": 0, "endColumnIndex": 16}, "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    for key in ["perf_header", "action_header", "yearly_header", "cycle_header"]:
        requests.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": style_rows[key] - 1, "endRowIndex": style_rows[key], "startColumnIndex": 0, "endColumnIndex": 16}, "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    ws.spreadsheet.batch_update({"requests": requests})
    print(f"[GoogleSheets] {title} 저장 완료")


def _write_daily_tab(ss, title: str, df: pd.DataFrame, ticker: str, perf: dict):
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(2200, len(df) + 50), cols=20)

    headers = list(df.columns)
    meta = [
        [f"{ticker}  —  RSI(2)+FnG  전일계산→금일적용 임계값 명확화"],
        [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,}"],
        [f"기간: {START_DATE} ~ {END_DATE}   거래: {perf['total_trades']}회   체결: LOC"],
        ["buy_limit_expected_px/sell_limit_expected_px: 전일 계산되어 금일 체결에 적용된 임계값"],
        ["next_day_buy_limit_px/next_day_sell_limit_px: 금일 종가로 재계산한 다음 거래일 임계값"],
        headers,
    ]
    values = [["" if (v == "" or (isinstance(v, float) and np.isnan(v))) else str(v) for v in row] for row in df.values.tolist()]
    col_letter = chr(64 + len(headers))
    ws.update(range_name=f"A1:{col_letter}{len(meta) + len(values)}", values=meta + values)
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행)")


def main():
    print("=" * 80)
    print(f"[RSI2_FnG_명확화_시트] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    close_map = {}
    for ticker in TICKER_CONFIG:
        close_map[ticker] = download_close(ticker)
        print(f"[{ticker}] 가격 데이터 {len(close_map[ticker])}일")

    fng_hist = load_fng_history()
    sample_dates = close_map["TQQQ"].index
    fng = fng_hist.reindex(sample_dates, method="ffill").fillna(50).astype(int)
    try:
        live = fetch_fear_greed()
        live_val = int(live["value"])
        if len(fng) > 0:
            fng.iloc[-1] = live_val
        print(f"[FnG] 마지막 행 CNN 동기화: {live_val} ({live.get('source', 'cnn')})")
    except Exception as e:
        print(f"[FnG] CNN 동기화 실패: {e}")

    result_map = {}
    perf_map = {}
    for ticker, cfg in TICKER_CONFIG.items():
        df = _simulate_one_ticker(close_map[ticker], fng, cfg)
        result_map[ticker] = df
        perf_map[ticker] = _perf(df)

    sm = SheetsManager(spreadsheet_id="1S-PmVqQblF9uZP0Tj76h3Nwv2ejw7rLBgjP2sb-xgeU")
    gc = sm._get_client()
    base_title = "BackTest3x_명확화_전일계산금일적용_2021시작"
    ss = gc.create(f"{base_title}_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}")
    try:
        ws0 = ss.worksheet("시트1")
        ss.del_worksheet(ws0)
    except Exception:
        pass

    _write_summary(ss, result_map, perf_map, int(fng.iloc[-1]))
    _write_daily_tab(ss, "TQQQ_명확화", result_map["TQQQ"], "TQQQ", perf_map["TQQQ"])
    _write_daily_tab(ss, "SOXL_명확화", result_map["SOXL"], "SOXL", perf_map["SOXL"])

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print("\n" + "=" * 80)
    print(f"[완료] 파일명: {ss.title}")
    print(f"[완료] 구글 시트 링크: {url}")
    print("탭: Summary | TQQQ_명확화 | SOXL_명확화")
    print("=" * 80)


if __name__ == "__main__":
    main()
