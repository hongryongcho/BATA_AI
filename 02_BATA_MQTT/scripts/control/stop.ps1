$target = Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -match "scheduler.py" -and
    $_.CommandLine -match "02_BATA_MQTT"
  }

if (-not $target) {
  Write-Output "NOT_RUNNING: bata-mqtt"
  exit 0
}

foreach ($proc in $target) {
  $procId = $proc.ProcessId
  Stop-Process -Id $procId -Force
  Write-Output "STOPPED: bata-mqtt PID=$procId"
}
