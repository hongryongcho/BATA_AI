$targetCount = (Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -match "scheduler.py" -and
    $_.CommandLine -match "02_BATA_MQTT"
  } |
  Measure-Object).Count

if ($targetCount -gt 0) {
  Write-Output "HEALTH: UP PROCS=$targetCount"
} else {
  Write-Output "HEALTH: DOWN"
}
