$target = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match "node" -and
    $_.CommandLine -match "src/index\.js"
  } |
  Select-Object ProcessId, Name, CommandLine

if (-not $target) {
  Write-Output "STATUS: DOWN"
  exit 0
}

Write-Output "STATUS: UP"
$target | Format-Table -AutoSize | Out-String | Write-Output
