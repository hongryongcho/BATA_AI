try {
  $res = Invoke-WebRequest -Uri "http://127.0.0.1:4000/health" -UseBasicParsing -TimeoutSec 3
  Write-Output "HEALTH: UP HTTP=$($res.StatusCode)"
  exit 0
} catch {
}

try {
  $res = Invoke-WebRequest -Uri "http://127.0.0.1:4000/" -UseBasicParsing -TimeoutSec 3
  Write-Output "HEALTH: PARTIAL HTTP=$($res.StatusCode)"
} catch {
  Write-Output "HEALTH: DOWN"
}
