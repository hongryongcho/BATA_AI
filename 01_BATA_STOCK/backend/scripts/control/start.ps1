$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
Push-Location $projectRoot
try {
  $nodeExe = "C:\Program Files\nodejs\node.exe"
  if (-not (Test-Path $nodeExe)) {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) {
      $nodeExe = $cmd.Source
    } else {
      Write-Output "ERROR: node not found"
      exit 1
    }
  }

  Start-Process -FilePath $nodeExe -ArgumentList "src/index.js" -WorkingDirectory $projectRoot
  Write-Output "STARTED: bata-stock"
} finally {
  Pop-Location
}
