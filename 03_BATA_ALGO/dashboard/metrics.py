"""
성과 지표 계산 모듈
MDD, 샤프 지수, 승률, 평균 보유기간, CAGR
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calc_mdd(total_assets: pd.Series) -> float:
    """최대낙폭(MDD) % 계산"""
    if total_assets.empty:
        return 0.0
    rolling_max = total_assets.cummax()
    drawdown = (total_assets - rolling_max) / rolling_max * 100
    return float(drawdown.min())


def calc_sharpe(total_assets: pd.Series, risk_free_rate: float = 0.04) -> float:
    """연환산 샤프 지수 (일별 수익률 기준)"""
    if len(total_assets) < 2:
        return 0.0
    daily_ret = total_assets.pct_change().dropna()
    if daily_ret.std() == 0:
        return 0.0
    excess = daily_ret - risk_free_rate / 252
    return float(excess.mean() / excess.std() * np.sqrt(252))


def calc_cagr(initial: float, final: float, years: float) -> float:
    """연평균 복리 수익률(CAGR) %"""
    if initial <= 0 or years <= 0:
        return 0.0
    return float((final / initial) ** (1 / years) - 1) * 100


def calc_win_rate(backtest_df: pd.DataFrame) -> dict:
    """
    사이클별 승률, 평균 수익률, 평균 보유기간 계산
    backtest_df: 날짜, 총자산, 사이클, 매매구분 컬럼 필요
    """
    if backtest_df.empty:
        return {"win_rate": 0.0, "avg_return": 0.0, "avg_hold_days": 0.0, "total_cycles": 0}

    required = {"사이클", "총자산", "매매구분"}
    if not required.issubset(backtest_df.columns):
        return {"win_rate": 0.0, "avg_return": 0.0, "avg_hold_days": 0.0, "total_cycles": 0}

    sell_rows = backtest_df[backtest_df["매매구분"].str.contains("SELL|매도", na=False, case=False)].copy()
    if sell_rows.empty:
        return {"win_rate": 0.0, "avg_return": 0.0, "avg_hold_days": 0.0, "total_cycles": 0}

    cycles: list[dict] = []
    for cycle_id, grp in backtest_df.groupby("사이클", sort=True):
        grp = grp.sort_values("날짜")
        buy_rows = grp[grp["매매구분"].str.contains("BUY|매수", na=False, case=False)]
        s_rows = grp[grp["매매구분"].str.contains("SELL|매도", na=False, case=False)]
        if buy_rows.empty or s_rows.empty:
            continue
        start_assets = grp["총자산"].iloc[0]
        end_assets = grp["총자산"].iloc[-1]
        ret_pct = (end_assets - start_assets) / start_assets * 100 if start_assets > 0 else 0.0
        hold_days = (grp["날짜"].iloc[-1] - grp["날짜"].iloc[0]).days
        cycles.append({"return_pct": ret_pct, "hold_days": hold_days})

    if not cycles:
        return {"win_rate": 0.0, "avg_return": 0.0, "avg_hold_days": 0.0, "total_cycles": 0}

    wins = sum(1 for c in cycles if c["return_pct"] > 0)
    return {
        "win_rate": wins / len(cycles) * 100,
        "avg_return": np.mean([c["return_pct"] for c in cycles]),
        "avg_hold_days": np.mean([c["hold_days"] for c in cycles]),
        "total_cycles": len(cycles),
    }


def calc_monthly_returns(backtest_df: pd.DataFrame) -> pd.DataFrame:
    """
    월별 수익률 피벗 테이블 반환 (행=연도, 열=월)
    backtest_df: 날짜, 총자산 컬럼 필요
    """
    if backtest_df.empty or "총자산" not in backtest_df.columns:
        return pd.DataFrame()

    df = backtest_df.set_index("날짜")[["총자산"]].copy()
    df = df.resample("ME").last()  # 월말 기준
    df["monthly_ret"] = df["총자산"].pct_change() * 100
    df["year"] = df.index.year
    df["month"] = df.index.month
    pivot = df.pivot_table(values="monthly_ret", index="year", columns="month", aggfunc="last")
    pivot.columns = [f"{m}월" for m in pivot.columns]
    return pivot


def calc_drawdown_series(total_assets: pd.Series) -> pd.Series:
    """낙폭 시리즈 반환 (%)"""
    if total_assets.empty:
        return pd.Series(dtype=float)
    rolling_max = total_assets.cummax()
    return (total_assets - rolling_max) / rolling_max * 100
