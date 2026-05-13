$projects = @(
  @{
    Name = "00_BATAGOTA"
    StatusScript = "E:\01_HT_DATA\10_AI_BATA\00_BATAGOTA\scripts\control\status.ps1"
    HealthScript = "E:\01_HT_DATA\10_AI_BATA\00_BATAGOTA\scripts\control\health.ps1"
  },
  @{
    Name = "01_BATA_STOCK"
    StatusScript = "E:\01_HT_DATA\10_AI_BATA\01_BATA_STOCK\backend\scripts\control\status.ps1"
    HealthScript = "E:\01_HT_DATA\10_AI_BATA\01_BATA_STOCK\backend\scripts\control\health.ps1"
  },
  @{
    Name = "02_BATA_MQTT"
    StatusScript = "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT\scripts\control\status.ps1"
    HealthScript = "E:\01_HT_DATA\10_AI_BATA\02_BATA_MQTT\scripts\control\health.ps1"
  }
)

$summary = @()
$detailed = @()
$allGreen = $true

foreach ($project in $projects) {
  $statusRaw = (& powershell -ExecutionPolicy Bypass -File $project.StatusScript | Out-String).Trim()
  $healthRaw = (& powershell -ExecutionPolicy Bypass -File $project.HealthScript | Out-String).Trim()

  $statusLine = "STATUS: UNKNOWN"
  $healthLine = "HEALTH: UNKNOWN"

  if ($statusRaw) {
    $statusLine = ($statusRaw -split "`r?`n")[0].Trim()
  }
  if ($healthRaw) {
    $healthLine = ($healthRaw -split "`r?`n")[0].Trim()
  }

  $statusIsUp = $statusLine -match "^STATUS:\s+UP$"
  $healthIsUp = $healthLine -match "^HEALTH:\s+UP"
  $isDegraded = (-not $statusIsUp) -or (-not $healthIsUp)

  if ($isDegraded) {
    $allGreen = $false
  }

  $summary += [PSCustomObject]@{
    Project = $project.Name
    Status  = $statusLine
    Health  = $healthLine
    Result  = if ($isDegraded) { "DEGRADED" } else { "GREEN" }
  }

  $detailed += [PSCustomObject]@{
    Project    = $project.Name
    StatusRaw  = $statusRaw
    HealthRaw  = $healthRaw
  }
}

Write-Output "=== BATA INTEGRATED STATUS ==="
$summary | Format-Table -AutoSize | Out-String | Write-Output

$overall = if ($allGreen) { "ALL GREEN" } else { "DEGRADED" }
$overallColor = if ($allGreen) { "Green" } else { "Yellow" }
Write-Host "=== OVERALL: $overall ===" -ForegroundColor $overallColor

foreach ($item in $summary) {
  $rowColor = switch ($item.Result) {
    "GREEN" { "Green" }
    default { "Yellow" }
  }
  Write-Host ("[{0}] {1} | {2} | {3}" -f $item.Result, $item.Project, $item.Status, $item.Health) -ForegroundColor $rowColor
}

Write-Output "=== DETAILS ==="
foreach ($item in $detailed) {
  Write-Output "--- $($item.Project) ---"
  Write-Output $item.StatusRaw
  Write-Output $item.HealthRaw
  Write-Output ""
}
