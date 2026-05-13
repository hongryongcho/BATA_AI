$target = Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -match "scheduler.py" -and
    $_.CommandLine -match "02_BATA_MQTT"
  } |
  Select-Object ProcessId, Name, CommandLine

if (-not $target) {
  Write-Output "STATUS: DOWN"
  exit 0
}

Write-Output "STATUS: UP"
$target | Format-Table -AutoSize | Out-String | Write-Output
