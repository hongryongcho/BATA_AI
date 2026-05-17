"""
TQQQ RSI(2) 매수 임계값 비교 분석
─────────────────────────────────────────────────────
buy_below 값 4가지(8, 10, 12, 15)에 대해
① RSI2 단독  ② RSI2 + FnG(최적 파라미터) 각각 백테스트 후
결과를 새 구글 시트로 출력.

탭 구성:
  Summary          ─ 4개 임계값 × 2전략 성과 비교표 + 사이클 수익률바
  TQQQ_RSI_8       ─ buy_below=8  일별 백테스트
  TQQQ_RSI_10      ─ buy_below=10 일별 백테스트
  TQQQ_RSI_12      ─ buy_below=12 일별 백테스트
  TQQQ_RSI_15      ─ buy_below=15 일별 백테스트
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

import create_nonsplit_best_algo_sheet as base
import create_rsi_price_target_sheet   as rsi2
import create_rsi_fng_sheet            as fng_mod
import search_optimal_strategies       as search_mod
from fear_greed_history  import load_fng_history
from sheets_manager      import SheetsManager
from _env_loader         import get_spreadsheet_id

TICKER        = "TQQQ"
SELL_ABOVE    = 75          # TQQQ 고정 매도 임계값
PERIOD        = 2
BUY_THRESHOLDS = [8, 10, 12, 15]
CAPITAL       = search_mod.CAPITAL

# FnG 최적 파라미터 (FnG 알고리즘이 이미 결정한 값과 동일하게 사용)
FEAR_MAX  = 20
GREED_MIN = 85

# 색상 상수 재사용
COLOR_BUY       = rsi2.COLOR_BUY
COLOR_SELL      = rsi2.COLOR_SELL
COLOR_TITLE_BG  = rsi2.COLOR_TITLE_BG
COLOR_HDR_BG    = rsi2.COLOR_HDR_BG
COLOR_HDR_FG    = rsi2.COLOR_HDR_FG
COLOR_SECTION_BG = rsi2.COLOR_SECTION_BG


# ──────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────

def _pct_bg(pct: float) -> dict:
    """수익률에 따라 빨강(양) / 파랑(음) 셀 배경색"""
    if pct >= 0:
        intensity = min(pct / 1000.0, 1.0)
        return {"red": 1.0, "green": 1.0 - intensity * 0.5, "blue": 1.0 - intensity * 0.5}
    else:
        intensity = min(abs(pct) / 50.0, 1.0)
        return {"red": 1.0 - intensity * 0.5, "green": 1.0 - intensity * 0.5, "blue": 1.0}


# ──────────────────────────────────────────────────────────────
# Summary 탭
# ──────────────────────────────────────────────────────────────

def write_summary(ss, all_results: dict):
    """
    all_results[buy_below] = {
        "rsi2":  {total_return_pct, cagr_pct, mdd_pct, final_assets, total_trades, df},
        "fng":   {total_return_pct, cagr_pct, mdd_pct, final_assets, total_trades, df},
    }
    """
    title = "Summary"
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=600, cols=24)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[list] = []
    style_map: dict = {}

    def add_row(v: list) -> int:
        rows.append(v)
        return len(rows)

    # ── 타이틀 ──────────────────────────────────────────────
    add_row([f"TQQQ  RSI(2)  매수 임계값 비교  (buy_below = {BUY_THRESHOLDS})"])
    add_row([f"생성: {now}   |   기간: {search_mod.START_DATE} ~ {search_mod.END_DATE}   |   초기자본: $100,000   |   sell_above={SELL_ABOVE}   |   체결: LOC"])
    add_row([f"FnG 파라미터:  Extreme Fear ≤ {FEAR_MAX} (매도 보류)  |  Extreme Greed ≥ {GREED_MIN} (매수 보류)"])
    add_row([])

    # ── 성과 비교표 ──────────────────────────────────────────
    add_row(["[ 전략 성과 비교 ]"])
    style_map["perf_section"] = len(rows)
    add_row(["buy_below", "전략", "총수익률(%)", "CAGR(%)", "MDD(%)", "최종자산($)", "거래횟수", "사이클수"])
    style_map["perf_header"] = len(rows)
    style_map["perf_data_start"] = len(rows) + 1

    for bb in BUY_THRESHOLDS:
        r2 = all_results[bb]["rsi2"]
        rf = all_results[bb]["fng"]
        n_cycles_r2 = len(rsi2._extract_cycle_state(r2["df"])[0])
        n_cycles_rf = len(rsi2._extract_cycle_state(rf["df"])[0])
        add_row([f"RSI<{bb}", "RSI2 단독",
                 r2["total_return_pct"], r2["cagr_pct"], r2["mdd_pct"],
                 r2["final_assets"], r2["total_trades"], n_cycles_r2])
        add_row([f"RSI<{bb}", f"RSI2+FnG(≤{FEAR_MAX}/≥{GREED_MIN})",
                 rf["total_return_pct"], rf["cagr_pct"], rf["mdd_pct"],
                 rf["final_assets"], rf["total_trades"], n_cycles_rf])

    add_row([])

    # ── 최적값 요약 ──────────────────────────────────────────
    best_bb_r2  = max(BUY_THRESHOLDS, key=lambda b: all_results[b]["rsi2"]["total_return_pct"])
    best_bb_fng = max(BUY_THRESHOLDS, key=lambda b: all_results[b]["fng"]["total_return_pct"])
    add_row(["[ 최고 수익률 ]"])
    style_map["best_section"] = len(rows)
    add_row(["전략", "최적 buy_below", "총수익률(%)", "CAGR(%)", "MDD(%)"])
    style_map["best_header"] = len(rows)
    r2b = all_results[best_bb_r2]["rsi2"]
    rfb = all_results[best_bb_fng]["fng"]
    add_row(["RSI2 단독", f"RSI<{best_bb_r2}",
             r2b["total_return_pct"], r2b["cagr_pct"], r2b["mdd_pct"]])
    add_row([f"RSI2+FnG(≤{FEAR_MAX}/≥{GREED_MIN})", f"RSI<{best_bb_fng}",
             rfb["total_return_pct"], rfb["cagr_pct"], rfb["mdd_pct"]])
    add_row([])

    # ── 임계값별 사이클 비교표 ────────────────────────────────
    for bb in BUY_THRESHOLDS:
        df_fng = all_results[bb]["fng"]["df"]
        completed, open_cycle = rsi2._extract_cycle_state(df_fng)
        add_row([f"[ 사이클 결과  /  RSI2+FnG  buy_below={bb} ]"])
        style_map[f"cycle_section_{bb}"] = len(rows)
        add_row(["Cycle #", "매수일", "매수가($)", "매도일", "매도가($)",
                 "시작현금($)", "종료현금($)", "사이클 수익률 / 바"])
        style_map[f"cycle_header_{bb}"] = len(rows)
        style_map[f"cycle_data_start_{bb}"] = len(rows) + 1

        max_ret = max((abs(float(c["cycle_return_pct"])) for c in completed), default=1.0)
        for cyc in completed:
            pct = float(cyc["cycle_return_pct"])
            bar = rsi2._bar_text_centered(pct, max_ret, max_ret, f"{pct:.2f}%")
            add_row([cyc["cycle_no"], cyc["buy_date"], cyc["buy_price"],
                     cyc["sell_date"], cyc["sell_price"],
                     cyc["start_cash"], cyc["end_cash"], bar])

        if open_cycle:
            add_row([open_cycle["cycle_no"], open_cycle["buy_date"], open_cycle["buy_price"],
                     "(보유중)", "", open_cycle["start_cash"], "(미정)", "진행중"])
        style_map[f"cycle_data_end_{bb}"] = len(rows)
        add_row([])

    ws.update(range_name=f"A1:J{len(rows)}", values=rows)

    # ── 스타일 ─────────────────────────────────────────────
    requests = [
        # 타이틀
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 20},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_TITLE_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True, "fontSize": 15}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # FnG 파라미터 행
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": 20},
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.95, "green": 0.85, "blue": 0.6}, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 성과 섹션 타이틀
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_map["perf_section"] - 1, "endRowIndex": style_map["perf_section"], "startColumnIndex": 0, "endColumnIndex": 20},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 성과 헤더
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_map["perf_header"] - 1, "endRowIndex": style_map["perf_header"], "startColumnIndex": 0, "endColumnIndex": 20},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        # 최고 섹션
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_map["best_section"] - 1, "endRowIndex": style_map["best_section"], "startColumnIndex": 0, "endColumnIndex": 20},
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.8, "green": 0.95, "blue": 0.8}, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_map["best_header"] - 1, "endRowIndex": style_map["best_header"], "startColumnIndex": 0, "endColumnIndex": 20},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
    ]

    # 성과표 데이터 행 색칠: RSI2 단독(흰) / FnG(연파랑) 교대
    ds = style_map["perf_data_start"]
    for i, bb in enumerate(BUY_THRESHOLDS):
        r2_row = ds + i * 2 - 1
        rf_row = ds + i * 2
        for row_no, bg in [(r2_row, None), (rf_row, {"red": 0.93, "green": 0.96, "blue": 1.0})]:
            if bg:
                requests.append({"repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 0, "endColumnIndex": 8},
                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                    "fields": "userEnteredFormat.backgroundColor",
                }})
        # 총수익률 셀(C열=col 2) 색상
        for row_no, result_key in [(r2_row, "rsi2"), (rf_row, "fng")]:
            pct = float(all_results[bb][result_key]["total_return_pct"])
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 2, "endColumnIndex": 3},
                "cell": {"userEnteredFormat": {"backgroundColor": _pct_bg(pct), "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})

    # 사이클 섹션 헤더 + 수익률바 셀 색칠
    for bb in BUY_THRESHOLDS:
        requests.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_map[f"cycle_section_{bb}"] - 1, "endRowIndex": style_map[f"cycle_section_{bb}"], "startColumnIndex": 0, "endColumnIndex": 10},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_SECTION_BG, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})
        requests.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": style_map[f"cycle_header_{bb}"] - 1, "endRowIndex": style_map[f"cycle_header_{bb}"], "startColumnIndex": 0, "endColumnIndex": 10},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})
        df_fng = all_results[bb]["fng"]["df"]
        completed, _ = rsi2._extract_cycle_state(df_fng)
        data_start = style_map[f"cycle_data_start_{bb}"]
        for idx, cyc in enumerate(completed):
            row_no = data_start + idx
            pct = float(cyc["cycle_return_pct"])
            shade = rsi2._shade_for_centered(pct)
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_no - 1, "endRowIndex": row_no, "startColumnIndex": 7, "endColumnIndex": 8},
                "cell": {"userEnteredFormat": {"backgroundColor": shade, "textFormat": {"bold": True, "fontFamily": "'Courier New'", "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})

    ws.spreadsheet.batch_update({"requests": requests})
    print(f"[GoogleSheets] {title} 저장 완료")


# ──────────────────────────────────────────────────────────────
# 일별 백테스트 탭 (FnG 기준)
# ──────────────────────────────────────────────────────────────

def write_daily_tab(ss, buy_below: int, df: pd.DataFrame, perf: dict):
    title = f"TQQQ_RSI_{buy_below}"
    headers = list(df.columns)
    try:
        ws = ss.worksheet(title)
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title=title, rows=max(1800, len(df) + 10), cols=len(headers))

    meta = [
        [f"TQQQ  —  RSI(2)+FnG  매수: RSI<{buy_below} & F&G<{GREED_MIN}  /  매도: RSI>{SELL_ABOVE} & F&G>{FEAR_MAX}"],
        [f"총수익률: {perf['total_return_pct']}%   CAGR: {perf['cagr_pct']}%   MDD: {perf['mdd_pct']}%   최종자산: ${perf['final_assets']:,}"],
        [f"기간: {search_mod.START_DATE} ~ {search_mod.END_DATE}   거래: {perf['total_trades']}회   체결: LOC"],
        [f"F&G: Extreme Fear ≤ {FEAR_MAX} → SELL 보류  |  Extreme Greed ≥ {GREED_MIN} → BUY 보류"],
        headers,
    ]
    data_row0 = len(meta)
    col_letter = chr(64 + min(len(headers), 26))

    ws.update(range_name=f"A1:{col_letter}{len(meta)}", values=meta)

    values = [
        ["" if (v == "" or (isinstance(v, float) and np.isnan(v))) else str(v) for v in row]
        for row in df.values.tolist()
    ]
    if values:
        ws.update(range_name=f"A{data_row0 + 1}:{col_letter}{data_row0 + len(values)}", values=values)

    col_idx = {c: i for i, c in enumerate(headers)}
    center_cols = [f"rsi{PERIOD}", "chg_pct", "fng", "buy_limit_expected_px",
                   "sell_limit_expected_px", "trade_qty", "holdings", "return_pct"]
    left_cols   = ["date", "close", "fng_blocked", "buy_limit_px", "sell_limit_px",
                   "action", "cash", "total_assets"]
    total_rows  = data_row0 + len(values) + 1

    align_requests = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": data_row0 - 1, "endRowIndex": data_row0, "startColumnIndex": 0, "endColumnIndex": len(headers)},
        "cell": {"userEnteredFormat": {"backgroundColor": COLOR_HDR_BG, "textFormat": {"foregroundColor": COLOR_HDR_FG, "bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }}]
    for c in center_cols:
        if c in col_idx:
            ci = col_idx[c]
            align_requests.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": data_row0, "endRowIndex": total_rows, "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }})
    for c in left_cols:
        if c in col_idx:
            ci = col_idx[c]
            align_requests.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": data_row0, "endRowIndex": total_rows, "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }})
    ws.spreadsheet.batch_update({"requests": align_requests})

    color_requests = []
    for i, row in df.iterrows():
        row_idx = data_row0 + df.index.get_loc(i)
        if row["action"] == "BUY":
            bg = COLOR_BUY
        elif row["action"] == "SELL":
            bg = COLOR_SELL
        elif row.get("fng_blocked", "") != "":
            bg = {"red": 1.0, "green": 0.98, "blue": 0.75}
        else:
            continue
        color_requests.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 0, "endColumnIndex": len(headers)},
            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
            "fields": "userEnteredFormat.backgroundColor",
        }})
    if color_requests:
        ws.spreadsheet.batch_update({"requests": color_requests})

    trades  = int((df["action"] != "HOLD").sum())
    blocked = int((df.get("fng_blocked", pd.Series([""] * len(df))) != "").sum())
    print(f"[GoogleSheets] {title} 저장 완료 ({len(df)}행, BUY/SELL {trades}회, F&G차단 {blocked}회)")


# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print(f"[TQQQ RSI 매수 임계값 비교] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  buy_below 탐색: {BUY_THRESHOLDS}")
    print("=" * 80)

    close = base.download_close(TICKER)
    print(f"[{TICKER}] 가격 데이터 {len(close)}일")

    # F&G 데이터
    try:
        fng_series = load_fng_history()
        fng = fng_series.reindex(close.index, method="ffill").fillna(50).astype(int)
        print(f"[FnG] 데이터 준비 완료 ({fng.index.min().date()} ~ {fng.index.max().date()})")
    except Exception as e:
        print(f"[FnG] ⚠️ 로드 실패: {e} → 중립값(50)")
        fng = pd.Series(50, index=close.index, name="fng")

    # 4가지 임계값 × 2전략 백테스트
    all_results: dict[int, dict] = {}
    print()
    for bb in BUY_THRESHOLDS:
        # RSI2 단독
        df_r2 = rsi2.simulate_with_targets(close, PERIOD, float(bb), float(SELL_ABOVE))
        tr, cagr, mdd, fa = base.calc_perf(df_r2["total_assets"])
        trades = int((df_r2["action"] != "HOLD").sum())
        r2_perf = {"total_return_pct": round(tr, 2), "cagr_pct": round(cagr, 2),
                   "mdd_pct": round(mdd, 2), "final_assets": round(fa, 2),
                   "total_trades": trades, "df": df_r2}

        # RSI2 + FnG
        df_fng = fng_mod.simulate_with_fng(
            close, fng, PERIOD, float(bb), float(SELL_ABOVE),
            fear_max=FEAR_MAX, greed_min=GREED_MIN
        )
        tr, cagr, mdd, fa = base.calc_perf(df_fng["total_assets"])
        trades  = int((df_fng["action"] != "HOLD").sum())
        blocked = int((df_fng["fng_blocked"] != "").sum())
        fng_perf = {"total_return_pct": round(tr, 2), "cagr_pct": round(cagr, 2),
                    "mdd_pct": round(mdd, 2), "final_assets": round(fa, 2),
                    "total_trades": trades, "df": df_fng}

        all_results[bb] = {"rsi2": r2_perf, "fng": fng_perf}
        print(
            f"  RSI<{bb:2d}  |  RSI2 단독: {r2_perf['total_return_pct']:>8.2f}%  {r2_perf['total_trades']}회"
            f"  |  RSI2+FnG: {fng_perf['total_return_pct']:>8.2f}%  {fng_perf['total_trades']}회  차단 {blocked}회"
        )

    # 새 구글 시트 생성
    title_date = datetime.now().strftime("%Y%m%d_%H%M")
    sheet_title = f"TQQQ_RSI_매수임계값비교_{title_date}"
    sm = SheetsManager(spreadsheet_id=get_spreadsheet_id())
    gc = sm._get_client()
    ss = gc.create(sheet_title)

    # 탭 작성
    write_summary(ss, all_results)
    for bb in BUY_THRESHOLDS:
        df_fng = all_results[bb]["fng"]["df"]
        perf   = {k: v for k, v in all_results[bb]["fng"].items() if k != "df"}
        write_daily_tab(ss, bb, df_fng, perf)

    # 기본 시트 제거
    try:
        default_ws = ss.worksheet("Sheet1")
        ss.del_worksheet(default_ws)
    except Exception:
        pass
    try:
        default_ws = ss.worksheet("시트1")
        ss.del_worksheet(default_ws)
    except Exception:
        pass

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print("\n" + "=" * 80)
    print(f"[완료] 파일명: {ss.title}")
    print(f"[완료] 구글 시트 링크: {url}")
    print(f"탭: {' | '.join(ws.title for ws in ss.worksheets())}")
    print("=" * 80)


if __name__ == "__main__":
    main()
