$ErrorActionPreference = 'Stop'
Set-Location "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT"

$pythonExe = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

Write-Host "[retention-schedule] Starting daily retention scheduler"

# APScheduler 및 필요 패키지 설치 확인
& $pythonExe -m pip install apscheduler -q

$code = @'
import os
import sys
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from workers.mqtt_retention import cleanup_old_logs, save_retention_log

SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    "/Users/batagota/BATAGOTA/10_AI_BATA/02_BATA_MQTT/data/mqtt_logs.db",
)

def scheduled_cleanup():
    print(f"[scheduler] cleanup triggered at {datetime.now().isoformat()}")
    result = cleanup_old_logs(SQLITE_PATH, 90)
    save_retention_log(result)
    print(f"[scheduler] cleanup done: deleted {result.get('deleted_count', 0)} logs")

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_cleanup, 'cron', hour=1, minute=0)  # 매일 1시
scheduler.start()

print("[scheduler] running... Press Ctrl+C to exit")
try:
    import time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("[scheduler] shutting down")
    scheduler.shutdown()
'@

& $pythonExe -c $code
