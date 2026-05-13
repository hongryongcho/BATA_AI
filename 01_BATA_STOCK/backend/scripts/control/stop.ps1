$target = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match "node" -and
    $_.CommandLine -match "src/index\.js"
  }

if (-not $target) {
  Write-Output "NOT_RUNNING: bata-stock"
  exit 0
}

foreach ($proc in $target) {
  $procId = $proc.ProcessId
  Stop-Process -Id $procId -Force
  Write-Output "STOPPED: bata-stock PID=$procId"
}
