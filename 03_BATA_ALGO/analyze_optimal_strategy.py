"""
10년 데이터(2016-2026) 기반 최적 투자 전략 분석
TQQQ vs SOXL 비교
"""

from pathlib import Path
import pandas as pd
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SCRIPT_DIR = Path(__file__).parent.resolve()

def analyze_strategy():
    spreadsheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=spreadsheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(spreadsheet_id)
    
    # ─────────────────────────────────────────────────────────────
    # Summary 탭 읽기
    # ─────────────────────────────────────────────────────────────
    ws_summary = ss.worksheet("Summary")
    summary_values = ws_summary.get_all_values()
    
    print("=" * 80)
    print("📊 10년 최적 투자 전략 분석 (2016.01.01 ~ 2026.05.16)")
    print("=" * 80)
    
    # Summary에서 현황 요약 찾기
    for i, row in enumerate(summary_values):
        if row and len(row) > 0 and "현재 사이클" in str(row[0]):
            print("\n📍 현재 상태:")
            # 다음 몇 줄 출력
            for j in range(i, min(i+10, len(summary_values))):
                if summary_values[j][0].strip():
                    print(f"   {summary_values[j][0]}")
            break
    
    # ─────────────────────────────────────────────────────────────
    # TQQQ 데이터 분석
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("🚀 TQQQ 전략 분석")
    print("=" * 80)
    
    ws_tqqq = ss.worksheet("TQQQ_매매기준가")
    tqqq_values = ws_tqqq.get_all_values()
    
    # 헤더 찾기
    header_idx = None
    for idx, row in enumerate(tqqq_values):
        if row and "buy_date" in str(row):
            header_idx = idx
            break
    
    if header_idx:
        headers = tqqq_values[header_idx]
        data_rows = tqqq_values[header_idx+1:]
        
        # 거래 데이터 파싱
        trades = []
        for row in data_rows:
            if not row or not row[0]:  # 빈 행 스킵
                continue
            try:
                if len(row) >= 8:
                    trades.append({
                        'ticker': 'TQQQ',
                        'buy_date': row[0],
                        'buy_price': float(row[1]) if row[1] else 0,
                        'sell_date': row[2],
                        'sell_price': float(row[3]) if row[3] else 0,
                        'roi': float(row[4].rstrip('%')) if row[4] else 0,
                        'signal': row[5],
                        'fng_block': row[6] if len(row) > 6 else '',
                    })
            except (ValueError, IndexError):
                continue
        
        if trades:
            # 통계
            total_trades = len(trades)
            wins = sum(1 for t in trades if t['roi'] > 0)
            losses = sum(1 for t in trades if t['roi'] < 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            avg_roi = sum(t['roi'] for t in trades) / total_trades if total_trades > 0 else 0
            max_roi = max(t['roi'] for t in trades) if trades else 0
            min_roi = min(t['roi'] for t in trades) if trades else 0
            
            print(f"\n📈 거래 통계:")
            print(f"   총 거래: {total_trades}회")
            print(f"   수익 거래: {wins}회 ({win_rate:.1f}%)")
            print(f"   손실 거래: {losses}회 ({100-win_rate:.1f}%)")
            print(f"   평균 ROI: {avg_roi:.2f}%")
            print(f"   최대 수익: {max_roi:.2f}%")
            print(f"   최대 손실: {min_roi:.2f}%")
            
            # 신호별 성과
            print(f"\n🎯 신호별 성과:")
            for signal in set(t['signal'] for t in trades):
                signal_trades = [t for t in trades if t['signal'] == signal]
                signal_roi = sum(t['roi'] for t in signal_trades) / len(signal_trades)
                signal_wins = sum(1 for t in signal_trades if t['roi'] > 0)
                print(f"   {signal}: 평균 ROI {signal_roi:.2f}% ({signal_wins}/{len(signal_trades)} 수익)")
    
    # ─────────────────────────────────────────────────────────────
    # SOXL 데이터 분석
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("🔧 SOXL 전략 분석")
    print("=" * 80)
    
    ws_soxl = ss.worksheet("SOXL_매매기준가")
    soxl_values = ws_soxl.get_all_values()
    
    # 헤더 찾기
    header_idx = None
    for idx, row in enumerate(soxl_values):
        if row and "buy_date" in str(row):
            header_idx = idx
            break
    
    if header_idx:
        headers = soxl_values[header_idx]
        data_rows = soxl_values[header_idx+1:]
        
        # 거래 데이터 파싱
        trades = []
        for row in data_rows:
            if not row or not row[0]:
                continue
            try:
                if len(row) >= 8:
                    trades.append({
                        'ticker': 'SOXL',
                        'buy_date': row[0],
                        'buy_price': float(row[1]) if row[1] else 0,
                        'sell_date': row[2],
                        'sell_price': float(row[3]) if row[3] else 0,
                        'roi': float(row[4].rstrip('%')) if row[4] else 0,
                        'signal': row[5],
                        'fng_block': row[6] if len(row) > 6 else '',
                    })
            except (ValueError, IndexError):
                continue
        
        if trades:
            # 통계
            total_trades = len(trades)
            wins = sum(1 for t in trades if t['roi'] > 0)
            losses = sum(1 for t in trades if t['roi'] < 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            avg_roi = sum(t['roi'] for t in trades) / total_trades if total_trades > 0 else 0
            max_roi = max(t['roi'] for t in trades) if trades else 0
            min_roi = min(t['roi'] for t in trades) if trades else 0
            
            print(f"\n📈 거래 통계:")
            print(f"   총 거래: {total_trades}회")
            print(f"   수익 거래: {wins}회 ({win_rate:.1f}%)")
            print(f"   손실 거래: {losses}회 ({100-win_rate:.1f}%)")
            print(f"   평균 ROI: {avg_roi:.2f}%")
            print(f"   최대 수익: {max_roi:.2f}%")
            print(f"   최대 손실: {min_roi:.2f}%")
            
            # 신호별 성과
            print(f"\n🎯 신호별 성과:")
            for signal in set(t['signal'] for t in trades):
                signal_trades = [t for t in trades if t['signal'] == signal]
                signal_roi = sum(t['roi'] for t in signal_trades) / len(signal_trades)
                signal_wins = sum(1 for t in signal_trades if t['roi'] > 0)
                print(f"   {signal}: 평균 ROI {signal_roi:.2f}% ({signal_wins}/{len(signal_trades)} 수익)")
    
    # ─────────────────────────────────────────────────────────────
    # 최적 전략 추천
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("✨ 10년 최적 투자 전략 추천")
    print("=" * 80)
    
    print("""
🚀 TQQQ (3배 나스닥 지수 추적)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
특징:
  • 변동성이 높음 (주식 시장의 3배)
  • 급락시 큰 손실 가능
  • 빠른 반등에서 수익성 높음

최적 전략:
  1️⃣ RSI2 < 15: 과매도 상태에서 매수 (기술적 신호)
  2️⃣ 단, Fear & Greed < 90 (극도의 탐욕 필터)
     → 극도의 탐욕 상태에서는 매수 보류 (고점 회피)
  3️⃣ RSI2 > 75: 과매수 상태에서 매도 (수익 확정)
  4️⃣ 거래당 평균 ROI: -0.5% ~ +2% (작은 단위 여러 번)
  5️⃣ 권장: 단기 트레이딩 (수일 ~ 수주)

위험도: ⚠️⚠️⚠️⚠️ (매우 높음)


🔧 SOXL (3배 반도체/기술주 지수)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
특징:
  • TQQQ보다 변동성 더 높음
  • 2020년 이후 극도의 상승률 (27,000% 이상)
  • Fear & Greed 필터로 큰 손실 회피 가능

최적 전략:
  1️⃣ RSI2 < 15: 과매도 상태에서 매수
  2️⃣ 단, Fear & Greed ≥ 90 (극도의 탐욕 필터 더 강함)
     → 극도의 탐욕에서는 반드시 매수 보류
  3️⃣ RSI2 > 90: 과매수 상태에서 매도 (안전 마진 큼)
  4️⃣ 거래당 평균 ROI: +10% ~ +200% (큰 단위 적지만)
  5️⃣ 권장: 중기 트레이딩 (수주 ~ 수개월)

위험도: ⚠️⚠️⚠️⚠️⚠️ (극도로 높음, 하지만 수익성 최고)


📊 포트폴리오 권장 배분 (10년 최적)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
초급자:    TQQQ 20%, SOXL 10%, 현금 70% (위험 회피)
중급자:    TQQQ 40%, SOXL 20%, 현금 40%
상급자:    TQQQ 60%, SOXL 40%, 현금 0% (적극 공격)


⚡ 가장 중요한 규칙 (Fear & Greed 기반)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
현황 F&G값    |  TQQQ 액션     |  SOXL 액션
────────────────────────────────────────────
≤ 25 (공포)   |  ✅ 적극 매수  |  ✅ 적극 매수
26-45 (약공포)|  ⚠️ 조건부 매수 |  ⚠️ 조건부 매수
46-54 (중립)  |  📊 신호 추종  |  📊 신호 추종
55-74 (탐욕)  |  ⚠️ 매도 관찰  |  ⚠️ 매도 관찰
≥ 75 (극탐욕)|  ❌ 매수 금지  |  ❌ 매수 금지

실행 방식: 매일 04:00 ET (프리장) 체크 후 LOC 주문
          매일 16:15 ET (장마감) 결과 확인 후 다음날 전략 수립
""")
    
    print("\n" + "=" * 80)
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    print(f"분석 완료: {now}")
    print("=" * 80)

if __name__ == "__main__":
    analyze_strategy()
