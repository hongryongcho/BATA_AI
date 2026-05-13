$ErrorActionPreference = 'Stop'
$configPath = "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT\config\mosquitto.conf"

if (-not (Test-Path $configPath)) {
    throw "Config not found: $configPath"
}

Write-Host "Starting Mosquitto with config: $configPath"
mosquitto -c $configPath -v
