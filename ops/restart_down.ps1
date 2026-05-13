$projects = @(
  @{
    Name = "00_BATAGOTA"
    StatusScript = "E:\01_HT_DATA\10_AI_BATA\00_BATAGOTA\scripts\control\status.ps1"
    HealthScript = "E:\01_HT_DATA\10_AI_BATA\00_BATAGOTA\scripts\control\health.ps1"
    StartScript = "E:\01_HT_DATA\10_AI_BATA\00_BATAGOTA\scripts\control\start.ps1"
  },
  @{
    Name = "01_BATA_STOCK"
    StatusScript = "E:\01_HT_DATA\10_AI_BATA\01_BATA_STOCK\backend\scripts\control\status.ps1"
    HealthScript = "E:\01_HT_DATA\10_AI_BATA\01_BATA_STOCK\backend\scripts\control\health.ps1"
    StartScript = "E:\01_HT_DATA\10_AI_BATA\01_BATA_STOCK\backend\scripts\control\start.ps1"
  },
  @{
    Name = "02_BATA_MQTT"
    StatusScript = "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT\scripts\control\status.ps1"
    HealthScript = "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT\scripts\control\health.ps1"
    StartScript = "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT\scripts\control\start.ps1"
  }
)

$restarted = @()

foreach ($project in $projects) {
  $statusRaw = (& powershell -ExecutionPolicy Bypass -File $project.StatusScript | Out-String).Trim()
  $healthRaw = (& powershell -ExecutionPolicy Bypass -File $project.HealthScript | Out-String).Trim()

  $statusLine = if ($statusRaw) { ($statusRaw -split "`r?`n")[0].Trim() } else { "STATUS: UNKNOWN" }
  $healthLine = if ($healthRaw) { ($healthRaw -split "`r?`n")[0].Trim() } else { "HEALTH: UNKNOWN" }

  $isDown = ($statusLine -notmatch "^STATUS:\s+UP$") -or ($healthLine -match "^HEALTH:\s+DOWN$")

  if ($isDown) {
    Write-Host "[RESTART] $($project.Name)" -ForegroundColor Yellow
    & powershell -ExecutionPolicy Bypass -File $project.StartScript | Out-Host
    $restarted += $project.Name
  } else {
    Write-Host "[SKIP] $($project.Name) already running" -ForegroundColor Green
  }
}

if ($restarted.Count -eq 0) {
  Write-Host "No DOWN projects found." -ForegroundColor Green
} else {
  Write-Host ("Restarted projects: " + ($restarted -join ", ")) -ForegroundColor Yellow
}

Write-Host "Run ops/check_all.ps1 to confirm consolidated status." -ForegroundColor Cyan
