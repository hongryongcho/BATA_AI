$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
Push-Location $projectRoot
try {
  $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    Start-Process -FilePath $venvPython -ArgumentList "scheduler.py" -WorkingDirectory $projectRoot
  } else {
    Start-Process -FilePath "py" -ArgumentList "scheduler.py" -WorkingDirectory $projectRoot
  }
  Write-Output "STARTED: bata-mqtt"
} finally {
  Pop-Location
}
