$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
Push-Location $projectRoot
try {
  function Get-RootManagedProcess {
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

  function Test-StockBackendUp {
    param(
      [string]$StockStatusScript
    )

    try {
      $stockOut = powershell -NoProfile -ExecutionPolicy Bypass -File $StockStatusScript | Out-String
      return ($stockOut -match "(?m)^STATUS:\s*UP")
    } catch {
      return $false
    }
  }

  $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
  $pythonCmd = if (Test-Path $venvPython) { $venvPython } else { "py" }

  $webProc = Get-RootManagedProcess -Pattern "run_mqtt_app_dashboard.py" |
    Select-Object -First 1

  if (-not $webProc) {
    Start-Process -FilePath $pythonCmd -ArgumentList "scripts/run_mqtt_app_dashboard.py" -WorkingDirectory $projectRoot
    Write-Output "STARTED: bata-core-web"
  } else {
    Write-Output "ALREADY_RUNNING: bata-core-web PID=$($webProc.ProcessId)"
  }

  $botProc = Get-RootManagedProcess -Pattern "interfaces\\telegram\\bot.py|interfaces/telegram/bot.py" |
    Select-Object -First 1

  if (-not $botProc) {
    Start-Process -FilePath $pythonCmd -ArgumentList "interfaces/telegram/bot.py" -WorkingDirectory $projectRoot
    Write-Output "STARTED: bata-core-telegram"
  } else {
    Write-Output "ALREADY_RUNNING: bata-core-telegram PID=$($botProc.ProcessId)"
  }

  $stockRoot = (Resolve-Path (Join-Path $projectRoot "..\01_BATA_STOCK\backend")).Path
  $stockStartScript = Join-Path $stockRoot "scripts\control\start.ps1"
  $stockStatusScript = Join-Path $stockRoot "scripts\control\status.ps1"
  $stockUp = Test-StockBackendUp -StockStatusScript $stockStatusScript

  if (-not $stockUp) {
    powershell -NoProfile -ExecutionPolicy Bypass -File $stockStartScript | Out-Null
    Write-Output "STARTED: bata-stock-backend"
  } else {
    Write-Output "ALREADY_RUNNING: bata-stock-backend"
  }

  Write-Output "STARTED: bata-core + bata-stock-backend"
} finally {
  Pop-Location
}
