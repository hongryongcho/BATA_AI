"""
BATA 백테스트 메인 실행 스크립트

사용법:
  python3 run_backtest.py --sheet-id <SPREADSHEET_ID> [--init-sheet] [--no-fg]
  python3 run_backtest.py --sheet-id <SPREADSHEET_ID> --ticker SPY --start 2022-01-01

옵션:
  --sheet-id   : Google Spreadsheet ID (URL에서 /d/XXXX/ 부분)
  --init-sheet : Summary 시트 템플릿 초기 생성 후 종료
  --no-fg      : Fear & Greed 비활성화 (모두 50=Neutral 처리)
  --ticker     : 티커 오버라이드 (Sheet 파라미터보다 우선)
  --start      : 시작일 오버라이드 (YYYY-MM-DD)
  --capital    : 초기자본 오버라이드 (USD)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 현재 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from backtest_engine import BacktestEngine, AlgoParams
from sheets_manager import SheetsManager
from fear_greed import fetch_fear_greed
from config import DEFAULT_PARAMS


def parse_args():
    parser = argparse.ArgumentParser(description="BATA 투자 알고리즘 백테스트")
    parser.add_argument("--sheet-id", required=True,
                        help="Google Spreadsheet ID")
    parser.add_argument("--init-sheet", action="store_true",
                        help="Summary 시트 템플릿 초기 생성 후 종료")
    parser.add_argument("--no-fg", action="store_true",
                        help="Fear & Greed 비활성화")
    parser.add_argument("--ticker", default=None,
                        help="티커 오버라이드 (예: TQQQ)")
    parser.add_argument("--start", default=None,
                        help="시작일 오버라이드 (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=None,
                        help="초기자본 오버라이드 (USD)")
    return parser.parse_args()


def load_fear_greed_series() -> dict:
    """
    현재는 단일 값만 가져옴 (오늘 날짜).
    향후 Historical API가 제공되면 전체 시리즈로 확장 가능.
    오늘 값을 모든 날짜에 동일하게 적용하지 않고,
    백테스트 시에는 역사적 데이터가 없으므로 50(Neutral)로 처리.
    실제 운용 시에만 당일 Fear & Greed 를 사용.
    """
    print("[main] Fear & Greed 조회...")
    fg = fetch_fear_greed()
    print(f"[main] Fear & Greed: {fg['value']} ({fg['label']}) [{fg['source']}]")
    # 백테스트용: 빈 딕셔너리 반환 → 엔진에서 50(Neutral) 기본값 사용
    # 오늘 날짜만 실제 값 사용
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    return {today: fg["value"]}


def main():
    args = parse_args()
    print("=" * 60)
    print("BATA 투자 알고리즘 백테스트")
    print("=" * 60)

    sm = SheetsManager(spreadsheet_id=args.sheet_id)

    # 템플릿 초기 생성 모드
    if args.init_sheet:
        sm.create_summary_template()
        print("\n[main] Summary 시트 템플릿 생성 완료.")
        print("Google Sheets에서 파라미터를 수정한 후 백테스트를 실행하세요.")
        return

    # 파라미터 읽기 (Sheets → 오버라이드 적용)
    params = sm.read_params()

    if args.ticker:
        params.ticker = args.ticker.upper()
    if args.start:
        params.start_date = args.start
    if args.capital:
        params.initial_capital = args.capital

    print(f"\n[main] 파라미터:")
    print(f"  티커:       {params.ticker}")
    print(f"  3배수ETF:   {params.is_3x}")
    print(f"  초기자본:   ${params.initial_capital:,.0f}")
    print(f"  등분수:     {params.n_splits}")
    print(f"  시작일:     {params.start_date}")
    print(f"  종료일:     {params.end_date or '오늘'}")
    print(f"  기본수익기준: {params.base_profit_pct}%")
    print(f"  매수임계: -{params.buy_threshold_1}%/-{params.buy_threshold_2}%/-{params.buy_threshold_3}%")
    print(f"  매도임계: +{params.sell_threshold_1}%/+{params.sell_threshold_2}%/+{params.sell_threshold_3}%")
    print()

    # Fear & Greed
    if args.no_fg:
        fg_series = {}
        print("[main] Fear & Greed 비활성화 (모두 Neutral=50 처리)")
    else:
        fg_series = load_fear_greed_series()

    # 백테스트 실행
    print("[main] 백테스트 실행 중...")
    engine = BacktestEngine(params=params, fg_series=fg_series)
    records, summary = engine.run()
    summary["ticker"] = params.ticker  # 요약에 티커 추가

    # 결과 출력
    print(f"\n[main] 백테스트 완료 ({len(records)}일)")
    print(f"  총수익률:  {summary['total_return_pct']:+.2f}%")
    print(f"  CAGR:      {summary['cagr_pct']:+.2f}%")
    print(f"  MDD:       {summary['mdd_pct']:.2f}%")
    print(f"  총거래수:  {summary['total_trades']} (매수:{summary['buy_count']} 매도:{summary['sell_count']})")
    print(f"  사이클수:  {summary['total_cycles']}")
    print(f"  최종총자산: ${summary['final_total_assets']:,.2f}")

    # Google Sheets에 결과 쓰기
    print("\n[main] Google Sheets 업로드 중...")
    sm.write_backtest(records)
    sm.write_performance(summary, params)

    print("\n[main] 완료!")
    print(f"Google Sheets에서 결과를 확인하세요:")
    print(f"  https://docs.google.com/spreadsheets/d/{args.sheet_id}")


if __name__ == "__main__":
    main()
