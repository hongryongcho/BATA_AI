"""
TQQQ 룰 기반 전략 비교 백테스트
기간: 2011-01-01 ~ 2024-12-31 (14년)
"""

import contextlib
import io
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

START = "2011-01-01"
END   = "2024-12-31"
INIT  = 10_000


def download():
    tickers = ["TQQQ", "QQQ", "BIL", "QLD"]
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)["Close"]
    return raw.dropna(how="all").ffill()


def calc_stats(eq: pd.Series, label: str, silent=False):
    ret   = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr  = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    mdd   = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
    final = eq.iloc[-1]
    if not silent:
        print(f"  {label:<42} 수익 {total*100:8.1f}%  CAGR {cagr*100:5.1f}%  MDD {mdd*100:6.1f}%  Sharpe {sharpe:.2f}  최종 ${final:,.0f}")
    return dict(label=label, total=total, cagr=cagr, mdd=mdd, sharpe=sharpe, eq=eq, final=final)


def wilder_rsi(series, period=2):
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ─────────────────────────────────────────────
# S0. TQQQ Buy & Hold  (기준선)
# ─────────────────────────────────────────────
def s0_buyhold(df):
    eq = INIT * df["TQQQ"] / df["TQQQ"].iloc[0]
    return calc_stats(eq, "S0. TQQQ Buy & Hold")


# ─────────────────────────────────────────────
# S1. QQQ SMA200 트렌드 추종
#   - 매일 장 마감 후 QQQ 종가 vs 200일 SMA 비교
#   - QQQ > SMA200  → 다음날 TQQQ 100%
#   - QQQ < SMA200  → 다음날 BIL  100%
# ─────────────────────────────────────────────
def s1_sma200(df):
    sma200 = df["QQQ"].rolling(200).mean()
    signal = (df["QQQ"] > sma200).astype(float).shift(1)
    strat  = signal * df["TQQQ"].pct_change() + (1 - signal) * df["BIL"].pct_change()
    eq     = INIT * (1 + strat).cumprod()
    eq.iloc[0] = INIT
    return calc_stats(eq.dropna(), "S1. SMA200 트렌드추종")


# ─────────────────────────────────────────────
# S2. SMA200 + RSI(2) 콤보
#   - SMA200 위 구간에서만 RSI 신호 적용
#   - SMA200 위 + RSI<10 → TQQQ / RSI>80 → BIL
#   - SMA200 아래 → 무조건 BIL
# ─────────────────────────────────────────────
def s2_sma_rsi(df):
    sma200 = df["QQQ"].rolling(200).mean()
    rsi2   = wilder_rsi(df["TQQQ"], 2)
    above  = (df["QQQ"] > sma200)
    pos    = pd.Series(np.nan, index=df.index)
    pos[above]  = 1.0
    pos[~above] = 0.0
    pos[(above) & (rsi2 > 80)] = 0.0
    pos[(above) & (rsi2 < 10)] = 1.0
    pos    = pos.ffill().shift(1)
    strat  = pos * df["TQQQ"].pct_change() + (1 - pos) * df["BIL"].pct_change()
    eq     = INIT * (1 + strat).cumprod()
    eq.iloc[0] = INIT
    return calc_stats(eq.dropna(), "S2. SMA200 + RSI(2) 콤보")


# ─────────────────────────────────────────────
# S3. 절대 모멘텀 (12개월)
#   - 월말 TQQQ 12개월 수익률 > 0 → 다음달 TQQQ
#   - 12개월 수익률 ≤ 0           → 다음달 BIL
# ─────────────────────────────────────────────
def s3_momentum(df):
    monthly  = df[["TQQQ", "BIL"]].resample("ME").last()
    sig_m    = (monthly["TQQQ"].pct_change(12) > 0).astype(float).shift(1)
    sig_d    = sig_m.reindex(df.index, method="ffill")
    strat    = sig_d * df["TQQQ"].pct_change() + (1 - sig_d) * df["BIL"].pct_change()
    eq       = INIT * (1 + strat).cumprod()
    eq.iloc[0] = INIT
    return calc_stats(eq.dropna(), "S3. 절대 모멘텀(12M)")


# ─────────────────────────────────────────────
# S4. VAA 라이트
#   - 매월 TQQQ/QLD/QQQ 모멘텀 점수 계산 (1+3+6+12M 평균)
#   - 3개 전부 양수 → 최강 자산 100%
#   - 1개라도 음수 → BIL 100% (경고등)
# ─────────────────────────────────────────────
def s4_vaa(df):
    monthly = df[["TQQQ","QLD","QQQ","BIL"]].resample("ME").last()
    def mscore(s):
        return (s.pct_change(1)+s.pct_change(3)+s.pct_change(6)+s.pct_change(12)) / 4
    score    = pd.DataFrame({t: mscore(monthly[t]) for t in ["TQQQ","QLD","QQQ"]})
    best     = score.idxmax(axis=1)
    all_pos  = (score > 0).all(axis=1)
    pos      = {t: pd.Series(0.0, index=monthly.index) for t in ["TQQQ","QLD","QQQ","BIL"]}
    for i in monthly.index:
        if all_pos.get(i, False):
            pos[best.get(i,"BIL")][i] = 1.0
        else:
            pos["BIL"][i] = 1.0
    for t in pos:
        pos[t] = pos[t].shift(1)
    sig  = {t: pos[t].reindex(df.index, method="ffill") for t in pos}
    rets = df[["TQQQ","QLD","QQQ","BIL"]].pct_change()
    strat = sum(sig[t] * rets[t] for t in ["TQQQ","QLD","QQQ","BIL"])
    eq    = INIT * (1 + strat).cumprod()
    eq.iloc[0] = INIT
    return calc_stats(eq.dropna(), "S4. VAA 라이트(TQQQ/QLD/QQQ)")


# ─────────────────────────────────────────────
# S5. RSI(2) 분할매수 (현재 BATA 전략 근사)
#   - 자본을 4 lot으로 분리 (40/20/20/20%)
#   - RSI < 80/70/60/50 순서로 각 lot 진입
#   - RSI > 80 → 전 lot 일괄 청산 → BIL 대기
# ─────────────────────────────────────────────
def s5_rsi_split(df):
    rsi2    = wilder_rsi(df["TQQQ"], 2)
    lot_w   = [0.40, 0.20, 0.20, 0.20]
    entries = [80, 70, 60, 50]
    exit_th = 80
    cash = INIT; holdings = [0.0]*4; in_trade = [False]*4
    bil_units = 0.0; equity = []
    for i, (date, row) in enumerate(df.iterrows()):
        if i == 0:
            bil_units = INIT / row["BIL"]
            equity.append(INIT); continue
        r_prev = rsi2.iloc[i-1]; p = row["TQQQ"]; b = row["BIL"]
        if r_prev > exit_th and any(in_trade):
            for k in range(4):
                if in_trade[k]:
                    cash += holdings[k]*p; holdings[k]=0.0; in_trade[k]=False
            bil_units = cash / b
        for k in range(4):
            if not in_trade[k] and r_prev < entries[k]:
                alloc = INIT * lot_w[k]
                if bil_units * b >= alloc:
                    bil_units -= alloc/b; cash -= alloc
                    holdings[k] = alloc/p; in_trade[k] = True
        equity.append(cash + sum(holdings[k]*p for k in range(4)) + bil_units*b)
    eq = pd.Series(equity, index=df.index)
    return calc_stats(eq, "S5. RSI(2) 분할매수 BIL헤지")


# ─────────────────────────────────────────────
# S6. QQQ 골든/데드크로스
#   - QQQ SMA50 > SMA200 (골든크로스) → TQQQ
#   - QQQ SMA50 < SMA200 (데드크로스) → BIL
#   - 크로스 발생은 연 1~3회 수준, 거래 빈도 낮음
#   - SMA200 단순신호보다 진입/청산이 약간 늦음 (=손실 구간에서 더 버팀)
# ─────────────────────────────────────────────
def s6_golden_cross(df):
    sma50  = df["QQQ"].rolling(50).mean()
    sma200 = df["QQQ"].rolling(200).mean()
    signal = (sma50 > sma200).astype(float).shift(1)
    strat  = signal * df["TQQQ"].pct_change() + (1 - signal) * df["BIL"].pct_change()
    eq     = INIT * (1 + strat).cumprod()
    eq.iloc[0] = INIT
    return calc_stats(eq.dropna(), "S6. 골든/데드크로스(SMA50/200)")


# ─────────────────────────────────────────────
# S8. 골든크로스 + FnG RSI(2) 결합  ★ 신전략
#   매수: 골든크로스(SMA50>SMA200) 유지 중 + RSI(2) 크로스다운 15 → TQQQ 전량
#   매도: 데드크로스(SMA50<SMA200) 돌입  OR  RSI(2) 크로스업 75  → BIL 전량
#   → 골든크로스가 "진입 허가" 필터, RSI가 "타이밍" 신호
# ─────────────────────────────────────────────
def s8_gc_fng_rsi(df):
    sma50  = df["QQQ"].rolling(50).mean()
    sma200 = df["QQQ"].rolling(200).mean()
    rsi2   = wilder_rsi(df["TQQQ"], 2)
    BUY_TH  = 15.0
    SELL_TH = 75.0
    cash = INIT; holdings = 0.0; in_pos = False
    bil_units = INIT / df["BIL"].iloc[0]
    equity = []
    for i, (dt, row) in enumerate(df.iterrows()):
        p = row["TQQQ"]; b = row["BIL"]
        if i == 0:
            equity.append(INIT); continue
        r_cur  = rsi2.iloc[i]
        r_prev = rsi2.iloc[i-1]
        s50    = sma50.iloc[i]
        s200   = sma200.iloc[i]
        if np.isnan(r_cur) or np.isnan(r_prev) or np.isnan(s200):
            equity.append(holdings * p + bil_units * b); continue
        gc_active = s50 > s200
        # 매도: 데드크로스 돌입 또는 RSI 크로스업
        if in_pos and (not gc_active or (r_prev <= SELL_TH and r_cur > SELL_TH)):
            bil_units = holdings * p / b
            holdings  = 0.0; in_pos = False
        # 매수: 골든크로스 유지 중 + RSI 크로스다운
        if not in_pos and gc_active and r_prev >= BUY_TH and r_cur < BUY_TH:
            holdings  = bil_units * b / p
            bil_units = 0.0; in_pos = True
        equity.append(holdings * p + bil_units * b)
    eq = pd.Series(equity, index=df.index)
    return calc_stats(eq, "S8. 골든크로스+FnG RSI(2)")


# ─────────────────────────────────────────────
# S7. FnG + RSI(2) All-in / All-out  ★ 원본 전략
#   - RSI(2) 전일 >= 15, 당일 < 15 크로스다운 → TQQQ 전량 매수
#   - RSI(2) 전일 <= 75, 당일 > 75 크로스업   → TQQQ 전량 매도 → BIL
#   - 포지션 없을 때는 BIL로 대기
# ─────────────────────────────────────────────
def s7_fng_rsi(df):
    rsi2     = wilder_rsi(df["TQQQ"], 2)
    BUY_TH   = 15.0
    SELL_TH  = 75.0
    cash = INIT; holdings = 0.0; in_pos = False
    bil_units = INIT / df["BIL"].iloc[0]
    equity = []
    for i, (dt, row) in enumerate(df.iterrows()):
        p = row["TQQQ"]; b = row["BIL"]
        if i == 0:
            equity.append(INIT); continue
        r_cur  = rsi2.iloc[i]
        r_prev = rsi2.iloc[i-1]
        if not np.isnan(r_cur) and not np.isnan(r_prev):
            # 매수 크로스
            if r_prev >= BUY_TH and r_cur < BUY_TH and not in_pos:
                invest = bil_units * b
                holdings  = invest / p
                bil_units = 0.0
                cash      = 0.0
                in_pos    = True
            # 매도 크로스
            elif r_prev <= SELL_TH and r_cur > SELL_TH and in_pos:
                proceeds  = holdings * p
                bil_units = proceeds / b
                holdings  = 0.0
                in_pos    = False
        nav = holdings * p + bil_units * b
        equity.append(nav)
    eq = pd.Series(equity, index=df.index)
    return calc_stats(eq, "S7. FnG+RSI(2) All-in/out ★")


# ─────────────────────────────────────────────
# 연도별 수익률 테이블
# ─────────────────────────────────────────────
def print_annual(results, keys):
    headers = [results[k]["label"][:16] for k in keys]
    print(f"\n  {'연도':<6}", end="")
    for h in headers:
        print(f"  {h:>16}", end="")
    print()
    print("  " + "─"*72)
    years = sorted(set(results[keys[0]]["eq"].index.year))
    for yr in years:
        print(f"  {yr}", end="")
        for k in keys:
            eq   = results[k]["eq"]
            y_eq = eq[eq.index.year == yr]
            if len(y_eq) < 2:
                print(f"  {'N/A':>16}", end="")
            else:
                r = y_eq.iloc[-1] / y_eq.iloc[0] - 1
                mark = " ▲" if r > 0 else " ▼"
                print(f"  {r*100:>14.1f}%{mark}", end="")
        print()


STRATEGY_FUNCS = [
    ("s0", s0_buyhold),
    ("s1", s1_sma200),
    ("s2", s2_sma_rsi),
    ("s3", s3_momentum),
    ("s4", s4_vaa),
    ("s5", s5_rsi_split),
    ("s6", s6_golden_cross),
    ("s7", s7_fng_rsi),
    ("s8", s8_gc_fng_rsi),
]

LABELS_SHORT = {
    "s0": "S0.TQQQ Buy&Hold",
    "s1": "S1.SMA200 트렌드",
    "s2": "S2.SMA200+RSI(2)",
    "s3": "S3.절대모멘텀12M",
    "s4": "S4.VAA 라이트",
    "s5": "S5.RSI(2)분할매수",
    "s6": "S6.골든/데드크로스",
    "s7": "S7.FnG+RSI(2)★",
    "s8": "S8.골든크로스+FnG★",
}


def run_all_strategies(df):
    """전체 df로 모든 전략 실행 (출력 억제) → {key: eq_series} 반환
    전체 데이터로 실행해야 SMA200 등 rolling window warm-up이 보존됨"""
    eq_curves = {}
    for key, fn in STRATEGY_FUNCS:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = fn(df)
        eq_curves[key] = res["eq"]
    return eq_curves


def stats_from_curves(eq_curves, start_str, end_str):
    """equity curve를 기간으로 슬라이스 후 INIT 기준 재정규화 → stats dict 반환"""
    results = {}
    for key, _ in STRATEGY_FUNCS:
        eq_sliced = eq_curves[key].loc[start_str:end_str]
        if len(eq_sliced) < 2:
            continue
        eq_norm = eq_sliced / eq_sliced.iloc[0] * INIT
        results[key] = calc_stats(eq_norm, LABELS_SHORT[key], silent=True)
    return results


def print_comparison_table(r_a, label_a, r_b, label_b):
    """두 기간 결과를 한 줄씩 나란히 출력"""
    SEP = "─" * 100
    HDR = f"  {'전략':<20}  {'총수익':>8} {'CAGR':>6} {'MDD':>7} {'Sharpe':>7}  │  {'총수익':>8} {'CAGR':>6} {'MDD':>7} {'Sharpe':>7}"
    print(f"\n  {'':20}  {'[ ' + label_a + ' ]':^32}    {'[ ' + label_b + ' ]':^32}")
    print(HDR)
    print("  " + SEP)
    for key, _ in STRATEGY_FUNCS:
        a = r_a[key]
        b = r_b[key]
        lbl = LABELS_SHORT[key]
        print(
            f"  {lbl:<20}"
            f"  {a['total']*100:>7.1f}% {a['cagr']*100:>5.1f}% {a['mdd']*100:>6.1f}% {a['sharpe']:>7.2f}"
            f"  │"
            f"  {b['total']*100:>7.1f}% {b['cagr']*100:>5.1f}% {b['mdd']*100:>6.1f}% {b['sharpe']:>7.2f}"
        )
    print("  " + SEP)


def print_annual_two(r_a, label_a, r_b, label_b, keys):
    """연도별 수익률을 두 기간 나란히 출력"""
    all_years = sorted(set(
        list(r_a[keys[0]]["eq"].index.year) +
        list(r_b[keys[0]]["eq"].index.year)
    ))
    col_w = 10

    # 헤더
    print(f"\n  {'연도':<6}", end="")
    for k in keys:
        lbl = LABELS_SHORT[k][:col_w]
        print(f"  {lbl:>{col_w}}", end="")
    print(f"   │", end="")
    for k in keys:
        lbl = LABELS_SHORT[k][:col_w]
        print(f"  {lbl:>{col_w}}", end="")
    print(f"\n  {'':6}  {'[ '+label_a+' ]':^{col_w*len(keys)+3*len(keys)}}   │  {'[ '+label_b+' ]':^{col_w*len(keys)+3*len(keys)}}")
    print("  " + "─"*90)

    for yr in all_years:
        print(f"  {yr}", end="")
        for k in keys:
            eq   = r_a[k]["eq"]
            y_eq = eq[eq.index.year == yr]
            if len(y_eq) < 2:
                print(f"  {'─':>{col_w}}", end="")
            else:
                r = y_eq.iloc[-1] / y_eq.iloc[0] - 1
                mark = "▲" if r > 0 else "▼"
                print(f"  {r*100:>{col_w-1}.1f}%{mark}", end="")
        print(f"   │", end="")
        for k in keys:
            eq   = r_b[k]["eq"]
            y_eq = eq[eq.index.year == yr]
            if len(y_eq) < 2:
                print(f"  {'─':>{col_w}}", end="")
            else:
                r = y_eq.iloc[-1] / y_eq.iloc[0] - 1
                mark = "▲" if r > 0 else "▼"
                print(f"  {r*100:>{col_w-1}.1f}%{mark}", end="")
        print()


if __name__ == "__main__":
    print("데이터 다운로드 중 (2011~2024) ...")
    df_all = download()
    print(f"데이터: {df_all.index[0].date()} ~ {df_all.index[-1].date()}  ({len(df_all)}일)\n")

    print("전략 시뮬레이션 중 (전체 기간, SMA warm-up 포함) ...")
    eq_curves = run_all_strategies(df_all)

    r_a = stats_from_curves(eq_curves, "2011-01-01", "2024-12-31")
    r_b = stats_from_curves(eq_curves, "2021-01-01", "2024-12-31")

    label_a = "2011~2024 (14년)"
    label_b = "2021~2024 (4년)"

    # ── 종합 성과 비교표 ──────────────────────────────────────
    print("\n" + "═"*100)
    print("  ★ 전략별 성과 비교  (초기자본 $10,000 기준)")
    print("═"*100)
    print_comparison_table(r_a, label_a, r_b, label_b)

    # ── 연도별 수익률: 주요 4개 ────────────────────────────────
    print("\n" + "─"*100)
    print("  연도별 수익률  ─  S0 · S1 · S6 · S7  (좌: 2011~2024 / 우: 2021~2024)")
    print("─"*100)
    print_annual_two(r_a, label_a, r_b, label_b, ["s0","s1","s6","s7"])

    print("\n" + "─"*100)
    print("  연도별 수익률  ─  S1 · S5 · S7  (좌: 2011~2024 / 우: 2021~2024)")
    print("─"*100)
    print_annual_two(r_a, label_a, r_b, label_b, ["s1","s5","s7"])

    # ── S6 / S7 / S8 집중 비교 ───────────────────────────────────
    print("\n" + "═"*100)
    print("  ★★ S6 vs S7 vs S8 집중 비교  (S8 = 골든크로스 필터 + FnG RSI 타이밍)")
    print("═"*100)

    compare_keys = ["s6", "s7", "s8"]
    compare_labels = ["S6.골든/데드크로스", "S7.FnG+RSI(2)★", "S8.골든크로스+FnG★"]
    col = 22

    # 성과표
    print(f"\n  {'기간':<18}  {'전략':<{col}}  {'총수익':>9}  {'CAGR':>6}  {'MDD':>7}  {'Sharpe':>7}  {'최종$':>10}")
    print("  " + "─"*88)
    for period_r, period_lbl in [(r_a, label_a), (r_b, label_b)]:
        for k in compare_keys:
            d = period_r[k]
            lbl = LABELS_SHORT[k]
            final_v = d["eq"].iloc[-1]
            print(f"  {period_lbl:<18}  {lbl:<{col}}  {d['total']*100:>8.1f}%  {d['cagr']*100:>5.1f}%  {d['mdd']*100:>6.1f}%  {d['sharpe']:>7.2f}  ${final_v:>9,.0f}")
        print("  " + "─"*88)

    # 연도별 비교
    print(f"\n  연도별 수익률 (2011~2024):")
    print(f"\n  {'연도':<6}", end="")
    for lbl in compare_labels:
        print(f"  {lbl[:col]:>{col}}", end="")
    print()
    print("  " + "─"*78)
    for yr in sorted(set(r_a["s6"]["eq"].index.year)):
        print(f"  {yr}", end="")
        for k in compare_keys:
            eq = r_a[k]["eq"]
            y_eq = eq[eq.index.year == yr]
            if len(y_eq) < 2:
                print(f"  {'─':>{col}}", end="")
            else:
                rv = y_eq.iloc[-1] / y_eq.iloc[0] - 1
                mark = "▲" if rv > 0 else "▼"
                print(f"  {rv*100:>{col-2}.1f}% {mark}", end="")
        print()

    print()
    print("※ 슬리피지·세금·환율 미반영  |  과거 성과는 미래를 보장하지 않음")
    print("※ S8 = S6 골든크로스(진입필터) + S7 FnG RSI(2)(타이밍 신호) 결합")
