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
  @($all | Where-Object { $allIds -notcontains $_.ParentProcessId }) |
    Select-Object ProcessId, Name, CommandLine
}

function Get-StockBackendStatus {
  $stockRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\01_BATA_STOCK\backend")).Path
  $stockStatusScript = Join-Path $stockRoot "scripts\control\status.ps1"

  try {
    $stockOut = powershell -NoProfile -ExecutionPolicy Bypass -File $stockStatusScript | Out-String
    if ($stockOut -match "(?m)^STATUS:\s*UP") {
      return @{ up = $true; detail = $stockOut }
    }
  } catch {
  }

  return @{ up = $false; detail = "" }
}

$webTarget = Get-RootManagedProcessList -Pattern "run_mqtt_app_dashboard.py"

$botTarget = Get-RootManagedProcessList -Pattern "interfaces\\telegram\\bot.py|interfaces/telegram/bot.py"

$stockStatus = Get-StockBackendStatus

$webUp = @($webTarget).Count -gt 0
$botUp = @($botTarget).Count -gt 0
$stockUp = [bool]$stockStatus.up

if (-not $webUp -and -not $botUp -and -not $stockUp) {
  Write-Output "STATUS: DOWN"
  exit 0
}

if ($webUp -and $botUp -and $stockUp) {
  Write-Output "STATUS: UP"
} else {
  Write-Output "STATUS: PARTIAL"
}

Write-Output "WEB_UP=$webUp BOT_UP=$botUp STOCK_UP=$stockUp"

if ($webUp) {
  Write-Output "--- WEB ---"
  $webTarget | Format-Table -AutoSize | Out-String | Write-Output
}

if ($botUp) {
  Write-Output "--- TELEGRAM ---"
  $botTarget | Format-Table -AutoSize | Out-String | Write-Output
}

if ($stockUp) {
  Write-Output "--- STOCK ---"
  Write-Output "STATUS: UP"
}
