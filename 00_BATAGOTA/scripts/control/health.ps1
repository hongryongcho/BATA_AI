function Test-TelegramBotProcess {
  $all = Get-CimInstance Win32_Process |
    Where-Object {
      $_.CommandLine -match "interfaces\\telegram\\bot.py|interfaces/telegram/bot.py" -and
      $_.CommandLine -match "00_BATAGOTA"
    }

  $allIds = @($all | ForEach-Object { $_.ProcessId })
  $count = (@($all | Where-Object { $allIds -notcontains $_.ParentProcessId }) | Measure-Object).Count

  return $count
}

$webHealth = "DOWN"
$httpCode = ""

$stockHealth = "DOWN"
$stockHttpCode = ""

try {
  $res = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -UseBasicParsing -TimeoutSec 3
  $webHealth = "UP"
  $httpCode = "$($res.StatusCode)"
} catch {
}

if ($webHealth -eq "DOWN") {
  try {
    $res = Invoke-WebRequest -Uri "http://127.0.0.1:8787/" -UseBasicParsing -TimeoutSec 3
    $webHealth = "PARTIAL"
    $httpCode = "$($res.StatusCode)"
  } catch {
  }
}

try {
  $res = Invoke-WebRequest -Uri "http://127.0.0.1:4000/health" -UseBasicParsing -TimeoutSec 3
  $stockHealth = "UP"
  $stockHttpCode = "$($res.StatusCode)"
} catch {
}

if ($stockHealth -eq "DOWN") {
  try {
    $res = Invoke-WebRequest -Uri "http://127.0.0.1:4000/" -UseBasicParsing -TimeoutSec 3
    $stockHealth = "PARTIAL"
    $stockHttpCode = "$($res.StatusCode)"
  } catch {
  }
}

$botCount = Test-TelegramBotProcess
$botUp = $botCount -gt 0

if (($webHealth -eq "UP" -or $webHealth -eq "PARTIAL") -and $botUp -and ($stockHealth -eq "UP" -or $stockHealth -eq "PARTIAL")) {
  Write-Output "HEALTH: UP HTTP=$httpCode BOT=UP PROCS=$botCount STOCK_HTTP=$stockHttpCode"
  exit 0
}

if ($webHealth -ne "DOWN" -or $botUp -or $stockHealth -ne "DOWN") {
  Write-Output "HEALTH: PARTIAL HTTP=$httpCode BOT=$(([string]$botUp).ToUpper()) PROCS=$botCount STOCK_HTTP=$stockHttpCode"
  exit 0
}

Write-Output "HEALTH: DOWN BOT=DOWN PROCS=0 STOCK=DOWN"
