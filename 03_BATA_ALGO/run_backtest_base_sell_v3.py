"""
기본매도 보강 버전 실행 진입점 (v3)

- 기본수익 구간(base_profit_pct) 돌파 시 최소 1회 매도 보장
- 나머지 동작은 run_backtest.py와 동일

사용법:
  python3 run_backtest_base_sell_v3.py
  python3 run_backtest_base_sell_v3.py --init-sheet
"""

from run_backtest import main


if __name__ == "__main__":
    main()
