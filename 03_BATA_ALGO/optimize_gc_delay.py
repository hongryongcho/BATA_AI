"""
GC 매도지연 최적 일수 탐색
━━━━━━━━━━━━━━━━━━━━━━━━━
delay_days 1~30일 전수 탐색 → CAGR 최대 일수 확인
데이터 다운로드는 1회, 시뮬레이션만 반복 (빠름)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# create_qqq_golden_cross_backtest 에서 핵심 함수 재활용
from create_qqq_golden_cross_backtest import (
    download_close, compute_qqq_gc, simulate, calc_perf,
    START_DATE, END_DATE, CAPITAL, QQQ_CRASH_PCT, QQQ_COOLDOWN,
    GC_MA_FAST, GC_MA_SLOW, TICKER_CONFIG,
)

import pandas as pd
from datetime import datetime

DELAY_RANGE = list(range(1, 31)) + [35, 40, 45, 50, 60]   # 1~30 + 추가


def main():
    print("=" * 70)
    print(f"GC 매도지연 일수 최적화  {START_DATE} ~ {END_DATE}")
    print(f"탐색 범위: {DELAY_RANGE[0]}~{DELAY_RANGE[-1]}일  ({len(DELAY_RANGE)}개)")
    print("=" * 70)

    # ── 데이터 1회 다운로드 ───────────────────────────────────────
    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
    except Exception:
        fng_base = pd.Series(dtype=float)

    print("\n[QQQ] 다운로드...")
    qqq_close = download_close("QQQ")
    qqq_gc    = compute_qqq_gc(qqq_close)

    ticker_data: dict[str, tuple] = {}
    for ticker, cfg in TICKER_CONFIG.items():
        print(f"[{ticker}] 다운로드...")
        close = download_close(ticker)
        fng   = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)
        ticker_data[ticker] = (close, fng, cfg)

    # ── Base 성과 (delay 없음) ────────────────────────────────────
    print("\n[Base] 시뮬레이션...")
    base_perf: dict[str, dict] = {}
    for ticker, (close, fng, cfg) in ticker_data.items():
        df, taxes = simulate(
            close=close, fng=fng, qqq_close=qqq_close,
            period=cfg["period"], buy_below=cfg["buy_below"],
            sell_above=cfg["sell_above"],
            fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
            qqq_gc=None,
        )
        base_perf[ticker] = calc_perf(df, taxes)
        print(f"  {ticker} Base: CAGR {base_perf[ticker]['cagr_pct']:.2f}%  "
              f"MDD {base_perf[ticker]['mdd_pct']:.1f}%  "
              f"평균보유 {base_perf[ticker]['avg_hold_days']:.1f}일")

    # ── delay_days 스윕 ───────────────────────────────────────────
    print(f"\n[스윕] {len(DELAY_RANGE)}개 × {len(TICKER_CONFIG)}종목 시뮬레이션 시작...")
    results: list[dict] = []

    for d in DELAY_RANGE:
        row: dict = {"delay_days": d}
        for ticker, (close, fng, cfg) in ticker_data.items():
            df, taxes = simulate(
                close=close, fng=fng, qqq_close=qqq_close,
                period=cfg["period"], buy_below=cfg["buy_below"],
                sell_above=cfg["sell_above"],
                fear_max=cfg["fear_max"], greed_min=cfg["greed_min"],
                qqq_gc=qqq_gc, gc_delay_days=d,
            )
            p = calc_perf(df, taxes)
            row[f"{ticker}_cagr"]       = p["cagr_pct"]
            row[f"{ticker}_mdd"]        = p["mdd_pct"]
            row[f"{ticker}_total_ret"]  = p["total_return_pct"]
            row[f"{ticker}_final"]      = p["final_assets"]
            row[f"{ticker}_cycles"]     = p["cycles"]
            row[f"{ticker}_win_rate"]   = p["win_rate"]
            row[f"{ticker}_avg_hold"]   = p["avg_hold_days"]
            row[f"{ticker}_gc_init"]    = p["gc_delay_initiated"]
            row[f"{ticker}_gc_exec"]    = p["gc_delay_executed"]
            row[f"{ticker}_tax"]        = p["total_tax_paid"]
        results.append(row)
        # 진행 표시
        tq = row["TQQQ_cagr"]
        so = row["SOXL_cagr"]
        dtq = tq - base_perf["TQQQ"]["cagr_pct"]
        dso = so - base_perf["SOXL"]["cagr_pct"]
        print(f"  delay={d:3d}일  TQQQ {tq:.2f}% ({dtq:+.2f}%p)  SOXL {so:.2f}% ({dso:+.2f}%p)")

    # ── 최적 탐색 ─────────────────────────────────────────────────
    df_r = pd.DataFrame(results)

    print("\n" + "=" * 70)
    print("[ CAGR 기준 최적 지연일수 ]")
    print("=" * 70)

    for ticker in TICKER_CONFIG:
        col   = f"{ticker}_cagr"
        best  = df_r.loc[df_r[col].idxmax()]
        worst = df_r.loc[df_r[col].idxmin()]
        base_cagr = base_perf[ticker]["cagr_pct"]
        print(f"\n{ticker}:")
        print(f"  Base  : CAGR {base_cagr:.2f}%  MDD {base_perf[ticker]['mdd_pct']:.1f}%  "
              f"평균보유 {base_perf[ticker]['avg_hold_days']:.1f}일")
        print(f"  최적  : delay={int(best['delay_days'])}일  "
              f"CAGR {best[col]:.2f}% ({best[col]-base_cagr:+.2f}%p)  "
              f"MDD {best[f'{ticker}_mdd']:.1f}%  "
              f"평균보유 {best[f'{ticker}_avg_hold']:.1f}일")
        print(f"  최하  : delay={int(worst['delay_days'])}일  "
              f"CAGR {worst[col]:.2f}% ({worst[col]-base_cagr:+.2f}%p)")

    # ── 전체 테이블 출력 ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("[ 전체 결과 테이블 ]")
    print(f"  {'지연일':>5}  {'TQ_CAGR':>8}  {'TQ_MDD':>7}  {'TQ_보유일':>8}  "
          f"{'SX_CAGR':>8}  {'SX_MDD':>7}  {'SX_보유일':>8}")
    print("  " + "-" * 60)
    tq_base = base_perf["TQQQ"]["cagr_pct"]
    sx_base = base_perf["SOXL"]["cagr_pct"]
    for r in results:
        d   = int(r["delay_days"])
        tqc = r["TQQQ_cagr"]
        tqm = r["TQQQ_mdd"]
        tqh = r["TQQQ_avg_hold"]
        sxc = r["SOXL_cagr"]
        sxm = r["SOXL_mdd"]
        sxh = r["SOXL_avg_hold"]
        # 최적 강조
        tq_mark = " ★" if tqc == df_r["TQQQ_cagr"].max() else ""
        sx_mark = " ★" if sxc == df_r["SOXL_cagr"].max() else ""
        print(f"  {d:>5}일  {tqc:>+8.2f}  {tqm:>7.1f}  {tqh:>8.1f}  "
              f"{sxc:>+8.2f}  {sxm:>7.1f}  {sxh:>8.1f}{tq_mark}{sx_mark}")

    # ── Google Sheet 저장 ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Google Sheet 저장 중...")
    _write_sheet(df_r, base_perf)


def _write_sheet(df_r: pd.DataFrame, base_perf: dict):
    from sheets_manager import SheetsManager
    from _env_loader import get_spreadsheet_id
    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc_client = sm._get_client()

    title = f"GC_Delay_Optimization_{START_DATE[:4]}_{END_DATE[:4]}"
    ss    = gc_client.create(title)
    url   = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    ws = ss.sheet1
    ws.update_title("CAGR_최적화")

    header_rows = [
        [f"GC 매도지연 일수 최적화  {START_DATE} ~ {END_DATE}  초기자본: ${CAPITAL:,.0f}"],
        [f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"Base: RSI(2)+F&G+QQQ Crash Guard ({QQQ_CRASH_PCT}%→{QQQ_COOLDOWN}일)  "
         f"GC: QQQ MA{GC_MA_FAST}>MA{GC_MA_SLOW} 구간 SELL 지연 (사이클당1회)"],
        [],
        ["[ Base 성과 ]"],
        ["종목", "CAGR(%)", "MDD(%)", "총수익률(%)", "최종자산($)", "사이클수", "평균보유일", "양도세($)"],
    ]
    for ticker in TICKER_CONFIG:
        p = base_perf[ticker]
        header_rows.append([ticker, p["cagr_pct"], p["mdd_pct"], p["total_return_pct"],
                             p["final_assets"], p["cycles"], p["avg_hold_days"], p["total_tax_paid"]])
    header_rows.append([])
    header_rows.append(["[ delay_days별 성과 비교 (★ = CAGR 최대) ]"])

    tq_col = [
        "지연일수",
        "TQQQ_CAGR(%)", "TQQQ_MDD(%)", "TQQQ_총수익률(%)", "TQQQ_최종자산($)",
        "TQQQ_사이클수", "TQQQ_승률(%)", "TQQQ_평균보유일",
        "TQQQ_GC지연발생", "TQQQ_GC지연후매도", "TQQQ_양도세($)",
        "SOXL_CAGR(%)", "SOXL_MDD(%)", "SOXL_총수익률(%)", "SOXL_최종자산($)",
        "SOXL_사이클수", "SOXL_승률(%)", "SOXL_평균보유일",
        "SOXL_GC지연발생", "SOXL_GC지연후매도", "SOXL_양도세($)",
    ]
    header_rows.append(tq_col)

    tq_best_cagr = df_r["TQQQ_cagr"].max()
    sx_best_cagr = df_r["SOXL_cagr"].max()

    data_rows = []
    for _, r in df_r.iterrows():
        d = int(r["delay_days"])
        mark = ""
        if r["TQQQ_cagr"] == tq_best_cagr and r["SOXL_cagr"] == sx_best_cagr:
            mark = "★★"
        elif r["TQQQ_cagr"] == tq_best_cagr:
            mark = "★TQQQ"
        elif r["SOXL_cagr"] == sx_best_cagr:
            mark = "★SOXL"
        delay_label = f"{d}일{(' ' + mark) if mark else ''}"
        data_rows.append([
            delay_label,
            r["TQQQ_cagr"], r["TQQQ_mdd"], r["TQQQ_total_ret"], r["TQQQ_final"],
            r["TQQQ_cycles"], r["TQQQ_win_rate"], r["TQQQ_avg_hold"],
            r["TQQQ_gc_init"], r["TQQQ_gc_exec"], r["TQQQ_tax"],
            r["SOXL_cagr"], r["SOXL_mdd"], r["SOXL_total_ret"], r["SOXL_final"],
            r["SOXL_cycles"], r["SOXL_win_rate"], r["SOXL_avg_hold"],
            r["SOXL_gc_init"], r["SOXL_gc_exec"], r["SOXL_tax"],
        ])

    all_rows = header_rows + data_rows
    max_cols = max(len(r) for r in all_rows if r)
    from create_qqq_golden_cross_backtest import _col_letter
    col_l = _col_letter(max_cols)
    ws.update(range_name=f"A1:{col_l}{len(all_rows)}", values=all_rows)
    print(f"[GoogleSheets] CAGR_최적화 저장 완료 ({len(data_rows)}행)")
    print(f"[GoogleSheets] URL: {url}")
    return url


if __name__ == "__main__":
    main()
