"""
이평선 추세 추종 전략 (MA Trend-Following) 백테스트 + 최적화
───────────────────────────────────────────────────────────────
전략 원칙:
  • 참조 지수(QQQ → TQQQ, SOXX → SOXL)가 이평선 위에 있을 때 레버리지 ETF 보유
  • 이평선을 상향 돌파 → 분할 매수  (N 거래일에 걸쳐 균등 분할 진입)
  • 이평선을 하향 돌파 → 분할 매도  (N 거래일에 걸쳐 균등 분할 청산)
  • 전략 시작 시 이평선 위이면 첫날부터 분할 매수 개시

최적화:
  MA 기간  : [20, 30, 45, 60, 90, 120, 200]
  분할 수  : [1, 2, 3, 4, 5]
  목적함수 : TQQQ + SOXL 합산 최종 자산 최대화

탭 구성:
  Summary      ─ 최적 파라미터 성과표 + 사이클별 수익률
  TQQQ_Best    ─ 최적 파라미터 일별 백테스트 (TQQQ)
  SOXL_Best    ─ 최적 파라미터 일별 백테스트 (SOXL)
  TQQQ_Grid    ─ TQQQ 전체 파라미터 조합 결과
  SOXL_Grid    ─ SOXL 전체 파라미터 조합 결과
"""
from __future__ import annotations

import itertools
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

import create_nonsplit_best_algo_sheet as base
import create_rsi_price_target_sheet as rsi2
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id

import search_optimal_strategies as search_mod

CAPITAL   = search_mod.CAPITAL
START     = base.START_DATE
END       = base.END_DATE

# 참조 지수 매핑
BASE_INDEX = {"TQQQ": "QQQ", "SOXL": "SOXX"}

# 최적화 탐색 범위
MA_PERIODS  = [20, 30, 45, 60, 90, 120, 200]
SPLIT_COUNTS = [1, 2, 3, 4, 5]

# 색상 상수
COLOR_BUY       = rsi2.COLOR_BUY
COLOR_SELL      = rsi2.COLOR_SELL
COLOR_TITLE_BG  = rsi2.COLOR_TITLE_BG
COLOR_HDR_BG    = rsi2.COLOR_HDR_BG
COLOR_HDR_FG    = rsi2.COLOR_HDR_FG
COLOR_SECTION_BG = rsi2.COLOR_SECTION_BG


# ──────────────────────────────────────────────────────────────
# 데이터 다운로드
# ──────────────────────────────────────────────────────────────

def download_close(ticker: str) -> pd.Series:
    end_plus = (pd.Timestamp(END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START, end=end_plus, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"데이터 없음: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].dropna().astype(float)
    s.index = pd.to_datetime(s.index)
    return s


# ──────────────────────────────────────────────────────────────
# 핵심 시뮬레이션
# ──────────────────────────────────────────────────────────────

def simulate_ma_trend(
    price_3x: pd.Series,
    price_base: pd.Series,
    ma_period: int,
    n_splits: int,
    capital: float = CAPITAL,
) -> pd.DataFrame:
    """
    이평선 추세 추종 + 분할 매수/매도 시뮬레이션.

    price_3x   : 레버리지 ETF 종가 (TQQQ / SOXL)
    price_base : 참조 지수 종가 (QQQ / SOXX)
    ma_period  : 이동평균 기간 (일)
    n_splits   : 분할 수 (매수/매도 각각 N일 걸쳐 균등 실행)
    """
    # 공통 날짜 정렬
    common_idx = price_3x.index.intersection(price_base.index)
    p3x  = price_3x.reindex(common_idx).ffill().dropna()
    pb   = price_base.reindex(common_idx).ffill().dropna()
    ma   = pb.rolling(ma_period).mean()

    cash      = float(capital)
    holdings  = 0.0
    buy_rem   = 0   # 남은 매수 분할 수
    sell_rem  = 0   # 남은 매도 분할 수
    prev_above = None   # 이전 날 기준선 위/아래
    initial_trigger_done = False  # 최초 진입 처리 여부

    records = []

    for date in p3x.index:
        px     = float(p3x[date])
        pb_px  = float(pb[date])
        ma_px  = float(ma[date]) if not pd.isna(ma[date]) else float("nan")

        above_ma = (pb_px >= ma_px) if not np.isnan(ma_px) else None

        # MA 미확정 구간
        if above_ma is None:
            records.append({
                "date": date.strftime("%Y-%m-%d"),
                "close": round(px, 2),
                "base_close": round(pb_px, 2),
                f"ma{ma_period}": "",
                "above_ma": "",
                "action": "WAIT",
                "trade_qty": 0.0,
                "holdings": round(holdings, 4),
                "cash": round(cash, 2),
                "total_assets": round(cash + holdings * px, 2),
                "return_pct": round((cash + holdings * px - capital) / capital * 100, 2),
                "signal_note": "",
            })
            continue

        signal_note = ""
        action      = "HOLD"
        trade_qty   = 0.0

        # 최초 MA 확정 시점
        if prev_above is None:
            if above_ma:
                buy_rem  = n_splits   # 최초 상태가 이평선 위 → 매수 개시
                signal_note = f"초기진입 개시({n_splits}분할)"
            # 최초 상태가 이평선 아래 → 매수 기회 대기
            initial_trigger_done = True

        else:
            # 상향 돌파
            if above_ma and not prev_above:
                buy_rem   = n_splits
                sell_rem  = 0
                signal_note = f"상향돌파→매수{n_splits}분할"
            # 하향 돌파
            elif not above_ma and prev_above:
                sell_rem  = n_splits
                buy_rem   = 0
                signal_note = f"하향돌파→매도{n_splits}분할"

        # 매수 분할 실행 (현금 → 보유)
        if buy_rem > 0 and cash > 0:
            deploy = cash / buy_rem       # 현재 현금을 남은 분할 수로 나눠 배치
            qty    = deploy / px
            holdings += qty
            cash     -= deploy
            buy_rem  -= 1
            action    = "BUY"
            trade_qty = round(qty, 4)
            if signal_note == "":
                signal_note = f"매수분할({n_splits - buy_rem}/{n_splits})"

        # 매도 분할 실행 (보유 → 현금)
        elif sell_rem > 0 and holdings > 0:
            qty      = holdings / sell_rem
            cash     += qty * px
            holdings -= qty
            sell_rem -= 1
            action    = "SELL"
            trade_qty = round(-qty, 4)
            if signal_note == "":
                signal_note = f"매도분할({n_splits - sell_rem}/{n_splits})"

        prev_above = above_ma
        total_assets = cash + holdings * px
        records.append({
            "date": date.strftime("%Y-%m-%d"),
            "close": round(px, 2),
            "base_close": round(pb_px, 2),
            f"ma{ma_period}": round(ma_px, 2),
            "above_ma": "○" if above_ma else "✗",
            "action": action,
            "trade_qty": trade_qty,
            "holdings": round(holdings, 4),
            "cash": round(cash, 2),
            "total_assets": round(total_assets, 2),
            "return_pct": round((total_assets - capital) / capital * 100, 2),
            "signal_note": signal_note,
        })

    # 보유 중인 주식을 최종일 청산하여 성과 계산 (백테스트 평가 기준)
    return pd.DataFrame(records)


def _extract_cycles(df: pd.DataFrame) -> list[dict]:
    """매수→매도 사이클 추출"""
    cycles = []
    cycle_no = 0
    in_buy = False
    buy_date = buy_price = start_cash = None
    holdings = 0.0
    cash     = 0.0

    for _, row in df.iterrows():
        if row["action"] == "BUY" and not in_buy:
            in_buy    = True
            buy_date  = row["date"]
            buy_price = row["close"]
            start_cash = row["cash"] + row["holdings"] * row["close"]

        elif row["action"] == "SELL" and in_buy:
            holdings = float(row["holdings"])
            cash     = float(row["cash"])
            if holdings < 1e-6:
                # 완전 청산
                in_buy    = False
                cycle_no += 1
                end_cash   = float(row["total_assets"])
                ret_pct    = round((end_cash - start_cash) / start_cash * 100, 2) if start_cash else 0.0
                cycles.append({
                    "cycle_no":         cycle_no,
                    "buy_date":         buy_date,
                    "buy_price":        buy_price,
                    "sell_date":        row["date"],
                    "sell_price":       row["close"],
                    "start_assets":     round(start_cash, 2),
                    "end_assets":       round(end_cash, 2),
                    "cycle_return_pct": ret_pct,
                })

    # 미결 사이클
    open_cycle = None
    if in_buy:
        cycle_no += 1
        open_cycle = {"cycle_no": cycle_no, "buy_date": buy_date, "buy_price": buy_price, "sell_date": "(보유중)"}

    return cycles, open_cycle


# ──────────────────────────────────────────────────────────────
# 최적화
# ──────────────────────────────────────────────────────────────

def optimize(tqqq_close, soxx_close, soxl_close, qqq_close) -> dict:
    """TQQQ+SOXL 합산 최종자산 기준으로 최적 (ma_period, n_splits) 탐색"""
    results = {}
    combos = list(itertools.product(MA_PERIODS, SPLIT_COUNTS))
    total = len(combos)
    print(f"[최적화] {total}개 조합 탐색 시작...")

    for idx, (ma, ns) in enumerate(combos, 1):
        df_t = simulate_ma_trend(tqqq_close, qqq_close,  ma, ns)
        df_s = simulate_ma_trend(soxl_close, soxx_close, ma, ns)

        ta_t = float(df_t["total_assets"].iloc[-1])
        ta_s = float(df_s["total_assets"].iloc[-1])
        total_assets = ta_t + ta_s

        results[(ma, ns)] = {
            "tqqq_assets": ta_t, "soxl_assets": ta_s, "combined": total_assets,
        }
        if idx % 7 == 0 or idx == total:
            best_so_far = max(results, key=lambda k: results[k]["combined"])
            print(f"  [{idx:>3}/{total}] 현재 최고: MA={best_so_far[0]:>3}일 분할={best_so_far[1]}  합산자산 ${results[best_so_far]['combined']:>15,.2f}")

    best = max(results, key=lambda k: results[k]["combined"])
    print(f"\n[최적화 완료] ★ 최적 파라미터: MA={best[0]}일, 분할={best[1]}회")
    return results, best


# ──────────────────────────────────────────────────────────────
# 스타일 헬퍼
# ──────────────────────────────────────────────────────────────

def _pct_bg(pct: float) -> dict:
    if pct >= 0:
        intensity = min(pct / 1200.0, 1.0)
        return {"red": 1.0, "green": 1.0 - intensity * 0.55, "blue": 1.0 - intensity * 0.55}
    else:
        intensity = min(abs(pct) / 60.0, 1.0)
        return {"red": 1.0 - intensity * 0.55, "green": 1.0 - intensity * 0.55, "blue": 1.0}


def _bar(pct: float, max_abs: float, width: int = 20) -> str:
    if max_abs == 0:
        return f"  {pct:+.2f}%"
    n = round(abs(pct) / max_abs * (width // 2))
    if pct >= 0:
        return " " * (width // 2) + "▓" * n + f"  +{pct:.2f}%"
    else:
        return " " * (width // 2 - n) + "░" * n + f"  {pct:.2f}%"


# ──────────────────────────────────────────────────────────────
# Summary 탭
# ──────────────────────────────────────────────────────────────

def write_summary(ss, all_sim: dict, opt_results: dict, best_key: tuple):
    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=800, cols=20)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[list] = []
    sm: dict = {}

    def R(v): rows.append(v); return len(rows)

    best_ma, best_ns = best_key

    R([f"이평선 추세 추종 전략  ─  MA Trend-Following + 분할 매수/매도"])
    R([f"생성: {now}   |   기간: {START} ~ {END}   |   초기자본: $100,000   |   체결: LOC"])
    R([f"참조지수:  TQQQ ← QQQ  |  SOXL ← SOXX   |   이평선: SMA(N)   |   분할: 매수/매도 N거래일 균등 분할"])
    R([])

    # ── 최적 파라미터 ────────────────────────────────────────
    R(["[ 최적화 결과 ]"])
    sm["opt_sec"] = len(rows)
    R(["항목", "값", "설명"])
    sm["opt_hdr"] = len(rows)
    R(["최적 MA 기간", f"{best_ma}일", f"QQQ/SOXX의 SMA({best_ma}) 기준으로 매매"])
    R(["최적 분할 수", f"{best_ns}회", f"진입/청산 각각 {best_ns}거래일에 걸쳐 균등 실행"])
    def _cp(df): return base.calc_perf(df.set_index(pd.to_datetime(df["date"]))["total_assets"])
    t_ret_t, cagr_t, mdd_t, fa_t = _cp(all_sim["TQQQ"])
    t_ret_s, cagr_s, mdd_s, fa_s = _cp(all_sim["SOXL"])
    R(["TQQQ 총수익률", f"{t_ret_t:.2f}%", f"CAGR {cagr_t:.2f}%  |  MDD {mdd_t:.2f}%  |  최종자산 ${fa_t:,.2f}"])
    R(["SOXL 총수익률", f"{t_ret_s:.2f}%", f"CAGR {cagr_s:.2f}%  |  MDD {mdd_s:.2f}%  |  최종자산 ${fa_s:,.2f}"])
    R(["합산 최종자산", f"${fa_t + fa_s:,.2f}", "TQQQ + SOXL (각 $100,000 시작)"])
    R([])

    # ── 주요 조합 Top 10 ─────────────────────────────────────
    R(["[ 전체 조합 성과 Top 10  (TQQQ+SOXL 합산 최종자산 기준) ]"])
    sm["top10_sec"] = len(rows)
    R(["순위", "MA 기간", "분할 수", "TQQQ 최종자산($)", "SOXL 최종자산($)", "합산 최종자산($)", "비고"])
    sm["top10_hdr"] = len(rows)
    sm["top10_start"] = len(rows) + 1
    sorted_combos = sorted(opt_results.items(), key=lambda x: x[1]["combined"], reverse=True)
    for rank, ((ma, ns), v) in enumerate(sorted_combos[:10], 1):
        note = "★ 최적" if (ma, ns) == best_key else ""
        R([rank, f"{ma}일", ns, round(v["tqqq_assets"], 2), round(v["soxl_assets"], 2), round(v["combined"], 2), note])
    sm["top10_end"] = len(rows)
    R([])

    # ── TQQQ 사이클 분석 ──────────────────────────────────────
    for ticker, df_sim in [("TQQQ", all_sim["TQQQ"]), ("SOXL", all_sim["SOXL"])]:
        t_ret, cagr, mdd, fa = _cp(df_sim)
        completed, open_cycle = _extract_cycles(df_sim)
        R([f"[ {ticker}  매매 사이클  /  MA={best_ma}일  분할={best_ns}회  총수익률={t_ret:.2f}%  CAGR={cagr:.2f}%  MDD={mdd:.2f}% ]"])
        sm[f"cyc_sec_{ticker}"] = len(rows)
        R(["Cycle #", "매수일", "매수가($)", "매도일", "매도가($)", "시작자산($)", "종료자산($)", "수익률 / 바"])
        sm[f"cyc_hdr_{ticker}"] = len(rows)
        sm[f"cyc_data_{ticker}"] = len(rows) + 1
        max_abs = max((abs(float(c["cycle_return_pct"])) for c in completed), default=1.0)
        for cyc in completed:
            pct = float(cyc["cycle_return_pct"])
            R([cyc["cycle_no"], cyc["buy_date"], cyc["buy_price"],
               cyc["sell_date"], cyc["sell_price"],
               cyc["start_assets"], cyc["end_assets"],
               _bar(pct, max_abs)])
        if open_cycle:
            R([open_cycle["cycle_no"], open_cycle["buy_date"], open_cycle["buy_price"], "(보유중)", "", "", "", "진행중"])
        sm[f"cyc_end_{ticker}"] = len(rows)
        R([])

    ws.update(range_name=f"A1:J{len(rows)}", values=rows)

    # ── 스타일 배치 ──────────────────────────────────────────
    reqs = []

    def _hdr_row(row_no, ncols=10):
        reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    def _sec_row(row_no, ncols=10, bg=None):
        bg = bg or COLOR_SECTION_BG
        reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {"userEnteredFormat": {"backgroundColor": bg, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    # 타이틀
    reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 20},
        "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TITLE_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True, "fontSize": 14}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    _sec_row(sm["opt_sec"])
    _hdr_row(sm["opt_hdr"])
    _sec_row(sm["top10_sec"])
    _hdr_row(sm["top10_hdr"])

    # Top10 데이터 행 색칠
    for i in range(sm["top10_start"], sm["top10_end"] + 1):
        row_data = rows[i - 1]
        if row_data[-1] == "★ 최적":
            reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": i - 1, "endRowIndex": i, "startColumnIndex": 0, "endColumnIndex": 7},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1.0, "green": 0.96, "blue": 0.7}, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    for ticker in ["TQQQ", "SOXL"]:
        _sec_row(sm[f"cyc_sec_{ticker}"])
        _hdr_row(sm[f"cyc_hdr_{ticker}"])
        completed, _ = _extract_cycles(all_sim[ticker])
        max_abs = max((abs(float(c["cycle_return_pct"])) for c in completed), default=1.0)
        for idx, cyc in enumerate(completed):
            row_no = sm[f"cyc_data_{ticker}"] + idx
            pct    = float(cyc["cycle_return_pct"])
            shade  = rsi2._shade_for_centered(pct)
            reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 7, "endColumnIndex": 8},
                "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    ws.spreadsheet.batch_update({"requests": reqs})
    print(f"[GoogleSheets] {title} 저장 완료")


# ──────────────────────────────────────────────────────────────
# 일별 백테스트 탭
# ──────────────────────────────────────────────────────────────

def write_daily_tab(ss, ticker: str, df: pd.DataFrame, ma_period: int, n_splits: int):
    title = f"{ticker}_Best"
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 10), cols=len(headers))

    t_ret, cagr, mdd, fa = base.calc_perf(df.set_index(pd.to_datetime(df["date"]))["total_assets"])
    base_ticker = BASE_INDEX[ticker]
    trades = int((df["action"].isin(["BUY", "SELL"])).sum())

    meta = [
        [f"{ticker}  —  이평선 추세 추종  |  참조: {base_ticker} SMA({ma_period})  |  분할: {n_splits}회  |  LOC 체결"],
        [f"총수익률: {t_ret:.2f}%   CAGR: {cagr:.2f}%   MDD: {mdd:.2f}%   최종자산: ${fa:,.2f}"],
        [f"기간: {START} ~ {END}   BUY/SELL 총 {trades}회"],
        [f"전략: {base_ticker} 종가 ≥ SMA({ma_period}) → {ticker} 분할매수 ({n_splits}거래일)  |  {base_ticker} 종가 < SMA({ma_period}) → {ticker} 분할매도 ({n_splits}거래일)"],
        headers,
    ]
    data_row0 = len(meta)
    col_letter = chr(64 + min(len(headers), 26))

    ws.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)

    values = []
    for row in df.values.tolist():
        processed = []
        for v in row:
            if v == "" or (isinstance(v, float) and np.isnan(v)):
                processed.append("")
            else:
                processed.append(str(v))
        values.append(processed)

    if values:
        ws.update(range_name=f"A{data_row0 + 1}:{col_letter}{data_row0 + len(values)}", values=values)

    col_idx = {c: i for i, c in enumerate(headers)}
    total_rows = data_row0 + len(values) + 1
    reqs = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": data_row0 - 1, "endRowIndex": data_row0, "startColumnIndex": 0, "endColumnIndex": len(headers)},
        "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}}]

    center_cols = ["above_ma", "trade_qty", "holdings", "return_pct"]
    for c in center_cols:
        if c in col_idx:
            ci = col_idx[c]
            reqs.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": data_row0, "endRowIndex": total_rows, "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment"}})
    ws.spreadsheet.batch_update({"requests": reqs})

    color_reqs = []
    ma_col = f"ma{ma_period}"
    for i, row in df.iterrows():
        row_idx = data_row0 + df.index.get_loc(i)
        if row["action"] == "BUY":
            bg = COLOR_BUY
        elif row["action"] == "SELL":
            bg = COLOR_SELL
        else:
            continue
        color_reqs.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 0, "endColumnIndex": len(headers)},
            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
            "fields": "userEnteredFormat.backgroundColor"}})
    if color_reqs:
        ws.spreadsheet.batch_update({"requests": color_reqs})

    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행, 거래 {trades}회)")


# ──────────────────────────────────────────────────────────────
# 그리드 서치 탭
# ──────────────────────────────────────────────────────────────

def write_grid_tab(ss, ticker: str, opt_results: dict, best_key: tuple):
    title = f"{ticker}_Grid"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=200, cols=20)

    rows = []
    rows.append([f"{ticker}  전체 파라미터 조합 성과표  (기간: {START} ~ {END})"])
    rows.append(["MA 기간", "분할 수", f"{ticker} 최종자산($)", "합산 최종자산($)", "비고"])
    hdr_row = len(rows)

    sorted_combos = sorted(opt_results.items(), key=lambda x: x[1]["combined"], reverse=True)
    for (ma, ns), v in sorted_combos:
        asset_key = f"{ticker.lower()}_assets"
        note = "★ 최적" if (ma, ns) == best_key else ""
        rows.append([f"{ma}일", ns, round(v[asset_key], 2), round(v["combined"], 2), note])

    ws.update(range_name=f"A1:E{len(rows)}", values=rows)

    reqs = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 5},
        "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TITLE_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": hdr_row - 1, "endRowIndex": hdr_row, "startColumnIndex": 0, "endColumnIndex": 5},
        "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}}]

    # 최적 행 강조
    for i, row in enumerate(rows[hdr_row:], hdr_row + 1):
        if row[-1] == "★ 최적":
            reqs.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": i - 1, "endRowIndex": i, "startColumnIndex": 0, "endColumnIndex": 5},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1.0, "green": 0.96, "blue": 0.7}, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    # 최종자산 색상 그라디언트 (C열)
    assets = [float(row[2]) for row in rows[hdr_row:] if isinstance(row[2], (int, float))]
    min_a  = min(assets) if assets else 0
    max_a  = max(assets) if assets else 1
    rng    = max_a - min_a if max_a != min_a else 1
    for i, (_, v) in enumerate(sorted_combos):
        asset_val = v[f"{ticker.lower()}_assets"]
        ratio = (asset_val - min_a) / rng
        row_no = hdr_row + i + 1
        bg = {"red": 1.0 - ratio * 0.4, "green": 0.7 + ratio * 0.3, "blue": 0.7 - ratio * 0.3}
        reqs.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 2, "endColumnIndex": 3},
            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
            "fields": "userEnteredFormat.backgroundColor"}})

    ws.spreadsheet.batch_update({"requests": reqs})
    print(f"[GoogleSheets] {title} 저장 완료")


# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print(f"[이평선 추세 추종 전략] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  MA 기간 탐색: {MA_PERIODS}")
    print(f"  분할 수 탐색: {SPLIT_COUNTS}")
    print("=" * 80)

    # 가격 데이터 다운로드
    print("[데이터] 다운로드 중...")
    tqqq_close = download_close("TQQQ")
    soxl_close = download_close("SOXL")
    qqq_close  = download_close("QQQ")
    soxx_close = download_close("SOXX")
    print(f"  TQQQ {len(tqqq_close)}일  /  SOXL {len(soxl_close)}일  /  QQQ {len(qqq_close)}일  /  SOXX {len(soxx_close)}일")

    # 최적화
    print()
    opt_results, best_key = optimize(tqqq_close, soxx_close, soxl_close, qqq_close)
    best_ma, best_ns = best_key

    # 최적 파라미터로 최종 시뮬레이션
    print(f"\n[최종 시뮬레이션] MA={best_ma}일, 분할={best_ns}회")
    df_tqqq = simulate_ma_trend(tqqq_close, qqq_close,  best_ma, best_ns)
    df_soxl = simulate_ma_trend(soxl_close, soxx_close, best_ma, best_ns)

    def _perf(df):
        s = df.set_index(pd.to_datetime(df["date"]))["total_assets"]
        return base.calc_perf(s)

    t_ret_t, cagr_t, mdd_t, fa_t = _perf(df_tqqq)
    t_ret_s, cagr_s, mdd_s, fa_s = _perf(df_soxl)
    print(f"  TQQQ: {t_ret_t:.2f}%  CAGR {cagr_t:.2f}%  MDD {mdd_t:.2f}%  최종자산 ${fa_t:,.2f}")
    print(f"  SOXL: {t_ret_s:.2f}%  CAGR {cagr_s:.2f}%  MDD {mdd_s:.2f}%  최종자산 ${fa_s:,.2f}")

    all_sim = {"TQQQ": df_tqqq, "SOXL": df_soxl}

    # 구글 시트 생성
    sheet_title = f"MA추세추종전략_{datetime.now().strftime('%Y%m%d_%H%M')}"
    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc = sm._get_client()
    ss = gc.create(sheet_title)
    print(f"\n[GoogleSheets] '{sheet_title}' 생성됨")

    write_summary(ss, all_sim, opt_results, best_key)
    for ticker, df_sim in [("TQQQ", df_tqqq), ("SOXL", df_soxl)]:
        write_daily_tab(ss, ticker, df_sim, best_ma, best_ns)
    write_grid_tab(ss, "TQQQ", opt_results, best_key)
    write_grid_tab(ss, "SOXL", opt_results, best_key)

    # 기본 시트 제거
    for default_name in ["Sheet1", "시트1"]:
        try:
            ss.del_worksheet(ss.worksheet(default_name))
        except Exception:
            pass

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print("\n" + "=" * 80)
    print(f"[완료] 파일명 : {ss.title}")
    print(f"[완료] 링크   : {url}")
    print(f"탭: {' | '.join(w.title for w in ss.worksheets())}")
    print("=" * 80)


if __name__ == "__main__":
    main()
