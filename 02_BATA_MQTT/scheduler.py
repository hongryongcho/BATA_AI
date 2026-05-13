"""
BATAGOTA MQTT 스케줄링 관리자
보관 정리 + Google Drive 백업을 자동으로 스케줄링
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent))

# 환경변수 로드
load_dotenv()

SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db"
)


def run_retention_cleanup():
    """보관 정리 작업"""
    try:
        from workers.mqtt_retention import cleanup_old_logs, save_retention_log
        
        print(f"\n[scheduler] 보관 정리 시작: {datetime.now(timezone.utc).isoformat()}")
        
        result = cleanup_old_logs(SQLITE_PATH, retention_days=90)
        save_retention_log(result)
        
        print(f"[scheduler] 보관 정리 완료: {result.get('status')}")
        print(f"           삭제된 로그: {result.get('deleted_count')}개")
        print(f"           남은 로그: {result.get('total_after')}개")
    
    except Exception as e:
        print(f"[scheduler] ❌ 보관 정리 실패: {str(e)}")


def run_monthly_backup():
    """월간 백업 작업"""
    try:
        from mqtt_backup import backup_mqtt_logs
        
        print(f"\n[scheduler] 월간 백업 시작: {datetime.now(timezone.utc).isoformat()}")
        
        result = backup_mqtt_logs(
            db_path=SQLITE_PATH,
            credentials_path="config/google_credentials.json",
            token_path="config/google_token.json",
            folder_name="BATAGOTA_MQTT_ARCHIVE"
        )
        
        print(f"[scheduler] 월간 백업 완료: {result.get('status')}")
        if result.get('status') == 'success':
            print(f"           파일: {result.get('year_month')}.csv")
            print(f"           링크: {result.get('file_link')}")
    
    except Exception as e:
        print(f"[scheduler] ❌ 월간 백업 실패: {str(e)}")


def main():
    """스케줄러 메인 루프"""
    print("="*60)
    print("  BATAGOTA MQTT 스케줄링 관리자")
    print("="*60)
    print()
    print(f"시작 시간: {datetime.now(timezone.utc).isoformat()}")
    print(f"SQLite 경로: {SQLITE_PATH}")
    print()
    
    # 스케줄러 생성
    scheduler = BackgroundScheduler()
    
    # 매일 1:00 AM에 보관 정리
    scheduler.add_job(
        run_retention_cleanup,
        trigger=CronTrigger(hour=1, minute=0),
        id='daily_retention',
        name='Daily retention cleanup',
        replace_existing=True
    )
    print("✅ 스케줄 등록: 매일 1:00 AM - 보관 정리")
    
    # 매월 1일 2:00 AM에 백업
    scheduler.add_job(
        run_monthly_backup,
        trigger=CronTrigger(day=1, hour=2, minute=0),
        id='monthly_backup',
        name='Monthly backup to Google Drive',
        replace_existing=True
    )
    print("✅ 스케줄 등록: 매월 1일 2:00 AM - Google Drive 백업")
    print()
    
    # 스케줄러 시작
    scheduler.start()
    print("🚀 스케줄러 시작됨 (Ctrl+C로 종료)")
    print()
    
    try:
        # 메인 루프 (계속 실행)
        while True:
            import time
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n[scheduler] 종료 신호 감지. 스케줄러 종료 중...")
        scheduler.shutdown()
        print("[scheduler] 스케줄러 종료 완료")


if __name__ == "__main__":
    main()
