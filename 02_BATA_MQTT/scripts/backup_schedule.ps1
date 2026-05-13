$ErrorActionPreference = 'Stop'
Set-Location "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT"

$pythonExe = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

Write-Host "[backup-schedule] Starting monthly backup scheduler"

& $pythonExe -m pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib -q

$code = @'
import os
import sys
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from workers.mqtt_backup import main as backup_main

def scheduled_backup():
    print(f"[scheduler] backup triggered at {datetime.now().isoformat()}")
    try:
        backup_main()
        print("[scheduler] backup completed successfully")
    except Exception as e:
        print(f"[scheduler] backup failed: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_backup, 'cron', day=1, hour=2, minute=0)  # 매월 1일 2시
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
