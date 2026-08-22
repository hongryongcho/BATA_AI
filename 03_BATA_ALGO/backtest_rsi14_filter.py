"""
RSI(14) 매수 제한 필터 분석
────────────────────────────
기존 FnG+RSI(2) 전략에서:
  매수 조건: RSI(2) 크로스다운 15 → TQQQ 전량 매수
  추가 제한: RSI(14) >= 임계값 이면 매수 차단 (고점 진입 방지)

대상: TQQQ / SOXL
기간: 2011~현재 / 2021~현재
"""

import warnings
warnings.filterwarnings("ignore")

import contextlib
import io
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date

TODAY      = date.today().isoformat()
START_FULL = "2011-01-01"
START_SUB  = "2021-01-01"
INIT       = 10_000

RSI14_THRESHOLDS = [50, 55, 60, 65, 70, 75, 80, 999]  # 999 = 제한 없음(기준선 S7)


# ── 공통 유틸 ──────────────────────────────────────────────────────────────────

def wilder_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_stats(eq: pd.Series, silent=False):
    ret    = eq.pct_change().dropna()
    total  = eq.iloc[-1] / eq.iloc[0] - 1
    years  = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr   = (eq.iloc[-1] / eq.iloc[0]) ** (1/years) - 1
    mdd    = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
    trades = int(((ret != 0) & (ret.shift(1) == 0)).sum())  # 대략 진입 횟수 추정
    return dict(total=total, cagr=cagr, mdd=mdd, sharpe=sharpe, final=eq.iloc[-1],
                blocked=0, eq=eq)


def run_strategy(price: pd.Series, bil: pd.Series,
                 rsi14_limit: float) -> dict:
    """
    price   : TQQQ 또는 SOXL 종가 Series
    bil     : BIL 종가 Series
    rsi14_limit : 이 값 이상이면 RSI(2) 매수 신호를 차단 (999 = 차단 없음)
    """
    rsi2  = wilder_rsi(price, 2)
    rsi14 = wilder_rsi(price, 14)

    BUY_TH  = 15.0
    SELL_TH = 75.0

    bil_units = INIT / bil.iloc[0]
    holdings  = 0.0
    in_pos    = False
    equity    = []
    blocked   = 0   # RSI14 필터로 차단된 횟수

    for i in range(len(price)):
        p = price.iloc[i]
        b = bil.iloc[i]

        if i == 0:
            equity.append(INIT)
            continue

        r2_cur  = rsi2.iloc[i]
        r2_prev = rsi2.iloc[i-1]
        r14_cur = rsi14.iloc[i]

        if not (np.isnan(r2_cur) or np.isnan(r2_prev) or np.isnan(r14_cur)):
            # 매수: RSI(2) 크로스다운 15 + RSI(14) < limit
            if r2_prev >= BUY_TH and r2_cur < BUY_TH and not in_pos:
                if r14_cur >= rsi14_limit:
                    blocked += 1  # RSI14 필터 차단
                else:
                    holdings  = (bil_units * b) / p
                    bil_units = 0.0
                    in_pos    = True

            # 매도: RSI(2) 크로스업 75
            elif r2_prev <= SELL_TH and r2_cur > SELL_TH and in_pos:
                bil_units = (holdings * p) / b
                holdings  = 0.0
                in_pos    = False

        nav = holdings * p + bil_units * b
        equity.append(nav)

    eq = pd.Series(equity, index=price.index)
    result = calc_stats(eq)
    result["blocked"] = blocked
    return result


# ── 기간 슬라이스 (full 데이터로 RSI 웜업 보장 후 구간 집계) ────────────────

def slice_stats(eq_full: pd.Series, start: str) -> dict:
    eq_sl   = eq_full.loc[start:]
    if len(eq_sl) < 2:
        return None
    eq_norm = eq_sl / eq_sl.iloc[0] * INIT
    return calc_stats(eq_norm, silent=True)


# ── 데이터 다운로드 ────────────────────────────────────────────────────────────

def download():
    tickers = ["TQQQ", "SOXL", "QQQ", "BIL"]
    raw = yf.download(tickers, start=START_FULL, end=TODAY,
                      auto_adjust=True, progress=False)["Close"]
    return raw.dropna(how="all").ffill()


# ── 출력 헬퍼 ─────────────────────────────────────────────────────────────────

SEP  = "─" * 100
SEP2 = "═" * 100

def pct(v):    return f"{v*100:+7.1f}%"
def pctn(v):   return f"{v*100:7.1f}%"

def print_table(ticker: str, rows: list, period_a: str, period_b: str):
    """rows: [(label, stat_a, stat_b, blocked), ...]"""
    W = 18
    print(f"\n  RSI14 제한값  │ {'──── ' + period_a + ' ────':^44} │ {'──── ' + period_b + ' ────':^44} │ 차단")
    print(f"  {'':16}  │ {'총수익':>8} {'CAGR':>7} {'MDD':>8} {'Sharpe':>7} │ {'총수익':>8} {'CAGR':>7} {'MDD':>8} {'Sharpe':>7} │")
    print("  " + SEP)
    for label, a, b, bl in rows:
        tag = "◀ 기준선" if label == "제한없음(기준)" else ""
        print(f"  {label:<16}  │ "
              f"{pct(a['total']):>9} {pctn(a['cagr']):>7} {pct(a['mdd']):>8} {a['sharpe']:>7.2f} │ "
              f"{pct(b['total']):>9} {pctn(b['cagr']):>7} {pct(b['mdd']):>8} {b['sharpe']:>7.2f} │ "
              f"{bl:>3}회  {tag}")
    print("  " + SEP)


def print_annual_compare(ticker: str, price: pd.Series, bil: pd.Series,
                         best_limit: float, period_b: str):
    """기준선 vs 최적 RSI14 연도별 수익률 비교"""
    eq_base = run_strategy(price, bil, 999)["eq"]
    eq_best = run_strategy(price, bil, best_limit)["eq"]

    years = sorted(set(eq_base.index.year))
    print(f"\n  {ticker} — 기준선 vs RSI14≥{best_limit} 제한 연도별 수익률")
    print(f"  {'연도':<6}  {'기준선(제한없음)':>16}  {'RSI14≥'+str(best_limit)+' 제한':>16}  {'차이':>10}")
    print("  " + "─"*56)
    for yr in years:
        def yr_ret(eq):
            y = eq[eq.index.year == yr]
            if len(y) < 2: return None
            return y.iloc[-1] / y.iloc[0] - 1
        rb = yr_ret(eq_base)
        ro = yr_ret(eq_best)
        if rb is None or ro is None: continue
        diff = ro - rb
        diff_str = f"{diff*100:+.1f}%p"
        flag = " ◀ 개선" if diff > 0.01 else (" ▼ 악화" if diff < -0.01 else "")
        print(f"  {yr}  {pct(rb):>16}  {pct(ro):>16}  {diff_str:>10}{flag}")
    print("  " + "─"*56)


# ── 최적값 판단 기준 (Sharpe×0.4 + CAGR×0.4 - |MDD|×0.2, 최근 4년 기준) ──

def score(st):
    return st["sharpe"] * 0.4 + st["cagr"] * 0.4 - abs(st["mdd"]) * 0.2


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{SEP2}")
    print(f"  RSI(14) 매수제한 필터 최적화 분석")
    print(f"  대상: TQQQ / SOXL   |   기준: $10,000   |   기간: {START_FULL} ~ {TODAY}")
    print(f"{SEP2}")

    print("\n  데이터 다운로드 중...")
    df = download()
    print(f"  로드 완료: {len(df):,}거래일  ({df.index[0].date()} ~ {df.index[-1].date()})")

    PERIOD_A = f"{START_FULL[:4]}~{TODAY[:4]} (전체)"
    PERIOD_B = f"{START_SUB[:4]}~{TODAY[:4]} (최근4년)"

    for ticker in ["TQQQ", "SOXL"]:
        price = df[ticker].dropna()
        bil   = df["BIL"].loc[price.index]

        print(f"\n{SEP2}")
        print(f"  ★ {ticker} — RSI(14) 매수제한 임계값별 성과 비교")
        print(f"{SEP2}")

        rows          = []
        best_score_b  = -999
        best_limit    = 999

        for limit in RSI14_THRESHOLDS:
            # 전체 데이터로 전략 실행 (RSI 웜업 보장)
            res_full = run_strategy(price, bil, limit)
            # 기간별 슬라이스
            st_a = slice_stats(res_full["eq"], START_FULL)
            st_b = slice_stats(res_full["eq"], START_SUB)
            blocked = res_full["blocked"]

            label = f"제한없음(기준)" if limit == 999 else f"RSI14 ≥ {limit}"
            rows.append((label, st_a, st_b, blocked))

            # 최적값: 최근 4년 기준으로 선택
            if limit != 999:
                sc = score(st_b)
                if sc > best_score_b:
                    best_score_b = sc
                    best_limit   = limit

        print_table(ticker, rows, PERIOD_A, PERIOD_B)

        # 최적 임계값 강조
        base_b  = rows[-1][2]  # 999 = 기준선, 최근4년
        best_row = next(r for r in rows if r[0] == f"RSI14 ≥ {best_limit}")
        best_b   = best_row[2]

        print(f"\n  ▶ [{ticker}] 최근 4년 최적 RSI14 제한값: {best_limit}")
        print(f"     기준선  총수익 {pct(base_b['total'])}  CAGR {pctn(base_b['cagr'])}  MDD {pct(base_b['mdd'])}  Sharpe {base_b['sharpe']:.2f}")
        print(f"     RSI14≥{best_limit}  총수익 {pct(best_b['total'])}  CAGR {pctn(best_b['cagr'])}  MDD {pct(best_b['mdd'])}  Sharpe {best_b['sharpe']:.2f}")

        # 연도별 수익률 비교
        print_annual_compare(ticker, price, bil, best_limit, PERIOD_B)

    # ── 종합 결론 ──────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  종합 분석 결론")
    print(f"{SEP2}")
    print("""
  [RSI(14) 매수 제한 필터 원리]
  ┌────────────────────────────────────────────────────────────────────────┐
  │  RSI(2) 크로스다운 15 → 매수 신호 발생                                │
  │  + RSI(14) >= 임계값 → 매수 차단  (아직 고점권, 추가 하락 가능성)    │
  │  + RSI(14) <  임계값 → 매수 허용  (이미 충분히 눌린 상태)            │
  └────────────────────────────────────────────────────────────────────────┘

  [해석 기준]
  - RSI(14) 50 이하 = 중장기 하락 추세권 → 매수 허용 대상 넓음
  - RSI(14) 60~70  = 중립~고점권 경계 → 일부 고점 신호 차단
  - RSI(14) 70 이상 = 중장기 과매수권 → 대부분 차단 (보수적)
  - RSI(14) 75~80  = 극단 과매수      → 거의 차단 (거래 횟수 급감)

  [권고]
  - MDD 개선이 목적이라면: 차단값 낮을수록(60~65) 효과적
  - 수익/MDD 균형이 목적이라면: 최적값 참고
  - 단, 차단이 많을수록 기회 손실도 발생 (연간 수익 변동성 증가 주의)
    """)
    print(SEP2)
