function Get-RootManagedProcessList {
  param(
    [string]$Pattern
  )

  $all = Get-CimInstance Win32_Process |
    Where-Object {
      $_.CommandLine -match $Pattern -and
      $_.CommandLine -match "00_BATAGOTA"
    }

  $allIds = @($all | ForEach-Object { $_.ProcessId })
  @($all | Where-Object { $allIds -notcontains $_.ParentProcessId })
}

$target = Get-RootManagedProcessList -Pattern "run_mqtt_app_dashboard.py"

$botTarget = Get-RootManagedProcessList -Pattern "interfaces\\telegram\\bot.py|interfaces/telegram/bot.py"

if (-not $target -and -not $botTarget) {
  Write-Output "NOT_RUNNING: bata-core"
  exit 0
}

foreach ($proc in $target) {
  $procId = $proc.ProcessId
  try {
    Stop-Process -Id $procId -Force -ErrorAction Stop
    Write-Output "STOPPED: bata-core-web PID=$procId"
  } catch {
    Write-Output "SKIP_STOP: bata-core-web PID=$procId"
  }
}

foreach ($proc in $botTarget) {
  $procId = $proc.ProcessId
  try {
    Stop-Process -Id $procId -Force -ErrorAction Stop
    Write-Output "STOPPED: bata-core-telegram PID=$procId"
  } catch {
    Write-Output "SKIP_STOP: bata-core-telegram PID=$procId"
  }
}
