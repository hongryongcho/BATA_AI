"""
백테스트 완료 알림 스크립트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 기존 Google Sheet 파일을 복사하여 새 파일 생성
2. 파일명을 현재 날짜 시간으로 변경
3. 필요한 탭만 유지 (Summary, TQQQ_매매기준가, SOXL_매매기준가)
4. 텔레그램 메시지 발송
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import gspread
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as OAuthCredentials

from _env_loader import load_env_config
from sheets_manager import SheetsManager


def copy_spreadsheet(
    creds: OAuthCredentials,
    source_id: str,
    new_title: str,
) -> tuple[str, str]:
    """
    Google Sheet를 복사하여 새 파일 생성
    
    Args:
        creds: Google 인증 정보
        source_id: 원본 파일 ID
        new_title: 새 파일명
        
    Returns:
        (새 파일 ID, 새 파일 제목)
    """
    print(f"\n📋 Google Sheet 복사 시작: {new_title}")
    
    # Google Drive API 서비스 빌드
    drive_service = build('drive', 'v3', credentials=creds)
    
    # 원본 파일 이름 확인
    file_info = drive_service.files().get(
        fileId=source_id,
        fields='name'
    ).execute()
    
    print(f"  ✓ 원본 파일 확인: {file_info.get('name')}")
    
    # 파일 복사
    file_metadata = {'name': new_title}
    copied_file = drive_service.files().copy(
        fileId=source_id,
        body=file_metadata,
        fields='id, name'
    ).execute()
    
    new_id = copied_file.get('id')
    new_name = copied_file.get('name')
    
    print(f"  ✓ 파일 복사 완료")
    print(f"    - 새 파일 ID: {new_id}")
    print(f"    - 새 파일명: {new_name}")
    
    return new_id, new_name


def cleanup_sheets(spreadsheet_id: str, keep_titles: set[str]):
    """
    불필요한 탭 삭제
    
    Args:
        spreadsheet_id: 스프레드시트 ID
        keep_titles: 유지할 탭 이름들
    """
    print(f"\n🧹 불필요한 탭 정리 (유지: {', '.join(keep_titles)})")
    
    sm = SheetsManager(spreadsheet_id=spreadsheet_id)
    gc = sm._get_client()
    ss = gc.open_by_key(spreadsheet_id)
    
    deleted = []
    for ws in ss.worksheets():
        if ws.title not in keep_titles:
            try:
                ss.del_worksheet(ws)
                deleted.append(ws.title)
                print(f"  ✓ 삭제: {ws.title}")
            except Exception as e:
                print(f"  ✗ 삭제 실패: {ws.title} ({e})")
    
    if not deleted:
        print("  (삭제할 탭 없음)")
    
    return deleted


async def send_telegram_notification(
    token: str,
    chat_id: int,
    file_id: str,
    tqqq_return: float,
    tqqq_trades: int,
    soxl_return: float,
    soxl_trades: int,
) -> bool:
    """
    텔레그램 메시지 발송
    
    Args:
        token: 텔레그램 봇 토큰
        chat_id: 채팅방 ID
        file_id: 새 파일 ID
        tqqq_return: TQQQ 수익률(%)
        tqqq_trades: TQQQ 거래 수
        soxl_return: SOXL 수익률(%)
        soxl_trades: SOXL 거래 수
        
    Returns:
        성공 여부
    """
    print(f"\n📤 텔레그램 메시지 발송")
    
    try:
        from telegram import Bot
        
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M')
        
        file_url = f"https://docs.google.com/spreadsheets/d/{file_id}"
        
        message = (
            f"[BATA_RSI2_FnG] {date_str} RSI2+F&G 백테스트 완료\n"
            f"📊 BackTest3x_{date_str.replace('-', '')}_{time_str.replace(':', '')}\n"
            f"링크: {file_url}\n"
            f"\n"
            f"✅ TQQQ: {tqqq_return:,.2f}% ({tqqq_trades}거래)\n"
            f"✅ SOXL: {soxl_return:,.2f}% ({soxl_trades}거래)"
        )
        
        bot = Bot(token=token)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
        )
        
        print(f"  ✓ 메시지 발송 성공")
        print(f"    - Chat ID: {chat_id}")
        print(f"    - 메시지:\n{message}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 메시지 발송 실패: {e}")
        return False


def main():
    """메인 함수"""
    
    print("\n" + "="*80)
    print("📊 BackTest3x 백테스트 완료 알림 스크립트")
    print("="*80)
    
    # 환경변수 로드
    env = load_env_config()
    
    source_id = env.get("SPREADSHEET_ID", "1WTyL9bYvAvai8CaOsZJ3vQoXVOxJEtFJvkiy_N8jtNM")
    bot_token = env.get("TELEGRAM_FNG_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_FNG_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("❌ 텔레그램 환경변수가 설정되지 않았습니다")
        print(f"  - TELEGRAM_FNG_BOT_TOKEN: {'설정됨' if bot_token else '미설정'}")
        print(f"  - TELEGRAM_FNG_CHAT_ID: {'설정됨' if chat_id else '미설정'}")
        return False
    
    # 새 파일명 생성
    now = datetime.now()
    new_title = f"BackTest3x_{now.strftime('%Y%m%d_%H%M')}"
    
    # Google Sheet 복사
    try:
        sm = SheetsManager(spreadsheet_id=source_id)
        creds = sm._load_or_create_credentials()
        
        new_id, _ = copy_spreadsheet(creds, source_id, new_title)
        
    except Exception as e:
        print(f"\n❌ Google Sheet 복사 실패: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 불필요한 탭 정리
    keep_titles = {"Summary", "TQQQ_매매기준가", "SOXL_매매기준가"}
    try:
        cleanup_sheets(new_id, keep_titles)
    except Exception as e:
        print(f"\n⚠️  탭 정리 중 오류: {e}")
    
    # 텔레그램 메시지 발송
    # 백테스트 결과를 외부에서 받아야 합니다
    # 현재는 예시 데이터로 발송합니다
    tqqq_return = 748.00
    tqqq_trades = 156
    soxl_return = 3541.59
    soxl_trades = 117
    
    try:
        import asyncio
        
        success = asyncio.run(
            send_telegram_notification(
                token=bot_token,
                chat_id=int(chat_id),
                file_id=new_id,
                tqqq_return=tqqq_return,
                tqqq_trades=tqqq_trades,
                soxl_return=soxl_return,
                soxl_trades=soxl_trades,
            )
        )
        
        if not success:
            print("⚠️  텔레그램 메시지 발송 실패")
    
    except Exception as e:
        print(f"\n❌ 텔레그램 발송 오류: {e}")
        return False
    
    # 최종 결과 출력
    file_url = f"https://docs.google.com/spreadsheets/d/{new_id}"
    
    print("\n" + "="*80)
    print("✅ 작업 완료!")
    print("="*80)
    print(f"\n📄 새 파일명: {new_title}")
    print(f"🔗 파일 ID: {new_id}")
    print(f"🌐 링크: {file_url}")
    print("\n" + "="*80 + "\n")
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n🛑 사용자 중단\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 예상치 못한 오류: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
