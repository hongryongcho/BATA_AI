$ErrorActionPreference = 'Stop'

$baseUrl = 'http://127.0.0.1:4000'

try {
    $diagnostics = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/ops/diagnostics"
    $summary = [ordered]@{
        SERVICE = $diagnostics.service
        PID = $diagnostics.process.pid
        UPTIME_SECONDS = $diagnostics.process.uptimeSeconds
        EMAIL_SEND_ENABLED = $diagnostics.runtime.emailSendEnabled
        AUTO_REPORT_ENABLED = $diagnostics.runtime.autoReportEnabled
        AUTO_REPORT_CRON = $diagnostics.runtime.autoReportCron
        AUTO_REPORT_TIMEZONE = $diagnostics.runtime.autoReportTimezone
        SMTP_CONFIGURED = $diagnostics.smtp.configured
        RECIPIENTS = $diagnostics.recipients.count
        SCHEDULER_STATUS = $diagnostics.scheduler.status
        LAST_RUN_REASON = $diagnostics.scheduler.lastRunReason
        LAST_RUN_TRADE_DATE = $diagnostics.scheduler.lastRunTradeDate
        LAST_ERROR = $diagnostics.scheduler.lastError
    }

    $summary.GetEnumerator() | ForEach-Object { Write-Host ("{0}={1}" -f $_.Key, $_.Value) }
    $diagnostics | ConvertTo-Json -Depth 8
} catch {
    Write-Host 'DIAGNOSTICS=DOWN'
    Write-Host $_.Exception.Message
    exit 1
}