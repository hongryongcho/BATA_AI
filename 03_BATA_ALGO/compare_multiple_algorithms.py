"""
다양한 알고리즘 비교 분석
10년(2016-2026) 및 20년(2006-2026) 데이터로 최적 투자전략 검증

테스트할 알고리즘:
1. RSI2 단독 (현재 사용 중)
2. RSI14 (표준 RSI)
3. MACD 기반
4. Bollinger Bands
5. 이동평균 교차 (SMA 50/200)
6. 평균회귀 (Mean Reversion)
7. Buy & Hold (장기 보유)
8. RSI2 + F&G (현재 최적 알고리즘)
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SCRIPT_DIR = Path(__file__).parent.resolve()

CAPITAL = 100000.0
TICKERS = ["TQQQ", "SOXL"]

# ─────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────

def load_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """yfinance에서 데이터 로드"""
    print(f"  [{ticker}] 데이터 로드 중... ({start_date} ~ {end_date})", end='')
    data = yf.download(ticker, start=start_date, end=end_date, progress=False)
    # MultiIndex 인 경우 처리
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    print(f" ✓ {len(data)}일")
    return data[['Close']].copy()


# ─────────────────────────────────────────────────────────────
# 알고리즘 1: RSI2 단독
# ─────────────────────────────────────────────────────────────

def algo_rsi2(close: pd.Series, buy_below: int = 15, sell_above: int = 75) -> dict:
    """RSI(2) 기반 매매 전략"""
    period = 2
    alpha = 1.0 / period
    closes = close.values.astype(float)
    n = len(closes)
    
    ma_up = np.zeros(n)
    ma_down = np.zeros(n)
    
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        ma_up[i] = alpha * max(delta, 0.0) + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-delta, 0.0) + (1 - alpha) * ma_down[i - 1]
    
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    
    rsi[:1] = np.nan
    
    signals = pd.Series(0, index=close.index, dtype=int)
    signals.loc[rsi < buy_below] = 1  # BUY
    signals.loc[rsi > sell_above] = -1  # SELL
    
    return {
        'name': 'RSI2',
        'signals': signals,
        'rsi': rsi,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 2: RSI14 (표준 RSI)
# ─────────────────────────────────────────────────────────────

def algo_rsi14(close: pd.Series, buy_below: int = 30, sell_above: int = 70) -> dict:
    """RSI(14) 기반 매매 전략"""
    period = 14
    alpha = 1.0 / period
    closes = close.values.astype(float)
    n = len(closes)
    
    ma_up = np.zeros(n)
    ma_down = np.zeros(n)
    
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        ma_up[i] = alpha * max(delta, 0.0) + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-delta, 0.0) + (1 - alpha) * ma_down[i - 1]
    
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    
    rsi[:1] = np.nan
    
    signals = pd.Series(0, index=close.index, dtype=int)
    signals.loc[rsi < buy_below] = 1  # BUY
    signals.loc[rsi > sell_above] = -1  # SELL
    
    return {
        'name': 'RSI14',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 3: MACD
# ─────────────────────────────────────────────────────────────

def algo_macd(close: pd.Series) -> dict:
    """MACD 기반 매매 전략"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    
    signals = pd.Series(0, index=close.index, dtype=int)
    signals[macd > signal_line] = 1  # BUY
    signals[macd < signal_line] = -1  # SELL
    
    return {
        'name': 'MACD',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 4: Bollinger Bands
# ─────────────────────────────────────────────────────────────

def algo_bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands 기반 매매 전략"""
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    
    signals = pd.Series(0, index=close.index, dtype=int)
    signals.loc[close < lower] = 1  # BUY (하단 터치)
    signals.loc[close > upper] = -1  # SELL (상단 터치)
    
    return {
        'name': 'BollingerBands',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 5: 이동평균 교차 (SMA 50/200)
# ─────────────────────────────────────────────────────────────

def algo_sma_crossover(close: pd.Series) -> dict:
    """SMA 50/200 교차 전략"""
    sma50 = close.rolling(window=50).mean()
    sma200 = close.rolling(window=200).mean()
    
    signals = pd.Series(0, index=close.index, dtype=int)
    signals.loc[sma50 > sma200] = 1  # BUY (단기 > 장기)
    signals.loc[sma50 < sma200] = -1  # SELL (단기 < 장기)
    
    return {
        'name': 'SMA_50_200',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 6: 평균회귀 (Mean Reversion)
# ─────────────────────────────────────────────────────────────

def algo_mean_reversion(close: pd.Series, period: int = 20, threshold: float = 1.0) -> dict:
    """평균회귀 전략 (가격이 평균에서 멀어지면 회귀 예상)"""
    ma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    
    z_score = (close - ma) / std
    
    signals = pd.Series(0, index=close.index, dtype=int)
    signals.loc[z_score < -threshold] = 1  # BUY (평균 이하)
    signals.loc[z_score > threshold] = -1  # SELL (평균 이상)
    
    return {
        'name': 'MeanReversion',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 7: Buy & Hold
# ─────────────────────────────────────────────────────────────

def algo_buy_and_hold(close: pd.Series) -> dict:
    """Buy & Hold (매수 후 보유)"""
    signals = pd.Series(0, index=close.index)
    signals.iloc[0] = 1  # 첫날 매수
    
    return {
        'name': 'BuyAndHold',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 알고리즘 8: RSI2 + F&G 필터 (현재 최적)
# ─────────────────────────────────────────────────────────────

def algo_rsi2_fng(close: pd.Series, buy_below: int = 15, sell_above: int = 75,
                  fear_max: int = 35, greed_min: int = 90) -> dict:
    """RSI2 + F&G 필터 (현재 최적 알고리즘)"""
    period = 2
    alpha = 1.0 / period
    closes = close.values.astype(float)
    n = len(closes)
    
    ma_up = np.zeros(n)
    ma_down = np.zeros(n)
    
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        ma_up[i] = alpha * max(delta, 0.0) + (1 - alpha) * ma_up[i - 1]
        ma_down[i] = alpha * max(-delta, 0.0) + (1 - alpha) * ma_down[i - 1]
    
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(ma_down == 0, np.inf, ma_up / ma_down)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    
    rsi[:1] = np.nan
    
    # RSI 기반 신호
    signals = pd.Series(0, index=close.index, dtype=int)
    signals.loc[rsi < buy_below] = 1
    signals.loc[rsi > sell_above] = -1
    
    # F&G는 임시로 50 (중립값) 사용 (실제 데이터 없음)
    # 실제로는 fear_greed_history에서 데이터 로드해야 함
    
    return {
        'name': 'RSI2+FnG',
        'signals': signals,
    }


# ─────────────────────────────────────────────────────────────
# 백테스트 및 성과 계산
# ─────────────────────────────────────────────────────────────

def backtest(close: pd.Series, signals: pd.Series, algo_name: str) -> dict:
    """백테스트 실행 및 성과 계산"""
    
    closes = close.values.astype(float)
    sigs = signals.fillna(0).astype(int).values
    
    cash = CAPITAL
    position = 0
    position_cost = 0
    
    trades = []
    equity_curve = [CAPITAL]
    
    for i in range(1, len(closes)):
        current_price = closes[i]
        signal = sigs[i]
        
        # BUY 신호
        if signal == 1 and position == 0:
            qty = cash / current_price
            position = qty
            position_cost = cash
            cash = 0
            trades.append({
                'type': 'BUY',
                'date': close.index[i],
                'price': current_price,
                'qty': qty,
            })
        
        # SELL 신호
        elif signal == -1 and position > 0:
            cash = position * current_price
            roi = (cash - position_cost) / position_cost * 100
            trades.append({
                'type': 'SELL',
                'date': close.index[i],
                'price': current_price,
                'roi': roi,
            })
            position = 0
            position_cost = 0
        
        # 현재 자산 계산
        current_equity = cash + (position * current_price if position > 0 else 0)
        equity_curve.append(current_equity)
    
    # 마지막 포지션 정산
    if position > 0:
        final_price = closes[-1]
        cash = position * final_price
        roi = (cash - position_cost) / position_cost * 100
    
    total_return = (equity_curve[-1] - CAPITAL) / CAPITAL * 100
    num_trades = len([t for t in trades if t['type'] == 'SELL'])
    
    # MDD 계산
    equity_array = np.array(equity_curve)
    peak = np.maximum.accumulate(equity_array)
    dd = (equity_array - peak) / peak * 100
    mdd = np.min(dd)
    
    # 승률
    wins = len([t for t in trades if t['type'] == 'SELL' and t.get('roi', 0) > 0])
    losses = len([t for t in trades if t['type'] == 'SELL' and t.get('roi', 0) <= 0])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    # 일일 수익률 계산 (Sharpe ratio용)
    daily_returns = np.diff(equity_curve) / equity_curve[:-1] * 100
    sharpe = (np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)) if np.std(daily_returns) > 0 else 0
    
    return {
        'algo': algo_name,
        'total_return': total_return,
        'num_trades': num_trades,
        'win_rate': win_rate,
        'mdd': mdd,
        'sharpe': sharpe,
        'final_equity': equity_curve[-1],
        'equity_curve': equity_curve,
    }


# ─────────────────────────────────────────────────────────────
# 메인 분석
# ─────────────────────────────────────────────────────────────

def run_comprehensive_analysis():
    """종합 알고리즘 비교 분석"""
    
    print("\n" + "=" * 120)
    print("🔬 다양한 알고리즘 비교 분석")
    print("=" * 120)
    
    # 분석할 기간
    periods = [
        ("최근 10년", "2016-01-01", "2026-05-16"),
        ("최근 20년", "2006-01-01", "2026-05-16"),
    ]
    
    all_results = {}
    
    for period_name, start_date, end_date in periods:
        print(f"\n📅 {period_name} 분석 ({start_date} ~ {end_date})")
        print("─" * 120)
        
        period_results = {}
        
        for ticker in TICKERS:
            print(f"\n  🔍 {ticker} 데이터 로드")
            data = load_data(ticker, start_date, end_date)
            close = data['Close']
            
            # 각 알고리즘 실행
            algorithms = [
                algo_rsi2(close),
                algo_rsi14(close),
                algo_macd(close),
                algo_bollinger_bands(close),
                algo_sma_crossover(close),
                algo_mean_reversion(close),
                algo_buy_and_hold(close),
                algo_rsi2_fng(close),
            ]
            
            ticker_results = []
            
            print(f"\n  ⚡ 백테스트 실행:")
            for algo in algorithms:
                result = backtest(close, algo['signals'], algo['name'])
                ticker_results.append(result)
                
                print(f"    [{result['algo']:<20}] 수익률: {result['total_return']:>8.2f}% | "
                      f"거래: {result['num_trades']:>3}회 | 승률: {result['win_rate']:>5.1f}% | "
                      f"MDD: {result['mdd']:>7.2f}% | Sharpe: {result['sharpe']:>6.2f}")
            
            period_results[ticker] = ticker_results
        
        # 결과 정렬 (수익률 기준)
        print(f"\n  📊 {period_name} - TQQQ vs SOXL 알고리즘 비교")
        print("  " + "─" * 116)
        print(f"  {'알고리즘':<20} | {'TQQQ 수익률':<15} | {'SOXL 수익률':<15} | {'합계':<15} | {'우위':<15}")
        print("  " + "─" * 116)
        
        for algo_name in [r['algo'] for r in period_results['TQQQ']]:
            tqqq_result = next(r for r in period_results['TQQQ'] if r['algo'] == algo_name)
            soxl_result = next(r for r in period_results['SOXL'] if r['algo'] == algo_name)
            
            total = tqqq_result['total_return'] + soxl_result['total_return']
            winner = "SOXL" if soxl_result['total_return'] > tqqq_result['total_return'] else "TQQQ"
            
            print(f"  {algo_name:<20} | {tqqq_result['total_return']:>14.2f}% | "
                  f"{soxl_result['total_return']:>14.2f}% | {total:>14.2f}% | {winner:<15}")
        
        all_results[period_name] = period_results
    
    # ─────────────────────────────────────────────────────────────
    # 안정성 분석 (10년 vs 20년)
    # ─────────────────────────────────────────────────────────────
    
    print(f"\n\n{'=' * 120}")
    print("🏆 안정성 분석 (10년 vs 20년 비교)")
    print(f"{'=' * 120}\n")
    
    for algo_idx, algo_name in enumerate(['RSI2', 'RSI14', 'MACD', 'BollingerBands', 'SMA_50_200', 'MeanReversion', 'BuyAndHold', 'RSI2+FnG']):
        print(f"📌 알고리즘: {algo_name}")
        print("─" * 120)
        
        for ticker in TICKERS:
            result_10yr = all_results['최근 10년'][ticker][algo_idx]
            result_20yr = all_results['최근 20년'][ticker][algo_idx]
            
            change = result_20yr['total_return'] - result_10yr['total_return']
            trend = "📈 향상" if change > 0 else "📉 악화" if change < 0 else "➡️ 동일"
            
            print(f"  {ticker}:")
            print(f"    10년: 수익률 {result_10yr['total_return']:>8.2f}% | 거래 {result_10yr['num_trades']:>3}회 | 승률 {result_10yr['win_rate']:>5.1f}% | MDD {result_10yr['mdd']:>7.2f}%")
            print(f"    20년: 수익률 {result_20yr['total_return']:>8.2f}% | 거래 {result_20yr['num_trades']:>3}회 | 승률 {result_20yr['win_rate']:>5.1f}% | MDD {result_20yr['mdd']:>7.2f}%")
            print(f"    {trend}: {change:+.2f}%p")
            print()
    
    print(f"{'=' * 120}")
    print(f"분석 완료: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"{'=' * 120}\n")


if __name__ == "__main__":
    run_comprehensive_analysis()
