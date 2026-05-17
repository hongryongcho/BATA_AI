"""
2021-01-01 ~ 2026-01-01 구간 전략 추천 + 액션 시트 생성
- LOC 기준
- Summary 탭에서 다음 거래일 대응 가능하도록 가격/수량 정보 제공
- 포함 전략
  1) TQQQ 최대수익: 분할매수/분할매도
  2) TQQQ 실전형: RSI2 Mean Reversion
  3) SOXL 최대수익: RSI2 Mean Reversion
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

import pandas as pd

from backtest_engine import AlgoParams, BacktestEngine, DayRecord
import create_nonsplit_best_algo_sheet as nonsplit_mod
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

START_DATE = "2021-01-01"
END_DATE = "2026-01-01"
CAPITAL = 100_000.0
FILE_TITLE = "전략추천_액션시트_20210101_20260101"


@dataclass
class SplitState:
    params: AlgoParams
    last_record: DayRecord
    prev_close: float
    unit_qty: int
    avg_cost: float
    shares: int
    cash: float
    high_52w: float
    records: list[DayRecord]
    summary: dict


@dataclass
class RsiState:
    ticker: str
    daily_df: pd.DataFrame
    total_return_pct: float
    cagr_pct: float
    mdd_pct: float
    final_assets: float
    total_trades: int
    last_close: float
    holdings: float
    cash: float
    last_rsi2: float | None
    prev_avg_up: float
    prev_avg_down: float


def run_split_with_state(ticker: str, n_splits: int, base_profit_pct: float,
                         buy1: float, buy2: float, buy3: float,
                         sell1: float, sell2: float, sell3: float,
                         gap_up_pct: float = 2.0) -> SplitState:
    params = AlgoParams(
        ticker=ticker,
        initial_capital=CAPITAL,
        n_splits=n_splits,
        start_date=START_DATE,
        end_date=END_DATE,
        base_profit_pct=base_profit_pct,
        buy_threshold_1=buy1,
        buy_threshold_2=buy2,
        buy_threshold_3=buy3,
        sell_threshold_1=sell1,
        sell_threshold_2=sell2,
        sell_threshold_3=sell3,
        gap_up_pct=gap_up_pct,
        is_3x=True,
    )
    engine = BacktestEngine(params=params, fg_series={})

    df_all = engine.load_price_data()
    high_52w = engine.compute_52w_high(df_all)
    df = df_all[df_all.index >= pd.Timestamp(params.start_date)].copy()
    high_52w = high_52w[high_52w.index >= pd.Timestamp(params.start_date)]

    cash = params.initial_capital
    shares = 0
    avg_cost = 0.0
    unit_qty = 0
    cycle = 1
    realized_pnl = 0.0
    records: list[DayRecord] = []

    dates = df.index.tolist()
    closes = df["Close"].tolist()

    for i, (dt, close) in enumerate(zip(dates, closes)):
        close = float(close)
        prev_close = float(closes[i - 1]) if i > 0 else close
        h52 = float(high_52w.loc[dt])
        dt_str = dt.strftime("%Y-%m-%d")
        fg_value = 50

        drawdown_pct = ((close / h52) - 1) * 100 if h52 > 0 else 0.0
        profit_pct = ((close / avg_cost) - 1) * 100 if avg_cost > 0 and shares > 0 else 0.0
        gap_up_pct_today = ((close / prev_close) - 1) * 100
        extreme_fear = False
        extreme_greed = False

        if unit_qty == 0 and shares == 0:
            unit_qty = max(1, math.floor(cash / params.n_splits / close))

        action = "HOLD"
        qty = 0
        trade_amount = 0.0
        memo = ""

        if shares > 0 and gap_up_pct_today >= params.gap_up_pct and not extreme_fear:
            sell_qty = min(unit_qty, shares)
            cash += sell_qty * close
            realized_pnl += sell_qty * (close - avg_cost)
            shares -= sell_qty
            action = "SELL"
            qty = sell_qty
            trade_amount = sell_qty * close
            memo = f"갭업강제매도 +{gap_up_pct_today:.1f}%"
            if shares == 0:
                cycle += 1
                unit_qty = 0

        elif shares > 0 and (gap_up_pct_today >= 1.0 or profit_pct >= params.base_profit_pct):
            sell_qty = min(max(1, unit_qty), shares)
            cash += sell_qty * close
            realized_pnl += sell_qty * (close - avg_cost)
            shares -= sell_qty
            action = "SELL"
            qty = sell_qty
            trade_amount = sell_qty * close
            if gap_up_pct_today >= 1.0 and profit_pct < params.base_profit_pct:
                memo = f"기본매도 상승1%={gap_up_pct_today:.2f}% profit={profit_pct:.2f}%"
            else:
                memo = f"기본매도 profit={profit_pct:.2f}%"
            if shares == 0:
                cycle += 1
                unit_qty = 0

        elif extreme_fear:
            buy_qty = engine._calc_buy_qty(unit_qty, drawdown_pct)
            cost = buy_qty * close
            if cash >= cost and buy_qty > 0:
                avg_cost = engine._new_avg_cost(avg_cost, shares, close, buy_qty)
                cash -= cost
                shares += buy_qty
                action = "BUY"
                qty = buy_qty
                trade_amount = cost
                memo = f"ExtremeFear={fg_value}"
            else:
                action = "SKIP"
                memo = "현금부족 또는 수량0"

        elif extreme_greed:
            if shares > 0:
                sell_qty = engine._calc_sell_qty(unit_qty, profit_pct, shares)
                cash += sell_qty * close
                realized_pnl += sell_qty * (close - avg_cost)
                shares -= sell_qty
                action = "SELL"
                qty = sell_qty
                trade_amount = sell_qty * close
                memo = f"ExtremeGreed={fg_value}"
                if shares == 0:
                    cycle += 1
                    unit_qty = 0
            else:
                action = "HOLD"
                memo = f"ExtremeGreed={fg_value} 보유없음"

        else:
            if shares == 0:
                buy_qty = unit_qty
                cost = buy_qty * close
                if cash >= cost:
                    avg_cost = close
                    cash -= cost
                    shares += buy_qty
                    action = "BUY"
                    qty = buy_qty
                    trade_amount = cost
                    memo = "신규진입"
                else:
                    action = "SKIP"
                    memo = "현금부족"
            else:
                buy_qty = engine._calc_buy_qty(unit_qty, drawdown_pct)
                cost = buy_qty * close
                if cash >= cost:
                    avg_cost = engine._new_avg_cost(avg_cost, shares, close, buy_qty)
                    cash -= cost
                    shares += buy_qty
                    action = "BUY"
                    qty = buy_qty
                    trade_amount = cost
                else:
                    action = "SKIP"
                    memo = "현금부족"

        portfolio_value = shares * close
        total_assets = cash + portfolio_value
        return_pct = (total_assets / params.initial_capital - 1) * 100
        avg_for_record = avg_cost if shares > 0 else 0.0
        profit_for_record = profit_pct if shares > 0 else 0.0

        records.append(DayRecord(
            date=dt_str,
            close=round(close, 4),
            high_52w=round(h52, 4),
            drawdown_pct=round(drawdown_pct, 2),
            avg_cost=round(avg_for_record, 4),
            profit_pct=round(profit_for_record, 2),
            fear_greed=fg_value,
            action=action,
            qty=qty,
            trade_amount=round(trade_amount, 2),
            shares=shares,
            cash=round(cash, 2),
            portfolio_value=round(portfolio_value, 2),
            total_assets=round(total_assets, 2),
            return_pct=round(return_pct, 2),
            cycle=cycle,
            memo=memo,
        ))

    summary = engine._compute_summary(records, params.initial_capital)
    last_record = records[-1]
    prev_close = float(records[-1].close)
    return SplitState(
        params=params,
        last_record=last_record,
        prev_close=prev_close,
        unit_qty=unit_qty,
        avg_cost=avg_cost,
        shares=shares,
        cash=float(cash),
        high_52w=float(last_record.high_52w),
        records=records,
        summary=summary,
    )


def build_split_daily_df(state: SplitState) -> pd.DataFrame:
    rows = []
    for r in state.records:
        rows.append({
            "date": r.date,
            "close": r.close,
            "high_52w": r.high_52w,
            "drawdown_pct": r.drawdown_pct,
            "avg_cost": r.avg_cost,
            "profit_pct": r.profit_pct,
            "action": r.action,
            "trade_qty": r.qty,
            "holdings": r.shares,
            "trade_amount": r.trade_amount,
            "cash": r.cash,
            "total_assets": r.total_assets,
            "return_pct": r.return_pct,
            "cycle": r.cycle,
            "memo": r.memo,
        })
    return pd.DataFrame(rows)


def build_rsi_state(ticker: str) -> RsiState:
    nonsplit_mod.START_DATE = START_DATE
    nonsplit_mod.END_DATE = END_DATE
    close = nonsplit_mod.download_close(ticker)
    daily_df = nonsplit_mod.build_rsi2(close)
    total_return_pct, cagr_pct, mdd_pct, final_assets = nonsplit_mod.calc_perf(daily_df["total_assets"])
    total_trades = int((daily_df["action"] != "HOLD").sum())

    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = up.ewm(alpha=1 / 2, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / 2, adjust=False).mean()
    last_rsi2 = daily_df["rsi2"].iloc[-1]
    last_rsi2 = None if last_rsi2 == "" else float(last_rsi2)

    return RsiState(
        ticker=ticker,
        daily_df=daily_df,
        total_return_pct=float(total_return_pct),
        cagr_pct=float(cagr_pct),
        mdd_pct=float(mdd_pct),
        final_assets=float(final_assets),
        total_trades=total_trades,
        last_close=float(close.iloc[-1]),
        holdings=float(daily_df["holdings"].iloc[-1]),
        cash=float(daily_df["cash"].iloc[-1]),
        last_rsi2=last_rsi2,
        prev_avg_up=float(avg_up.iloc[-1]),
        prev_avg_down=float(avg_down.iloc[-1]),
    )


def calc_rsi2_price_thresholds(state: RsiState) -> tuple[float, float]:
    prev_close = state.last_close
    prev_up = state.prev_avg_up
    prev_down = state.prev_avg_down

    # RSI 10 하향 돌파 가격: prev_up / (prev_down - delta) = 1/9, delta <= 0
    buy_delta = prev_down - 9 * prev_up
    buy_price = prev_close + buy_delta

    # RSI 70 상향 돌파 가격: (prev_up + delta) / prev_down = 7/3, delta >= 0
    sell_delta = prev_down * (7 / 3) - prev_up
    sell_price = prev_close + sell_delta

    return float(buy_price), float(sell_price)


def build_split_next_day_rows(state: SplitState) -> list[list]:
    p = state.params
    current_price = float(state.last_record.close)
    current_high_52w = float(state.high_52w)
    avg_cost = float(state.avg_cost)
    unit_qty = int(state.unit_qty)
    shares = int(state.shares)
    cash = float(state.cash)

    gapup_force_sell = current_price * (1 + p.gap_up_pct / 100)
    base_sell_gap = current_price * 1.01
    base_sell_profit = avg_cost * (1 + p.base_profit_pct / 100) if shares > 0 and avg_cost > 0 else 0.0
    first_sell_trigger = max(base_sell_gap, base_sell_profit) if shares > 0 else 0.0

    buy_price_1 = current_high_52w * (1 - p.buy_threshold_1 / 100)
    buy_price_2 = current_high_52w * (1 - p.buy_threshold_2 / 100)
    buy_price_3 = current_high_52w * (1 - p.buy_threshold_3 / 100)

    est_qty_1 = min(unit_qty, math.floor(cash / buy_price_1)) if buy_price_1 > 0 else 0
    est_qty_2 = min(unit_qty * 2, math.floor(cash / buy_price_2)) if buy_price_2 > 0 else 0
    est_qty_3 = min(unit_qty * 3, math.floor(cash / buy_price_3)) if buy_price_3 > 0 else 0
    est_qty_4 = min(unit_qty * 4, math.floor(cash / (current_high_52w * (1 - p.buy_threshold_3 / 100)))) if buy_price_3 > 0 else 0
    sell_qty = min(unit_qty, shares)

    rows = [
        ["TQQQ 최대수익 전략", "분할매수/분할매도"],
        ["마지막거래일", state.last_record.date],
        ["현재종가", f"${current_price:,.2f}"],
        ["현재 보유수량", shares],
        ["현재 현금", f"${cash:,.2f}"],
        ["현재 평단가", f"${avg_cost:,.2f}" if avg_cost > 0 else "0"],
        ["1회 단위수량(unit)", unit_qty],
        ["52주 고점", f"${current_high_52w:,.2f}"],
        ["다음날 갭업 강제매도", f"종가 >= ${gapup_force_sell:,.2f} 이면 {sell_qty}주 SELL" if shares > 0 else "보유 없음"],
        ["다음날 기본매도", f"종가 >= ${first_sell_trigger:,.2f} 이면 {sell_qty}주 SELL" if shares > 0 else "보유 없음"],
        ["다음날 기본매수 1배", f"종가 > ${buy_price_1:,.2f} 이면 {est_qty_1}주 BUY (현금 허용 시)"],
        ["다음날 기본매수 2배", f"종가 <= ${buy_price_1:,.2f} 이고 > ${buy_price_2:,.2f} 이면 {est_qty_2}주 BUY"],
        ["다음날 기본매수 3배", f"종가 <= ${buy_price_2:,.2f} 이고 > ${buy_price_3:,.2f} 이면 {est_qty_3}주 BUY"],
        ["다음날 기본매수 4배", f"종가 <= ${buy_price_3:,.2f} 이면 {est_qty_4}주 BUY"],
        ["실전 메모", "SELL 조건이 먼저 우선 적용되고, SELL 미해당 시 BUY 로직이 적용됩니다."],
    ]
    return rows


def build_rsi_next_day_rows(label: str, state: RsiState) -> list[list]:
    buy_price, sell_price = calc_rsi2_price_thresholds(state)
    current_price = state.last_close
    holdings = state.holdings
    cash = state.cash
    buy_qty_est = cash / buy_price if buy_price > 0 else 0.0

    if holdings > 0:
        action_line = f"종가 >= ${sell_price:,.2f} 이면 {holdings:,.4f}주 SELL, 미만이면 HOLD"
    else:
        action_line = f"종가 <= ${buy_price:,.2f} 이면 약 {buy_qty_est:,.4f}주 BUY, 초과이면 CASH 유지"

    rows = [
        [label, "RSI2 Mean Reversion"],
        ["마지막거래일", state.daily_df["date"].iloc[-1]],
        ["현재종가", f"${current_price:,.2f}"],
        ["현재 RSI2", f"{state.last_rsi2:.2f}" if state.last_rsi2 is not None else ""],
        ["현재 보유수량", round(holdings, 4)],
        ["현재 현금", f"${cash:,.2f}"],
        ["다음날 BUY 기준가", f"${buy_price:,.2f}"],
        ["다음날 SELL 기준가", f"${sell_price:,.2f}"],
        ["다음날 대응", action_line],
        ["실전 메모", "RSI2는 종가 기준 계산이므로 LOC 주문은 장 마감 직전 신호 확인 후 집행"],
    ]
    return rows


def build_guide_rows() -> list[list]:
    return [
        ["전략/주문 가이드"],
        ["1. TQQQ 최대수익", "분할매수/분할매도", "52주 고점 대비 낙폭으로 1~4배 매수, 수익/상승시 1단위 매도"],
        ["2. TQQQ 실전형", "RSI2 Mean Reversion", "RSI2<10 매수, RSI2>70 매도"],
        ["3. SOXL 최대수익", "RSI2 Mean Reversion", "RSI2<10 매수, RSI2>70 매도"],
        ["체결 방식", "LOC", "종가를 보고 당일 종가에 매수/매도 판단"],
        ["주의", "백테스트", "수수료, 세금, 슬리피지, 분할체결 실패는 미반영"],
    ]


def write_table(ss, title: str, rows: list[list], cols: int):
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(200, len(rows) + 20), cols=cols)

    col_letter = chr(64 + cols) if cols <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}{len(rows)}", values=rows)
    print(f"[GoogleSheets] {title} 저장 완료")


def write_daily_df(ss, title: str, df: pd.DataFrame, header_note: str):
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 20), cols=len(headers))

    meta = [
        [title],
        [header_note],
        [f"기간: {START_DATE} ~ {END_DATE} | 생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        headers,
    ]
    col_letter = chr(64 + len(headers)) if len(headers) <= 26 else "Z"
    ws.update(range_name=f"A1:{col_letter}4", values=meta)

    values = []
    for _, row in df.iterrows():
        values.append(["" if pd.isna(v) else str(v) for v in row.tolist()])
    if values:
        ws.update(range_name=f"A5:{col_letter}{4 + len(values)}", values=values)
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행)")


def build_summary_rows(split_state: SplitState, tqqq_rsi: RsiState, soxl_rsi: RsiState) -> list[list]:
    rows: list[list] = [
        ["2021-01-01 ~ 2026-01-01 전략 추천 요약"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"] ,
        ["기준: LOC / 종목별 초기자본 $100,000 / 마지막 거래일 기준 다음 거래일 대응 포함"],
        [],
        ["전략", "종목", "유형", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수"],
        ["최대수익", "TQQQ", "분할매수/매도", round(split_state.summary["total_return_pct"], 2), round(split_state.summary["cagr_pct"], 2), round(split_state.summary["mdd_pct"], 2), round(split_state.summary["final_total_assets"], 2), int(split_state.summary["total_trades"])],
        ["실전형 대안", "TQQQ", "RSI2 Mean Reversion", round(tqqq_rsi.total_return_pct, 2), round(tqqq_rsi.cagr_pct, 2), round(tqqq_rsi.mdd_pct, 2), round(tqqq_rsi.final_assets, 2), tqqq_rsi.total_trades],
        ["최대수익", "SOXL", "RSI2 Mean Reversion", round(soxl_rsi.total_return_pct, 2), round(soxl_rsi.cagr_pct, 2), round(soxl_rsi.mdd_pct, 2), round(soxl_rsi.final_assets, 2), soxl_rsi.total_trades],
        [],
        ["다음 거래일 대응 - TQQQ 최대수익(분할)"],
    ]

    rows.extend(build_split_next_day_rows(split_state))
    rows.append([])
    rows.append(["다음 거래일 대응 - TQQQ 실전형(RSI2)"])
    rows.extend(build_rsi_next_day_rows("TQQQ 실전형", tqqq_rsi))
    rows.append([])
    rows.append(["다음 거래일 대응 - SOXL 최대수익(RSI2)"])
    rows.extend(build_rsi_next_day_rows("SOXL 최대수익", soxl_rsi))
    return rows


def main():
    print("=" * 80)
    print(f"[액션 시트 생성] 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    split_state = run_split_with_state(
        ticker="TQQQ",
        n_splits=40,
        base_profit_pct=5.0,
        buy1=5,
        buy2=10,
        buy3=15,
        sell1=8,
        sell2=16,
        sell3=24,
        gap_up_pct=2.0,
    )
    tqqq_split_df = build_split_daily_df(split_state)
    tqqq_rsi = build_rsi_state("TQQQ")
    soxl_rsi = build_rsi_state("SOXL")

    existing_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=existing_id)
    gc = sm._get_client()
    ss = gc.create(FILE_TITLE)

    summary_rows = build_summary_rows(split_state, tqqq_rsi, soxl_rsi)
    write_table(ss, "Summary", summary_rows, 8)
    write_table(ss, "Guide", build_guide_rows(), 3)
    write_daily_df(ss, "TQQQ_최대수익_분할일별", tqqq_split_df, "TQQQ 최대수익 전략 | 분할매수/분할매도 | LOC")
    write_daily_df(ss, "TQQQ_실전형_RSI2_일별", tqqq_rsi.daily_df, "TQQQ 실전형 대안 | RSI2 Mean Reversion | LOC")
    write_daily_df(ss, "SOXL_최대수익_RSI2_일별", soxl_rsi.daily_df, "SOXL 최대수익 전략 | RSI2 Mean Reversion | LOC")

    try:
        default_ws = ss.worksheet("Sheet1")
        ss.del_worksheet(default_ws)
    except Exception:
        pass

    print("=" * 80)
    print(f"[완료] 새 구글 시트: {ss.url}")
    print("탭: Summary | Guide | TQQQ_최대수익_분할일별 | TQQQ_실전형_RSI2_일별 | SOXL_최대수익_RSI2_일별")
    print("=" * 80)


if __name__ == "__main__":
    main()
