"""
TQQQ 최적 알고리즘 도출 - 파라미터 최적화 (Grid Search)

2022-01-01 ~ 2026-05-16 기간 TQQQ 데이터로
최대 수익률을 만드는 파라미터 조합을 찾음
"""

import sys
from pathlib import Path
from datetime import datetime
import itertools
import time

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))

from backtest_engine import BacktestEngine, AlgoParams
from sheets_manager import SheetsManager
from config import DEFAULT_PARAMS
from _env_loader import get_spreadsheet_id


def optimize_parameters():
    """
    Grid Search: 여러 파라미터 조합을 테스트하여 최고 수익률 찾기
    """
    print("=" * 80)
    print("TQQQ 최적 알고리즘 탐색 (2022-01-01 ~ 2026-05-16)")
    print("=" * 80)

    # 테스트할 파라미터 범위
    n_splits_options = [20, 30, 40, 50]           # 등분수
    base_profit_options = [1.0, 2.0, 3.0, 5.0]    # 기본 수익 기준 (%)
    
    # 매수 임계값 (3배수이므로 실제로는 ×3)
    buy_threshold_options = [
        (8, 12, 16),
        (10, 15, 20),
        (5, 10, 15),
        (12, 18, 24),
    ]
    
    # 매도 임계값
    sell_threshold_options = [
        (8, 16, 24),
        (10, 20, 30),
        (5, 15, 25),
        (12, 24, 36),
        (15, 30, 45),
    ]

    results = []
    total_combinations = (
        len(n_splits_options) * 
        len(base_profit_options) * 
        len(buy_threshold_options) * 
        len(sell_threshold_options)
    )
    
    print(f"\n테스트 조합 수: {total_combinations}")
    print(f"예상 소요시간: ~{int(total_combinations * 1.5)}초 (약 {int(total_combinations * 1.5 / 60)}분)\n")

    iteration = 0
    for n_splits, base_profit, buy_thresh, sell_thresh in itertools.product(
        n_splits_options,
        base_profit_options,
        buy_threshold_options,
        sell_threshold_options,
    ):
        iteration += 1
        
        params = AlgoParams(
            ticker="TQQQ",
            initial_capital=100_000.0,
            n_splits=n_splits,
            start_date="2022-01-01",
            end_date="2026-05-16",
            base_profit_pct=base_profit,
            buy_threshold_1=buy_thresh[0],
            buy_threshold_2=buy_thresh[1],
            buy_threshold_3=buy_thresh[2],
            sell_threshold_1=sell_thresh[0],
            sell_threshold_2=sell_thresh[1],
            sell_threshold_3=sell_thresh[2],
            gap_up_pct=2.0,
            is_3x=True,
        )

        try:
            engine = BacktestEngine(params=params, fg_series={})
            records, summary = engine.run()
            
            results.append({
                "n_splits": n_splits,
                "base_profit_pct": base_profit,
                "buy_thresh_1": buy_thresh[0],
                "buy_thresh_2": buy_thresh[1],
                "buy_thresh_3": buy_thresh[2],
                "sell_thresh_1": sell_thresh[0],
                "sell_thresh_2": sell_thresh[1],
                "sell_thresh_3": sell_thresh[2],
                "total_return_pct": summary["total_return_pct"],
                "cagr_pct": summary["cagr_pct"],
                "mdd_pct": summary["mdd_pct"],
                "total_trades": summary["total_trades"],
                "buy_count": summary["buy_count"],
                "sell_count": summary["sell_count"],
                "total_cycles": summary["total_cycles"],
                "final_assets": summary["final_total_assets"],
                "records": records,
            })

            if iteration % 20 == 0:
                top_return = max(r["total_return_pct"] for r in results)
                print(f"[{iteration}/{total_combinations}] 진행 중... "
                      f"현재 최고: {top_return:.2f}%")

        except Exception as e:
            print(f"[{iteration}/{total_combinations}] 오류: {str(e)[:50]}")
            continue

    # 결과 정렬
    results_df = pd.DataFrame([{k: v for k, v in r.items() if k != "records"} for r in results])
    results_df = results_df.sort_values("total_return_pct", ascending=False)

    print("\n" + "=" * 100)
    print("🏆 최적화 완료 - 상위 10개 전략")
    print("=" * 100)
    
    for idx, row in results_df.head(10).iterrows():
        print(
            f"{idx+1:<3}: 수익 {row['total_return_pct']:>8.2f}% | "
            f"CAGR {row['cagr_pct']:>7.2f}% | "
            f"MDD {row['mdd_pct']:>7.2f}% | "
            f"거래 {row['total_trades']:>5.0f} | "
            f"N={row['n_splits']:.0f} | "
            f"buy=({row['buy_thresh_1']:.0f},{row['buy_thresh_2']:.0f},{row['buy_thresh_3']:.0f}) | "
            f"sell=({row['sell_thresh_1']:.0f},{row['sell_thresh_2']:.0f},{row['sell_thresh_3']:.0f})"
        )

    # 상세 결과 저장
    results_data = {
        "results_df": results_df,
        "all_results": results,
    }

    return results_data


def save_to_google_sheets(results_data):
    """
    최적화 결과를 Google Sheets에 저장
    """
    print("\n" + "=" * 80)
    print("Google Sheets에 저장 중...")
    print("=" * 80)
    
    try:
        sheet_id = get_spreadsheet_id()
    except ValueError:
        print("[오류] Google Sheets ID를 찾을 수 없습니다.")
        print("     .env 파일에 SPREADSHEET_ID를 설정하세요.")
        return

    sm = SheetsManager(spreadsheet_id=sheet_id)
    results_df = results_data["results_df"]
    all_results = results_data["all_results"]

    # 최고 수익률 조합 선택
    best_result = all_results[0]  # 이미 정렬됨
    best_records = best_result["records"]
    best_summary = {
        "n_splits": best_result["n_splits"],
        "base_profit_pct": best_result["base_profit_pct"],
        "buy_threshold_1": best_result["buy_thresh_1"],
        "buy_threshold_2": best_result["buy_thresh_2"],
        "buy_threshold_3": best_result["buy_thresh_3"],
        "sell_threshold_1": best_result["sell_thresh_1"],
        "sell_threshold_2": best_result["sell_thresh_2"],
        "sell_threshold_3": best_result["sell_thresh_3"],
        "gap_up_pct": 2.0,
        "total_return_pct": best_result["total_return_pct"],
        "cagr_pct": best_result["cagr_pct"],
        "mdd_pct": best_result["mdd_pct"],
        "total_trades": best_result["total_trades"],
        "buy_count": best_result["buy_count"],
        "sell_count": best_result["sell_count"],
        "total_cycles": best_result["total_cycles"],
        "final_total_assets": best_result["final_assets"],
        "start_date": "2022-01-01",
        "end_date": "2026-05-16",
        "ticker": "TQQQ",
        "is_3x": True,
        "initial_capital": 100_000.0,
    }

    # 1) BackTest 시트에 최고 수익률 알고리즘 저장
    print("[1/3] BackTest 시트에 최고 수익률 백테스트 데이터 저장...")
    sm.write_backtest(best_records, best_summary)

    # 2) Summary 시트 업데이트
    print("[2/3] Summary 시트에 알고리즘 설명 저장...")
    sm.write_summary_dashboard(best_summary)

    # 3) 최적화 결과 시트 생성
    print("[3/3] 최적화 결과 시트 생성...")
    create_optimization_sheet(sm, results_df)

    print("\n✅ Google Sheets 저장 완료!")
    print(f"   URL: https://docs.google.com/spreadsheets/d/{sm.spreadsheet_id}")


def create_optimization_sheet(sm: SheetsManager, results_df: pd.DataFrame):
    """
    최적화 결과를 새로운 시트에 저장
    """
    ss = sm._open_spreadsheet()
    
    # 최적화 결과 시트 생성
    try:
        ws_opt = ss.worksheet("최적화결과")
    except:
        ws_opt = ss.add_worksheet(title="최적화결과", rows=len(results_df) + 50, cols=15)

    ws_opt.clear()

    # 제목
    title_row = [
        ["TQQQ 파라미터 최적화 결과 분석"],
        [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [f"기간: 2022-01-01 ~ 2026-05-16"],
        [f"총 테스트 조합: {len(results_df)}개"],
        [""],
    ]
    ws_opt.update("A1:E5", title_row)
    ws_opt.format("A1", {
        "textFormat": {"bold": True, "fontSize": 14, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.10, "green": 0.20, "blue": 0.35},
    })

    # 헤더
    headers = [
        "순위",
        "누적수익률(%)",
        "CAGR(%)",
        "MDD(%)",
        "총거래",
        "사이클",
        "등분수(N)",
        "기본수익(%)",
        "매수1낙폭(%)",
        "매수2낙폭(%)",
        "매수3낙폭(%)",
        "매도1수익(%)",
        "매도2수익(%)",
        "매도3수익(%)",
        "최종자산($)",
    ]

    ws_opt.update("A7:O7", [headers])
    ws_opt.format("A7:O7", {
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.10, "green": 0.20, "blue": 0.35},
    })

    # 데이터
    data_rows = []
    for rank, (idx, row) in enumerate(results_df.head(50).iterrows(), start=1):
        data_rows.append([
            rank,
            row["total_return_pct"],
            row["cagr_pct"],
            row["mdd_pct"],
            row["total_trades"],
            row["total_cycles"],
            row["n_splits"],
            row["base_profit_pct"],
            row["buy_thresh_1"],
            row["buy_thresh_2"],
            row["buy_thresh_3"],
            row["sell_thresh_1"],
            row["sell_thresh_2"],
            row["sell_thresh_3"],
            row["final_assets"],
        ])

    ws_opt.update(f"A8:O{8 + len(data_rows) - 1}", data_rows)

    # 포맷팅
    for col in ["B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"]:
        ws_opt.format(f"{col}8:{col}{8 + len(data_rows) - 1}", {
            "numberFormat": {"type": "NUMBER", "pattern": "0.00"},
        })

    # 최고 수익률 행 하이라이트
    ws_opt.format("A8:O8", {
        "backgroundColor": {"red": 0.84, "green": 0.95, "blue": 0.89},
        "textFormat": {"bold": True},
    })

    print(f"   최적화 결과 시트에 상위 {min(50, len(results_df))}개 결과 저장")


if __name__ == "__main__":
    print("\n")
    results_data = optimize_parameters()
    save_to_google_sheets(results_data)
    print("\n")
