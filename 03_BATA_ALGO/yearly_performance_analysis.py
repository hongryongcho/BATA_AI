"""
연도별 수익률 분석 스크립트
TQQQ와 SOXL의 매년 성과를 계산하고 비교
"""

from pathlib import Path
import pandas as pd
from sheets_manager import SheetsManager
from _env_loader import get_spreadsheet_id
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

def extract_year_from_date(date_str):
    """날짜 문자열에서 연도 추출"""
    try:
        if not date_str or date_str.strip() == '':
            return None
        # YYYY-MM-DD 형식 가정
        return int(date_str[:4])
    except:
        return None

def analyze_yearly_performance():
    spreadsheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=spreadsheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(spreadsheet_id)
    
    print("=" * 90)
    print("📅 10년 연도별 수익률 분석 (2016-2026)")
    print("=" * 90)
    
    tickers = ['TQQQ', 'SOXL']
    yearly_data = {}
    
    for ticker in tickers:
        print(f"\n{'=' * 90}")
        print(f"📊 {ticker} 연도별 수익률")
        print(f"{'=' * 90}\n")
        
        ws = ss.worksheet(f"{ticker}_매매기준가")
        all_values = ws.get_all_values()
        
        # 헤더 찾기
        header_idx = None
        for idx, row in enumerate(all_values):
            if row and any("buy_date" in str(cell) or "date" in str(cell).lower() for cell in row):
                header_idx = idx
                break
        
        if not header_idx:
            print(f"⚠️ {ticker} 헤더를 찾을 수 없습니다.")
            continue
        
        headers = all_values[header_idx]
        data_rows = all_values[header_idx + 1:]
        
        # 컬럼 인덱스 찾기
        try:
            buy_date_idx = next(i for i, h in enumerate(headers) if "buy_date" in str(h).lower() or "매수일" in str(h))
            sell_date_idx = next(i for i, h in enumerate(headers) if "sell_date" in str(h).lower() or "매도일" in str(h))
            roi_idx = next(i for i, h in enumerate(headers) if "roi" in str(h).lower() or "수익률" in str(h))
        except StopIteration:
            print(f"⚠️ {ticker}: 필수 컬럼을 찾을 수 없습니다.")
            continue
        
        # 거래 데이터 파싱
        yearly_stats = {}
        all_trades = []
        
        for row in data_rows:
            if not row or not row[0]:
                continue
            
            try:
                buy_date = row[buy_date_idx] if buy_date_idx < len(row) else ""
                sell_date = row[sell_date_idx] if sell_date_idx < len(row) else ""
                roi_str = row[roi_idx] if roi_idx < len(row) else "0"
                
                # ROI 숫자 추출
                roi = float(roi_str.replace('%', '').strip()) if roi_str else 0
                
                # 연도 추출 (매도일 기준)
                year = extract_year_from_date(sell_date) or extract_year_from_date(buy_date)
                
                if year and 2016 <= year <= 2026:
                    if year not in yearly_stats:
                        yearly_stats[year] = {
                            'trades': [],
                            'total_roi': 0,
                            'wins': 0,
                            'losses': 0,
                            'count': 0
                        }
                    
                    yearly_stats[year]['trades'].append(roi)
                    yearly_stats[year]['count'] += 1
                    yearly_stats[year]['total_roi'] += roi
                    
                    if roi > 0:
                        yearly_stats[year]['wins'] += 1
                    elif roi < 0:
                        yearly_stats[year]['losses'] += 1
                    
                    all_trades.append({
                        'year': year,
                        'buy_date': buy_date,
                        'sell_date': sell_date,
                        'roi': roi
                    })
            except (ValueError, IndexError) as e:
                continue
        
        # 연도별 결과 출력
        if yearly_stats:
            yearly_data[ticker] = yearly_stats
            
            total_all_roi = 0
            total_all_count = 0
            
            for year in sorted(yearly_stats.keys()):
                stats = yearly_stats[year]
                avg_roi = stats['total_roi'] / stats['count'] if stats['count'] > 0 else 0
                win_rate = stats['wins'] / stats['count'] * 100 if stats['count'] > 0 else 0
                
                print(f"📅 {year}년")
                print(f"   총 수익률: {stats['total_roi']:+.2f}%")
                print(f"   거래 수: {stats['count']}회 (수익: {stats['wins']}회, 손실: {stats['losses']}회)")
                print(f"   평균 ROI: {avg_roi:+.2f}% ({win_rate:.1f}% 승률)")
                print()
                
                total_all_roi += stats['total_roi']
                total_all_count += stats['count']
            
            print(f"{'─' * 90}")
            print(f"🏆 {ticker} 전체 합계 (2016-2026)")
            print(f"   누적 수익률: {total_all_roi:+.2f}%")
            print(f"   총 거래: {total_all_count}회")
            print(f"   평균 거래 ROI: {total_all_roi/total_all_count if total_all_count > 0 else 0:+.2f}%")
        else:
            print(f"❌ {ticker}: 분석할 거래 데이터가 없습니다.")
    
    # ─────────────────────────────────────────────────────────────
    # 비교 분석
    # ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print("🔄 TQQQ vs SOXL 비교")
    print(f"{'=' * 90}\n")
    
    if 'TQQQ' in yearly_data and 'SOXL' in yearly_data:
        print("연도   | TQQQ 수익률 | SOXL 수익률 | 차이 (SOXL-TQQQ) | SOXL 초과수익\n" + "─" * 85)
        
        all_years = sorted(set(
            list(yearly_data.get('TQQQ', {}).keys()) + 
            list(yearly_data.get('SOXL', {}).keys())
        ))
        
        tqqq_total = 0
        soxl_total = 0
        
        for year in all_years:
            tqqq_roi = yearly_data['TQQQ'][year]['total_roi'] if year in yearly_data['TQQQ'] else 0
            soxl_roi = yearly_data['SOXL'][year]['total_roi'] if year in yearly_data['SOXL'] else 0
            
            diff = soxl_roi - tqqq_roi
            
            print(f"{year}  | {tqqq_roi:>11.2f}% | {soxl_roi:>11.2f}% | {diff:>16.2f}% | {'SOXL 우위' if soxl_roi > tqqq_roi else 'TQQQ 우위'}")
            
            tqqq_total += tqqq_roi
            soxl_total += soxl_roi
        
        print("─" * 85)
        print(f"합계  | {tqqq_total:>11.2f}% | {soxl_total:>11.2f}% | {soxl_total - tqqq_total:>16.2f}% | {'✨ SOXL 압도적 우위' if soxl_total > tqqq_total else 'TQQQ 우위'}")
        
        improvement = ((soxl_total - tqqq_total) / abs(tqqq_total) * 100) if tqqq_total != 0 else 0
        print(f"\n💡 SOXL의 TQQQ 대비 초과수익: {improvement:+.1f}%p")
    
    print(f"\n{'=' * 90}")
    print(f"분석 완료: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"{'=' * 90}\n")

if __name__ == "__main__":
    analyze_yearly_performance()
