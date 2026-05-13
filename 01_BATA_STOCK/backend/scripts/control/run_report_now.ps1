$ErrorActionPreference = 'Stop'

$baseUrl = 'http://127.0.0.1:4000'
$body = @{ force = $true } | ConvertTo-Json

try {
    $result = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/ops/report/run-now" -ContentType 'application/json' -Body $body
    $result | ConvertTo-Json -Depth 8
} catch {
    Write-Host 'RUN_NOW=FAILED'
    Write-Host $_.Exception.Message
    exit 1
}