"""
TQQQ / SOXL 장기 역사 백테스트  (2011-01-01 ~ 오늘)
──────────────────────────────────────────────────────
• 현재 운영 시트(2021~)와 별도의 새 Google Spreadsheet에 저장
• 알고리즘: 현재와 동일한 RSI(2)+F&G (TQQQ buy<15/sell>75, SOXL buy<15/sell>90)
• F&G 데이터: 2021-01-04 이전 구간은 F&G=50(중립) 적용 → 순수 RSI(2)처럼 동작
• 앱 / 현재 시트에는 영향 없음
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# ── 파라미터 ─────────────────────────────────────────────────────
START_DATE = "2011-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")
CAPITAL    = 100_000.0
NEW_SHEET_TITLE = f"TQQQ_SOXL_Historical_{START_DATE[:4]}_{END_DATE[:4]}"

TICKER_CONFIG = {
    "TQQQ": {"period": 2, "buy_below": 15, "sell_above": 75, "fear_max": 25, "greed_min": 90},
    "SOXL": {"period": 2, "buy_below": 15, "sell_above": 90, "fear_max": 25, "greed_min": 90},
}


# ── 데이터 다운로드 ──────────────────────────────────────────────

def download_close(ticker: str) -> pd.Series:
    import yfinance as yf
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"주가 데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].squeeze()
    s.index = pd.to_datetime(s.index).normalize()
    return s.sort_index().dropna()


# ── 프로덕션 시뮬레이션 함수 import (동일 로직 보장) ────────────
from create_rsi_fng_sheet import simulate_with_fng


# ── 성과 계산 ────────────────────────────────────────────────────

def calc_perf(df: pd.DataFrame, taxes: dict) -> dict:
    ta = df["total_assets"].astype(float)
    initial = CAPITAL
    final   = float(ta.iloc[-1])

    # MDD
    peak = initial
    mdd  = 0.0
    for v in ta:
        if v > peak:
            peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd:
            mdd = dd

    dates = pd.to_datetime(df["date"])
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1/365.25)
    cagr  = ((final / initial) ** (1/years) - 1) * 100

    buy_rows  = df[df["action"] == "BUY"]
    sell_rows = df[df["action"] == "SELL"]
    blocked   = int((df["fng_blocked"] != "").sum())

    # 사이클 추출
    cycles = []
    in_pos = False
    buy_date = buy_px = None
    for _, row in df.iterrows():
        if row["action"] == "BUY" and not in_pos:
            in_pos   = True
            buy_date = row["date"]
            buy_px   = float(row["close"])
        elif row["action"] == "SELL" and in_pos:
            sell_px  = float(row["close"])
            ret      = (sell_px - buy_px) / buy_px * 100 if buy_px else 0.0
            hold     = (pd.Timestamp(row["date"]) - pd.Timestamp(buy_date)).days
            cycles.append({"buy_date": buy_date, "sell_date": row["date"],
                           "buy_px": buy_px, "sell_px": sell_px,
                           "ret_pct": round(ret, 2), "hold_days": hold})
            in_pos = False

    rets  = [c["ret_pct"] for c in cycles]
    wins  = [r for r in rets if r > 0]
    total_tax = sum(v.get("tax", 0) for v in taxes.values())

    return {
        "total_return_pct": round((final / initial - 1) * 100, 2),
        "cagr_pct":         round(cagr, 2),
        "mdd_pct":          round(mdd, 2),
        "final_assets":     round(final, 0),
        "buy_count":        len(buy_rows),
        "sell_count":       len(sell_rows),
        "fng_blocked":      blocked,
        "cycles":           len(cycles),
        "win_rate":         round(len(wins) / len(rets) * 100, 1) if rets else 0,
        "avg_ret_pct":      round(sum(rets) / len(rets), 2) if rets else 0,
        "avg_hold_days":    round(sum(c["hold_days"] for c in cycles) / len(cycles), 1) if cycles else 0,
        "total_tax_paid":   round(total_tax, 0),
        "cycle_list":       cycles,
    }


# ── 사이클+잔고+양도세 검증 테이블 생성 ─────────────────────────

def build_cycle_balance_rows(df: pd.DataFrame, annual_taxes: dict,
                             ticker: str, cfg: dict) -> list:
    """
    사이클별 매도후잔고와 연말 양도세 차감을 시계열로 나열하는 테이블 생성.

    컬럼:
      # | 구분 | 날짜 | 매수가 | 매도가 | 보유일 | 수익률% | 매도후잔고$ | 세금차감$ | 이월잔고$

    세금행 구분:
      - SELL 당일 세금 적용: 매도 → 세금 → 이월잔고 (한 행)
      - BUY 전 세금 적용:   "── YYYY년 양도세 ──" 별도 행 삽입
    """
    # annual_taxes에서 deducted_on 기준으로 tax 매핑
    tax_by_date: dict[str, dict] = {}
    for yr, info in annual_taxes.items():
        if info.get("tax", 0) > 0 and info.get("deducted_on"):
            deducted_on = info["deducted_on"]
            tax_by_date[deducted_on] = {
                "year": yr,
                "tax": info["tax"],
                "total_before": info.get("total_before", 0),
                "deducted_on": deducted_on,
            }

    rows = []
    cycle_num = 0
    buy_date = buy_price = None
    pending_tax_rows: list[dict] = []   # BUY 전 세금행 버퍼

    for _, row in df.iterrows():
        date   = str(row["date"])
        action = str(row["action"])

        # ── BUY 전 세금행 처리 ─────────────────────────────────
        if action == "BUY":
            # 이 날 세금이 적용됐으면 BUY 행 앞에 세금 행 삽입
            if date in tax_by_date:
                ti = tax_by_date[date]
                # 세금 적용 후 잔고 = 이 날 total_assets (세금 차감+매수 완료 후)
                # → 매수 전 잔고는 total_before (전년 말 총자산, 근사치로 충분)
                bal_before_tax = ti["total_before"]
                tax_amt        = ti["tax"]
                bal_after_tax  = float(row["total_assets"]) + float(row.get("buy_cash_used") or 0)
                # buy_cash_used = 매수에 투입된 현금 = 세금 차감 후 남은 현금
                # total_assets 매수 후는 현금=0, holdings=all → 세금 반영 전 현금 근사: buy_cash_used + tax
                try:
                    used = float(row.get("buy_cash_used") or 0)
                except Exception:
                    used = 0.0
                cash_before_buy = used + tax_amt  # 세금 차감 전 현금 (≈ 이월잔고)
                rows.append([
                    "",
                    f"▶ {ti['year']}년 양도세",
                    ti["deducted_on"],
                    "", "", "", "",
                    f"${cash_before_buy:,.0f}",
                    f"-${tax_amt:,.0f}",
                    f"${cash_before_buy - tax_amt:,.0f}",
                ])

            cycle_num += 1
            buy_date  = date
            buy_price = float(row["close"])

        elif action == "SELL" and buy_date is not None:
            sell_price  = float(row["close"])
            balance     = float(row["total_assets"])
            hold_days   = (pd.Timestamp(date) - pd.Timestamp(buy_date)).days
            ret_pct     = (sell_price / buy_price - 1) * 100

            # SELL 당일 세금 적용 여부
            try:
                tax_today = float(row.get("tax_deducted") or 0)
            except Exception:
                tax_today = 0.0

            if tax_today > 0 and date in tax_by_date:
                ti = tax_by_date[date]
                # 세금 차감 전 잔고 = balance + tax_today (프로덕션 로직: sell → tax 차감)
                bal_before_tax = balance + tax_today
                rows.append([
                    cycle_num,
                    "SELL+세금",
                    f"{buy_date} → {date}",
                    f"${buy_price:.2f}",
                    f"${sell_price:.2f}",
                    hold_days,
                    f"{ret_pct:+.1f}%",
                    f"${bal_before_tax:,.0f}",
                    f"-${tax_today:,.0f}  ({ti['year']}년)",
                    f"${balance:,.0f}",
                ])
            else:
                rows.append([
                    cycle_num,
                    "SELL",
                    f"{buy_date} → {date}",
                    f"${buy_price:.2f}",
                    f"${sell_price:.2f}",
                    hold_days,
                    f"{ret_pct:+.1f}%",
                    f"${balance:,.0f}",
                    "",
                    f"${balance:,.0f}",
                ])
            buy_date = None

    return rows


# ── Google Sheet 작성 ────────────────────────────────────────────

def write_to_new_sheet(results: dict[str, tuple[pd.DataFrame, dict, dict]]):
    from sheets_manager import SheetsManager
    from _env_loader import get_spreadsheet_id

    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc = sm._get_client()

    # 기존 시트가 있으면 재사용, 없으면 새로 생성
    _EXISTING_ID = "1Y-p5JoITaA4X2ltik-XSXK3zX2aa55Om-5k_8wU4U68"
    try:
        ss = gc.open_by_key(_EXISTING_ID)
        print(f"[GoogleSheets] 기존 스프레드시트 열기: {NEW_SHEET_TITLE}")
        # 기존 탭 모두 삭제 후 재작성
        for ws in ss.worksheets()[1:]:
            ss.del_worksheet(ws)
        ss.sheet1.clear()
        ss.sheet1.update_title("Summary")
    except Exception:
        print(f"[GoogleSheets] 새 스프레드시트 생성: {NEW_SHEET_TITLE}")
        ss = gc.create(NEW_SHEET_TITLE)
    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[GoogleSheets] URL: {url}")

    # Summary 탭
    ws_summary = ss.sheet1
    ws_summary.update_title("Summary")
    summary_rows = [
        [f"TQQQ / SOXL  RSI(2)+F&G  장기 역사 백테스트  {START_DATE} ~ {END_DATE}"],
        [f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   초기자본: ${CAPITAL:,.0f}   체결: LOC"],
        [f"알고리즘: TQQQ RSI<15/RSI>75   SOXL RSI<15/RSI>90   F&G 파라미터: 공포≤25→매도보류  탐욕≥90→매수보류"],
        [f"※ F&G 데이터는 2021-01-04 이전 구간에서 50(중립) 적용 → 2011~2020은 순수 RSI(2) 동작"],
        [],
        ["종목", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)",
         "사이클수", "승률(%)", "평균수익률(%)", "평균보유(일)",
         "매수횟수", "매도횟수", "F&G차단", "양도세합계($)"],
    ]
    for ticker, (df, taxes, perf) in results.items():
        summary_rows.append([
            ticker,
            perf["total_return_pct"], perf["cagr_pct"], perf["mdd_pct"],
            perf["final_assets"], perf["cycles"], perf["win_rate"],
            perf["avg_ret_pct"], perf["avg_hold_days"],
            perf["buy_count"], perf["sell_count"], perf["fng_blocked"],
            perf["total_tax_paid"],
        ])
    summary_rows.append([])

    # 연도별 수익률
    summary_rows.append(["[ 연도별 수익률 ]"])
    year_labels: list[str] = []
    yearly: dict[str, dict[str, float]] = {}
    for ticker, (df, taxes, perf) in results.items():
        df2 = df.copy()
        df2["year"] = pd.to_datetime(df2["date"]).dt.year
        yr_dict: dict[str, float] = {}
        current_yr = datetime.now().year
        for yr, grp in df2.groupby("year"):
            s = float(grp.iloc[0]["total_assets"])
            e = float(grp.iloc[-1]["total_assets"])
            if yr == current_yr:
                e += float(taxes.get(yr, {}).get("tax", 0))
            label = f"{yr}{'(진행중)' if yr == current_yr else ''}"
            yr_dict[label] = round((e / s - 1) * 100, 2)
            if label not in year_labels:
                year_labels.append(label)
        yearly[ticker] = yr_dict
    year_labels.sort()
    summary_rows.append(["종목"] + year_labels)
    for ticker in results:
        summary_rows.append([ticker] + [yearly[ticker].get(y, "") for y in year_labels])
    summary_rows.append([])

    # 사이클 테이블
    summary_rows.append(["[ 사이클 목록 ]"])
    for ticker, (df, taxes, perf) in results.items():
        summary_rows.append([f"▶ {ticker}"])
        summary_rows.append(["#", "매수일", "매수가($)", "매도일", "매도가($)",
                              "보유(일)", "수익률(%)"])
        for i, c in enumerate(perf["cycle_list"], 1):
            summary_rows.append([i, c["buy_date"], c["buy_px"], c["sell_date"],
                                  c["sell_px"], c["hold_days"], c["ret_pct"]])
        summary_rows.append([])

    max_cols = max((len(r) for r in summary_rows if r), default=1)
    col_letter = chr(64 + max_cols) if max_cols <= 26 else "Z"
    ws_summary.update(range_name=f"A1:{col_letter}{len(summary_rows)}", values=summary_rows)
    print(f"[GoogleSheets] Summary 저장 완료")

    # 종목별 일별 탭 (simulate_with_fng 출력 컬럼과 동일하게)
    headers = ["date", "close", "chg_pct", "fng", "rsi2", "fng_blocked",
               "buy_limit_expected_px", "sell_limit_expected_px",
               "buy_limit_px", "sell_limit_px",
               "action", "trade_qty", "buy_cash_used", "holdings",
               "cash", "total_assets", "return_pct", "annual_profit_ytd", "tax_deducted"]

    for ticker, (df, taxes, perf) in results.items():
        title = f"{ticker}_일별"
        ws = ss.add_worksheet(title=title, rows=max(5000, len(df)+10), cols=len(headers)+2)

        meta = [
            [f"{ticker}  RSI(2)+F&G  {START_DATE} ~ {END_DATE}"],
            [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%"
             f"   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,}"],
            [f"사이클: {perf['cycles']}회   승률: {perf['win_rate']}%"
             f"   F&G차단: {perf['fng_blocked']}회   양도세: ${perf['total_tax_paid']:,}"],
            [f"※ F&G 2011~2020 구간은 중립(50) 적용"],
            headers,
        ]
        data_rows = [[str(row.get(h, "")) for h in headers]
                     for _, row in df.iterrows()]

        col_letter = chr(64 + len(headers))
        ws.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)
        if data_rows:
            ws.update(range_name=f"A{len(meta)+1}:{col_letter}{len(meta)+len(data_rows)}",
                      values=data_rows)
        print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행, "
              f"BUY {perf['buy_count']}회 SELL {perf['sell_count']}회)")

    # ── 사이클+잔고 검증 탭 ────────────────────────────────────────
    cycle_hdr = ["#", "구분", "매수→매도", "매수가($)", "매도가($)",
                 "보유(일)", "수익률(%)", "매도후잔고($)", "양도세차감($)", "이월잔고($)"]
    for ticker, (df, taxes, perf) in results.items():
        cycle_rows = build_cycle_balance_rows(df, taxes, ticker, TICKER_CONFIG[ticker])
        title = f"{ticker}_사이클잔고"
        total_rows = len(cycle_rows) + 5
        ws_cyc = ss.add_worksheet(title=title, rows=max(500, total_rows), cols=len(cycle_hdr)+1)

        meta = [
            [f"{ticker}  사이클별 잔고 & 양도세 검증  {START_DATE} ~ {END_DATE}"],
            [f"buy: RSI<{TICKER_CONFIG[ticker]['buy_below']}  "
             f"sell: RSI>{TICKER_CONFIG[ticker]['sell_above']}  "
             f"fear_max:{TICKER_CONFIG[ticker]['fear_max']}  "
             f"greed_min:{TICKER_CONFIG[ticker]['greed_min']}  "
             f"| 초기자본: ${CAPITAL:,.0f}  최종: ${perf['final_assets']:,.0f}"],
            [f"▶ 세금행: 전년도 실현손익에 대한 양도세(22%) 차감 시점 표시  "
             f"(기본공제 $1,900 ≒ 250만원)"],
            [],
            cycle_hdr,
        ]
        col_letter = chr(64 + len(cycle_hdr))
        ws_cyc.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)
        if cycle_rows:
            ws_cyc.update(
                range_name=f"A{len(meta)+1}:{col_letter}{len(meta)+len(cycle_rows)}",
                values=cycle_rows,
            )
        print(f"[GoogleSheets] {title} 저장 완료 ({len(cycle_rows)}행)")

    return url, ss.id


# ── main ─────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"TQQQ/SOXL 장기 역사 백테스트  {START_DATE} ~ {END_DATE}")
    print(f"알고리즘: RSI(2)+F&G  (프로덕션 동일 로직)")
    print("=" * 70)

    # F&G 데이터
    try:
        from fear_greed_history import load_fng_history
        fng_base = load_fng_history()
        print(f"F&G 데이터: {fng_base.index.min().date()} ~ {fng_base.index.max().date()}")
        print("※ 이전 구간(2011~2020)은 F&G=50(중립) 자동 적용")
    except Exception as e:
        print(f"F&G 로드 실패: {e} → 전 기간 F&G=50")
        fng_base = pd.Series(dtype=float)

    results: dict[str, tuple[pd.DataFrame, dict, dict]] = {}

    for ticker, cfg in TICKER_CONFIG.items():
        print(f"\n[{ticker}] 가격 데이터 다운로드...")
        close = download_close(ticker)
        print(f"[{ticker}] {len(close)}일 ({close.index[0].date()} ~ {close.index[-1].date()})")

        # F&G 시리즈를 close 날짜 기준으로 정렬 (없으면 50)
        fng = fng_base.reindex(close.index, method="ffill").fillna(50).astype(int)

        print(f"[{ticker}] 시뮬레이션 실행... (프로덕션 동일 로직: fear_max={cfg['fear_max']}, greed_min={cfg['greed_min']})")
        df, taxes = simulate_with_fng(
            close=close,
            fng=fng,
            period=cfg["period"],
            buy_below=cfg["buy_below"],
            sell_above=cfg["sell_above"],
            fear_max=cfg["fear_max"],
            greed_min=cfg["greed_min"],
        )

        perf = calc_perf(df, taxes)
        results[ticker] = (df, taxes, perf)

        print(f"[{ticker}] 결과:")
        print(f"  총수익률  : {perf['total_return_pct']:+.1f}%")
        print(f"  CAGR      : {perf['cagr_pct']:.1f}%")
        print(f"  MDD       : {perf['mdd_pct']:.1f}%")
        print(f"  최종자산  : ${perf['final_assets']:,.0f}")
        print(f"  사이클    : {perf['cycles']}회  승률 {perf['win_rate']}%")
        print(f"  평균수익  : {perf['avg_ret_pct']:+.2f}%  평균보유 {perf['avg_hold_days']:.0f}일")
        print(f"  F&G차단   : {perf['fng_blocked']}회")
        print(f"  양도세합계: ${perf['total_tax_paid']:,.0f}")

        # 연도별 수익률 출력
        df2 = df.copy()
        df2["year"] = pd.to_datetime(df2["date"]).dt.year
        current_yr = datetime.now().year
        print(f"  연도별 수익률:")
        for yr, grp in df2.groupby("year"):
            s = float(grp.iloc[0]["total_assets"])
            e = float(grp.iloc[-1]["total_assets"])
            if yr == current_yr:
                e += float(taxes.get(yr, {}).get("tax", 0))
            pct = (e / s - 1) * 100
            bar = "█" * min(int(abs(pct) / 5), 20)
            sign = "+" if pct >= 0 else "-"
            suffix = "(진행중)" if yr == current_yr else ""
            print(f"    {yr}{suffix}: {pct:+.1f}% {bar}")

    # Google Sheet 저장
    print("\n" + "="*70)
    print("Google Sheet 저장 중...")
    url, sheet_id = write_to_new_sheet(results)

    # 최종 결과 요약 출력
    print("\n" + "="*70)
    print("[ 최종 결과 요약 ]")
    print(f"기간: {START_DATE} ~ {END_DATE}  초기자본: ${CAPITAL:,.0f}")
    print()
    for ticker, (_, _, perf) in results.items():
        print(f"{ticker}:")
        print(f"  총수익률 {perf['total_return_pct']:+.1f}% | CAGR {perf['cagr_pct']:.1f}% | "
              f"MDD {perf['mdd_pct']:.1f}% | 최종 ${perf['final_assets']:,.0f}")
        print(f"  사이클 {perf['cycles']}회 | 승률 {perf['win_rate']}% | "
              f"평균수익 {perf['avg_ret_pct']:+.2f}% | 평균보유 {perf['avg_hold_days']:.0f}일")
    print()
    print(f"Google Sheet URL: {url}")
    print("="*70)


if __name__ == "__main__":
    main()
