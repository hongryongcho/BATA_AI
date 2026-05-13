$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$statusScript = Join-Path $PSScriptRoot "status.ps1"
$healthScript = Join-Path $PSScriptRoot "health.ps1"
$startScript = Join-Path $PSScriptRoot "start.ps1"

function Invoke-ControlScript {
  param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath
  )

  powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath | Out-String
}

function Get-PrimaryState {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [Parameter(Mandatory = $true)]
    [string]$Prefix
  )

  $regex = "(?m)^${Prefix}:\s*(UP|PARTIAL|DOWN)"
  $match = [regex]::Match($Output, $regex)
  if ($match.Success) {
    return $match.Groups[1].Value
  }
  return "UNKNOWN"
}

Push-Location $projectRoot
try {
  $statusOutput = Invoke-ControlScript -ScriptPath $statusScript
  $healthOutput = Invoke-ControlScript -ScriptPath $healthScript

  $statusState = Get-PrimaryState -Output $statusOutput -Prefix "STATUS"
  $healthState = Get-PrimaryState -Output $healthOutput -Prefix "HEALTH"

  $restartReasons = @()
  if ($statusState -in @("DOWN", "PARTIAL", "UNKNOWN")) {
    $restartReasons += "STATUS=$statusState"
  }
  if ($healthState -in @("DOWN", "PARTIAL", "UNKNOWN")) {
    $restartReasons += "HEALTH=$healthState"
  }

  if ($restartReasons.Count -gt 0) {
    Invoke-ControlScript -ScriptPath $startScript | Out-Null
    Write-Output ("WATCHDOG: RESTART_TRIGGERED REASON=" + ($restartReasons -join ","))
  } else {
    Write-Output "WATCHDOG: OK STATUS=UP HEALTH=UP"
  }
} finally {
  Pop-Location
}
