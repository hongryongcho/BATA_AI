$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$dbPath = Join-Path $projectRoot 'data\mqtt_logs.db'
$logsPath = Join-Path $projectRoot 'logs'
$backupsPath = Join-Path $projectRoot 'backups'

$processes = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -match 'scheduler.py' -and
        $_.CommandLine -match '02_BATA_MQTT'
    } |
    Select-Object ProcessId, Name, CommandLine

$dbExists = Test-Path $dbPath
$dbInfo = $null
if ($dbExists) {
    $dbInfo = Get-Item $dbPath | Select-Object FullName, Length, LastWriteTimeUtc
}

$latestBackup = Get-ChildItem $backupsPath -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1 Name, Length, LastWriteTimeUtc

$diagnostics = [ordered]@{
    service = 'bata-mqtt-scheduler'
    generatedAt = [DateTime]::UtcNow.ToString('o')
    process = [ordered]@{
        count = @($processes).Count
        items = @($processes)
    }
    sqlite = [ordered]@{
        path = $dbPath
        exists = $dbExists
        size = if ($dbInfo) { $dbInfo.Length } else { 0 }
        updatedAt = if ($dbInfo) { $dbInfo.LastWriteTimeUtc.ToString('o') } else { $null }
    }
    logs = [ordered]@{
        path = $logsPath
        exists = (Test-Path $logsPath)
    }
    backups = [ordered]@{
        path = $backupsPath
        latest = if ($latestBackup) {
            [ordered]@{
                name = $latestBackup.Name
                size = $latestBackup.Length
                updatedAt = $latestBackup.LastWriteTimeUtc.ToString('o')
            }
        } else {
            $null
        }
    }
}

Write-Host ('SERVICE={0}' -f $diagnostics.service)
Write-Host ('PROCESS_COUNT={0}' -f $diagnostics.process.count)
Write-Host ('SQLITE_EXISTS={0}' -f $diagnostics.sqlite.exists)
Write-Host ('SQLITE_SIZE={0}' -f $diagnostics.sqlite.size)
$diagnostics | ConvertTo-Json -Depth 8