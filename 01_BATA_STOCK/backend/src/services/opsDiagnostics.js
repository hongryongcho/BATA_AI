import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

import { getAutoReportDiagnostics } from './autoReportScheduler.js';
import { getPriceAlertDiagnostics } from './priceAlertService.js';
import { getRecipients } from './reportService.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const recipientsFilePath = path.resolve(__dirname, '../../data/report-recipients.json');

function getBooleanEnv(name, fallback = 'false') {
  return String(process.env[name] || fallback) === 'true';
}

function safeNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

async function getFileDiagnostics(filePath) {
  try {
    const stat = await fs.stat(filePath);
    return {
      exists: true,
      size: stat.size,
      updatedAt: stat.mtime.toISOString(),
    };
  } catch {
    return {
      exists: false,
      size: 0,
      updatedAt: null,
    };
  }
}

export async function getOpsDiagnostics() {
  const recipients = await getRecipients().catch(() => []);
  const recipientsFile = await getFileDiagnostics(recipientsFilePath);
  const scheduler = getAutoReportDiagnostics();
  const priceAlert = getPriceAlertDiagnostics();

  return {
    service: 'bata-stock-backend',
    generatedAt: new Date().toISOString(),
    process: {
      pid: process.pid,
      uptimeSeconds: Math.round(process.uptime()),
      nodeVersion: process.version,
      platform: process.platform,
      arch: process.arch,
    },
    runtime: {
      port: safeNumber(process.env.PORT || 4000, 4000),
      emailSendEnabled: getBooleanEnv('EMAIL_SEND_ENABLED', 'false'),
      telegramReportEnabled: getBooleanEnv('TELEGRAM_REPORT_ENABLED', 'true'),
      autoReportEnabled: getBooleanEnv('AUTO_REPORT_ENABLED', 'true'),
      autoReportRunOnStartup: getBooleanEnv('AUTO_REPORT_RUN_ON_STARTUP', 'false'),
      autoReportCron: process.env.AUTO_REPORT_CRON || '15 16 * * 1-5',
      autoReportTimezone: process.env.AUTO_REPORT_TIMEZONE || 'America/New_York',
      autoReportJobTimeoutMs: safeNumber(process.env.AUTO_REPORT_JOB_TIMEOUT_MS || 30000, 30000),
    },
    smtp: {
      configured: Boolean(process.env.SMTP_HOST && process.env.SMTP_USER && process.env.SMTP_PASS),
      host: process.env.SMTP_HOST || null,
      port: safeNumber(process.env.SMTP_PORT || 587, 587),
      secure: getBooleanEnv('SMTP_SECURE', 'false'),
      from: process.env.SMTP_FROM || process.env.SMTP_USER || null,
    },
    recipients: {
      count: recipients.length,
      file: recipientsFile,
      sample: recipients.slice(0, 3),
    },
    scheduler,
    priceAlert,
  };
}