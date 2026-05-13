$ErrorActionPreference = 'Stop'

$baseUrl = 'http://127.0.0.1:8787'

try {
    $diagnostics = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/ops/diagnostics"
    $summary = [ordered]@{
        SERVICE = $diagnostics.service
        SQLITE_EXISTS = $diagnostics.sqlite.exists
        SQLITE_SIZE = $diagnostics.sqlite.size
        MQTT_HOST = $diagnostics.mqtt.host
        MQTT_PORT = $diagnostics.mqtt.port
        WEB_INDEX = $diagnostics.web.index_exists
    }

    $summary.GetEnumerator() | ForEach-Object { Write-Host ("{0}={1}" -f $_.Key, $_.Value) }
    $diagnostics | ConvertTo-Json -Depth 8
} catch {
    Write-Host 'DIAGNOSTICS=DOWN'
    Write-Host $_.Exception.Message
    exit 1
}