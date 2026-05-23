"""
BATA 투자 알고리즘 백테스트 엔진

알고리즘 요약:
- LOC(Limit-On-Close) 기반 분할 매수/매도
- 52주 전고점 대비 낙폭으로 매수 배수 결정
- 평단 대비 수익률로 매도 배수 결정
- Fear & Greed Extreme 구간 필터
- 갭업 조건 강제 매도
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
import yfinance as yf

from config import ETF_3X_CODES, DEFAULT_PARAMS, EXTREME_FEAR_MAX, EXTREME_GREED_MIN


# ─────────────────────────────────────────────
# 양도세 설정 (해외주식, 연간 정산)
# ─────────────────────────────────────────────
TAX_RATE_ANNUAL   = 0.22       # 22% (지방세 2% 포함)
TAX_EXEMPTION_USD = 1_900.0    # 비과세 한도 ~250만원 (KRW 1,300/USD 기준)


# ─────────────────────────────────────────────
# 파라미터 데이터클래스
# ─────────────────────────────────────────────

@dataclass
class AlgoParams:
    ticker: str = "SPY"
    initial_capital: float = 100_000.0
    n_splits: int = 40
    start_date: str = "2022-01-01"
    end_date: Optional[str] = None
    base_profit_pct: float = 3.0    # 기본 수익 기준 (%)
    buy_threshold_1: float = 10.0   # 2배수 낙폭 (%)
    buy_threshold_2: float = 15.0   # 3배수 낙폭 (%)
    buy_threshold_3: float = 20.0   # 4배수 낙폭 (%)
    sell_threshold_1: float = 10.0  # 2배수 수익 (%)
    sell_threshold_2: float = 20.0  # 3배수 수익 (%)
    sell_threshold_3: float = 30.0  # 4배수 수익 (%)
    gap_up_pct: float = 2.0         # 갭업 강제 매도 기준 (%)
    is_3x: Optional[bool] = None    # None = 자동 감지

    def __post_init__(self):
        # 3배수 여부 자동 감지
        if self.is_3x is None:
            self.is_3x = self.ticker.upper() in ETF_3X_CODES

        # 3배수인 경우 임계값 × 3
        if self.is_3x:
            self.buy_threshold_1 *= 3
            self.buy_threshold_2 *= 3
            self.buy_threshold_3 *= 3
            self.sell_threshold_1 *= 3
            self.sell_threshold_2 *= 3
            self.sell_threshold_3 *= 3
            self.base_profit_pct *= 3
            self.gap_up_pct *= 3

    @classmethod
    def from_dict(cls, d: dict) -> "AlgoParams":
        kwargs = {**DEFAULT_PARAMS, **{k: v for k, v in d.items() if v is not None and v != ""}}
        # 숫자 변환
        for key in ["initial_capital", "base_profit_pct",
                    "buy_threshold_1", "buy_threshold_2", "buy_threshold_3",
                    "sell_threshold_1", "sell_threshold_2", "sell_threshold_3",
                    "gap_up_pct"]:
            if key in kwargs:
                kwargs[key] = float(kwargs[key])
        if "n_splits" in kwargs:
            kwargs["n_splits"] = int(kwargs["n_splits"])

        # is_3x: 문자열/숫자/불리언 입력을 모두 안전하게 처리
        def _parse_optional_bool(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                if value == 1:
                    return True
                if value == 0:
                    return False
                return None
            if isinstance(value, str):
                v = value.strip().lower()
                if v in {"true", "t", "1", "yes", "y"}:
                    return True
                if v in {"false", "f", "0", "no", "n"}:
                    return False
                return None
            return None

        if "is_3x" in kwargs:
            kwargs["is_3x"] = _parse_optional_bool(kwargs["is_3x"])

        return cls(**{k: v for k, v in kwargs.items() if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────
# 일별 거래 결과 레코드
# ─────────────────────────────────────────────

@dataclass
class DayRecord:
    date: str
    close: float
    high_52w: float
    drawdown_pct: float       # 전고점 대비 낙폭 (음수)
    avg_cost: float           # 평단가
    profit_pct: float         # 평단 대비 수익률 (%)
    fear_greed: int
    action: str               # BUY / SELL / HOLD / SKIP
    qty: int                  # 거래 수량
    trade_amount: float       # 거래 금액
    shares: int               # 거래 후 보유 주식수
    cash: float               # 현금 잔고
    portfolio_value: float    # 보유주식 평가금액
    total_assets: float       # 총자산
    return_pct: float         # 초기자본 대비 수익률 (%)
    cycle: int                # 사이클 번호
    memo: str = ""


# ─────────────────────────────────────────────
# 백테스트 엔진
# ─────────────────────────────────────────────

class BacktestEngine:

    def __init__(self, params: AlgoParams, fg_series: Optional[dict] = None):
        """
        params: AlgoParams
        fg_series: {날짜문자열: int} 딕셔너리 (없으면 50=Neutral 사용)
        """
        self.params = params
        self.fg_series = fg_series or {}

    # ── 주가 데이터 다운로드 ─────────────────

    def load_price_data(self) -> pd.DataFrame:
        p = self.params
        end = p.end_date or datetime.today().strftime("%Y-%m-%d")
        # 52주 전고점 계산을 위해 시작일보다 1년 이전 데이터도 받아옴
        fetch_start = (
            pd.Timestamp(p.start_date) - pd.DateOffset(years=1)
        ).strftime("%Y-%m-%d")

        print(f"[backtest] 주가 다운로드: {p.ticker} {fetch_start} ~ {end}")
        df = yf.download(p.ticker, start=fetch_start, end=end,
                         auto_adjust=True, progress=False)

        if df.empty:
            raise ValueError(f"주가 데이터 없음: {p.ticker}")

        # Multi-level column 처리 (yfinance 최신 버전)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index).normalize()
        df.sort_index(inplace=True)
        return df

    # ── 52주 전고점 계산 ─────────────────────

    @staticmethod
    def compute_52w_high(df: pd.DataFrame) -> pd.Series:
        return df["Close"].rolling(window=252, min_periods=1).max()

    # ── 배수 계산 ────────────────────────────

    def buy_multiplier(self, drawdown_pct: float) -> int:
        """drawdown_pct: 음수 (예: -12.5 → -12.5%)"""
        p = self.params
        drop = abs(drawdown_pct)
        if drop >= p.buy_threshold_3:
            return 4
        if drop >= p.buy_threshold_2:
            return 3
        if drop >= p.buy_threshold_1:
            return 2
        return 1

    def sell_multiplier(self, profit_pct: float) -> int:
        """profit_pct: 평단 대비 수익률 (%)"""
        p = self.params
        if profit_pct >= p.sell_threshold_3:
            return 4
        if profit_pct >= p.sell_threshold_2:
            return 3
        if profit_pct >= p.sell_threshold_1:
            return 2
        return 1

    # ── 백테스트 실행 ────────────────────────

    def run(self) -> tuple[list[DayRecord], dict]:
        p = self.params
        df_all = self.load_price_data()
        high_52w = self.compute_52w_high(df_all)

        # 백테스트 기간으로 자르기
        df = df_all[df_all.index >= pd.Timestamp(p.start_date)].copy()
        high_52w = high_52w[high_52w.index >= pd.Timestamp(p.start_date)]

        # 상태 변수
        cash = p.initial_capital
        shares = 0
        avg_cost = 0.0
        unit_qty = 0
        cycle = 1
        realized_pnl = 0.0
        annual_realized_pnl = 0.0
        current_year = pd.Timestamp(p.start_date).year
        total_tax_paid = 0.0
        records: list[DayRecord] = []

        dates = df.index.tolist()
        closes = df["Close"].tolist()

        for i, (dt, close) in enumerate(zip(dates, closes)):
            close = float(close)
            prev_close = float(closes[i - 1]) if i > 0 else close
            h52 = float(high_52w.loc[dt])
            dt_str = dt.strftime("%Y-%m-%d")

            # Fear & Greed
            fg_value = self.fg_series.get(dt_str, 50)

            # 파생 지표
            drawdown_pct = ((close / h52) - 1) * 100 if h52 > 0 else 0.0
            profit_pct = ((close / avg_cost) - 1) * 100 if avg_cost > 0 and shares > 0 else 0.0
            gap_up_pct_today = ((close / prev_close) - 1) * 100

            extreme_fear = fg_value <= EXTREME_FEAR_MAX
            extreme_greed = fg_value >= EXTREME_GREED_MIN

            # ── unit_qty 결정 ──────────────────
            if unit_qty == 0 and shares == 0:
                # 첫 매수 시 unit_qty 결정
                unit_qty = max(1, math.floor(cash / p.n_splits / close))

            action = "HOLD"
            qty = 0
            trade_amount = 0.0
            memo = ""

            # ── 연간 양도세 차감 (새해 첫 거래일) ────────────────
            tax_note = ""
            if dt.year != current_year:
                taxable = max(0.0, annual_realized_pnl - TAX_EXEMPTION_USD)
                if taxable > 0:
                    tax = round(taxable * TAX_RATE_ANNUAL, 2)
                    cash -= tax
                    total_tax_paid += tax
                    tax_note = f"[양도세 ${tax:,.0f} 차감] {current_year}년 실현손익=${annual_realized_pnl:,.0f}"
                annual_realized_pnl = 0.0
                current_year = dt.year

            # ── 매매 로직 ──────────────────────

            # 1) 갭업 강제 매도 (shares > 0 인 경우만)
            if shares > 0 and gap_up_pct_today >= p.gap_up_pct and not extreme_fear:
                sell_qty = min(unit_qty, shares)
                cash += sell_qty * close
                realized_pnl += sell_qty * (close - avg_cost)
                annual_realized_pnl += sell_qty * (close - avg_cost)
                shares -= sell_qty
                action = "SELL"
                qty = sell_qty
                trade_amount = sell_qty * close
                memo = f"갭업강제매도 +{gap_up_pct_today:.1f}%"

                # 사이클 종료 체크
                if shares == 0:
                    cycle += 1
                    unit_qty = 0  # 다음 매수 시 재계산

            # 2) 기본 매수/매도
            elif shares > 0 and (gap_up_pct_today >= 1.0 or profit_pct >= p.base_profit_pct):
                # 손실 구간이라도 당일 +1% 상승 시 기본매도 실행
                # 수익 구간에서도 동일한 기본매도 수량을 사용
                sell_qty = self._calc_base_sell_qty(unit_qty, shares)
                cash += sell_qty * close
                realized_pnl += sell_qty * (close - avg_cost)
                annual_realized_pnl += sell_qty * (close - avg_cost)
                shares -= sell_qty
                action = "SELL"
                qty = sell_qty
                trade_amount = sell_qty * close
                if gap_up_pct_today >= 1.0 and profit_pct < p.base_profit_pct:
                    memo = f"기본매도 상승1%={gap_up_pct_today:.2f}% profit={profit_pct:.2f}%"
                else:
                    memo = f"기본매도 profit={profit_pct:.2f}%"
                if shares == 0:
                    cycle += 1
                    unit_qty = 0

            elif extreme_fear:
                # Extreme Fear → 매수만
                buy_qty = self._calc_buy_qty(unit_qty, drawdown_pct)
                cost = buy_qty * close
                if cash >= cost and buy_qty > 0:
                    avg_cost = self._new_avg_cost(avg_cost, shares, close, buy_qty)
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
                # Extreme Greed → 매도만
                if shares > 0:
                    sell_qty = self._calc_sell_qty(unit_qty, profit_pct, shares)
                    cash += sell_qty * close
                    realized_pnl += sell_qty * (close - avg_cost)
                    annual_realized_pnl += sell_qty * (close - avg_cost)
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
                # 일반 매매
                if shares == 0:
                    # 주식 0 → 무조건 1회 매수
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
                    # 평단 +기준% 미만 → 매수
                    buy_qty = self._calc_buy_qty(unit_qty, drawdown_pct)
                    cost = buy_qty * close
                    if cash >= cost:
                        avg_cost = self._new_avg_cost(avg_cost, shares, close, buy_qty)
                        cash -= cost
                        shares += buy_qty
                        action = "BUY"
                        qty = buy_qty
                        trade_amount = cost
                    else:
                        action = "SKIP"
                        memo = "현금부족"

            # ── 양도세 메모 병합 ────────────────
            if tax_note:
                memo = tax_note + (" | " + memo if memo else "")

            # ── 자산 계산 ──────────────────────
            portfolio_value = shares * close
            total_assets = cash + portfolio_value
            return_pct = (total_assets / p.initial_capital - 1) * 100
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

        # ── 마지막 연도 양도세 차감 ─────────────────────────────
        taxable_final = max(0.0, annual_realized_pnl - TAX_EXEMPTION_USD)
        if taxable_final > 0 and records:
            tax_final = round(taxable_final * TAX_RATE_ANNUAL, 2)
            total_tax_paid += tax_final
            last = records[-1]
            last.cash = round(last.cash - tax_final, 2)
            last.total_assets = round(last.total_assets - tax_final, 2)
            last.return_pct = round((last.total_assets / p.initial_capital - 1) * 100, 2)
            suffix = f" | [양도세 ${tax_final:,.0f} 최종차감]"
            last.memo = (last.memo + suffix) if last.memo else suffix.lstrip(" | ")

        # ── 성과 요약 ──────────────────────────
        summary = self._compute_summary(records, p.initial_capital, total_tax_paid)
        return records, summary

    # ── 헬퍼 메서드 ──────────────────────────

    def _calc_buy_qty(self, unit_qty: int, drawdown_pct: float) -> int:
        multiplier = self.buy_multiplier(drawdown_pct)
        return unit_qty * multiplier

    @staticmethod
    def _calc_base_sell_qty(unit_qty: int, shares: int) -> int:
        return min(max(1, unit_qty), shares)

    def _calc_sell_qty(self, unit_qty: int, profit_pct: float, shares: int) -> int:
        multiplier = self.sell_multiplier(profit_pct)
        qty = min(unit_qty * multiplier, shares)
        # 기본수익 구간 이상이면 최소 1회 매도 보장
        if shares > 0 and profit_pct >= self.params.base_profit_pct:
            return max(1, qty)
        return qty

    @staticmethod
    def _new_avg_cost(prev_avg: float, prev_shares: int, price: float, qty: int) -> float:
        if prev_shares == 0:
            return price
        total_cost = prev_avg * prev_shares + price * qty
        return total_cost / (prev_shares + qty)

    @staticmethod
    def _compute_summary(records: list[DayRecord], initial_capital: float, total_tax_paid: float = 0.0) -> dict:
        if not records:
            return {}

        total_assets_series = [r.total_assets for r in records]
        max_assets = initial_capital
        mdd = 0.0
        for ta in total_assets_series:
            if ta > max_assets:
                max_assets = ta
            dd = (ta / max_assets - 1) * 100
            if dd < mdd:
                mdd = dd

        final = records[-1]
        first_date = datetime.strptime(records[0].date, "%Y-%m-%d")
        last_date = datetime.strptime(records[-1].date, "%Y-%m-%d")
        years = max((last_date - first_date).days / 365.25, 1 / 365.25)
        cagr = ((final.total_assets / initial_capital) ** (1 / years) - 1) * 100

        buy_count = sum(1 for r in records if r.action == "BUY")
        sell_count = sum(1 for r in records if r.action == "SELL")
        max_cycle = max(r.cycle for r in records)

        return {
            "ticker": records[0].date,  # placeholder, set by caller
            "start_date": records[0].date,
            "end_date": records[-1].date,
            "initial_capital": round(initial_capital, 2),
            "final_total_assets": round(final.total_assets, 2),
            "total_return_pct": round(final.return_pct, 2),
            "cagr_pct": round(cagr, 2),
            "mdd_pct": round(mdd, 2),
            "total_trades": buy_count + sell_count,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_cycles": max_cycle,
            "final_cash": round(final.cash, 2),
            "final_shares": final.shares,
            "final_portfolio_value": round(final.portfolio_value, 2),
            "total_tax_paid": round(total_tax_paid, 2),
        }
