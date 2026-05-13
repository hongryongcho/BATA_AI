$ErrorActionPreference = 'Stop'
Set-Location "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT"

if (Test-Path ".venv\Scripts\python.exe") {
    & ".venv\Scripts\python.exe" "workers\mqtt_logger.py"
} else {
    python "workers\mqtt_logger.py"
}
