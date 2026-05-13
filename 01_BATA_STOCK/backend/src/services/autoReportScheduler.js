import cron from 'node-cron';

import { getDailyMarketSummary } from './marketService.js';
import { sendDailySummaryReport } from './reportService.js';
import { isTelegramReportEnabled, sendDailyTelegramCloseReport } from './telegramReportService.js';

const DEFAULT_CRON = '15 16 * * 1-5'; // 뉴욕 시간 기준 평일 16:15(미국장 마감 15분 후)
const DEFAULT_TIMEZONE = 'America/New_York';
const DEFAULT_JOB_TIMEOUT_MS = 30000;

const schedulerState = {
  active: false,
  startedAt: null,
  enabled: null,
  emailEnabled: null,
  telegramEnabled: null,
  cronExpr: DEFAULT_CRON,
  timezone: DEFAULT_TIMEZONE,
  status: 'idle',
  lastRunAt: null,
  lastRunReason: null,
  lastRunTradeDate: null,
  lastRunResult: null,
  lastError: null,
  lastSuccessAt: null,
  lastSkippedAt: null,
  lastSkippedReason: null,
  lastSentTradeDate: '',
  jobTimeoutMs: DEFAULT_JOB_TIMEOUT_MS,
  successfulRuns: 0,
  failedRuns: 0,
  skippedRuns: 0,
};

let schedulerJob = null;

function formatDateInTimezone(date, timeZone) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

function getNyTradeDate(referenceDate = new Date()) {
  return formatDateInTimezone(referenceDate, 'America/New_York');
}

function getBooleanEnv(name, fallback = 'false') {
  return String(process.env[name] || fallback) === 'true';
}

function getSchedulerSnapshot() {
  return {
    ...schedulerState,
    jobScheduled: Boolean(schedulerJob),
  };
}

function setSchedulerConfig() {
  schedulerState.enabled = getBooleanEnv('AUTO_REPORT_ENABLED', 'true');
  schedulerState.emailEnabled = getBooleanEnv('EMAIL_SEND_ENABLED', 'false');
  schedulerState.telegramEnabled = isTelegramReportEnabled();
  schedulerState.cronExpr = process.env.AUTO_REPORT_CRON || DEFAULT_CRON;
  schedulerState.timezone = process.env.AUTO_REPORT_TIMEZONE || DEFAULT_TIMEZONE;
  schedulerState.jobTimeoutMs = getTimeoutMs();
}

function getTimeoutMs() {
  const parsed = Number(process.env.AUTO_REPORT_JOB_TIMEOUT_MS || DEFAULT_JOB_TIMEOUT_MS);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_JOB_TIMEOUT_MS;
  }

  return parsed;
}

function withTimeout(promise, timeoutMs, label) {
  let timer = null;

  const timeoutPromise = new Promise((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${label} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  return Promise.race([
    promise.finally(() => {
      if (timer) {
        clearTimeout(timer);
      }
    }),
    timeoutPromise,
  ]);
}

async function runAutoReportJob(reason = 'scheduled', options = {}) {
  const force = Boolean(options.force);
  const tradeDate = getNyTradeDate();

  schedulerState.status = 'running';
  schedulerState.lastRunAt = new Date().toISOString();
  schedulerState.lastRunReason = reason;
  schedulerState.lastRunTradeDate = tradeDate;
  schedulerState.lastError = null;

  if (!force && schedulerState.lastSentTradeDate === tradeDate) {
    const result = {
      ok: true,
      skipped: true,
      reason: 'duplicate-trade-date',
      tradeDate,
      sentTo: [],
    };

    schedulerState.skippedRuns += 1;
    schedulerState.status = 'idle';
    schedulerState.lastSkippedAt = new Date().toISOString();
    schedulerState.lastSkippedReason = result.reason;
    schedulerState.lastRunResult = result;

    console.log(`[auto-report] skipped duplicate send for tradeDate=${tradeDate}`);
    return result;
  }

  try {
    const timeoutMs = schedulerState.jobTimeoutMs || DEFAULT_JOB_TIMEOUT_MS;
    const summary = await withTimeout(
      getDailyMarketSummary(tradeDate),
      timeoutMs,
      'getDailyMarketSummary',
    );

    const channelResults = {};
    const sentTo = [];

    if (schedulerState.emailEnabled) {
      const emailResult = await withTimeout(
        sendDailySummaryReport(summary),
        timeoutMs,
        'sendDailySummaryReport',
      );
      channelResults.email = {
        sent: true,
        sentTo: emailResult.sentTo,
        subject: emailResult.subject,
      };
      sentTo.push(...emailResult.sentTo);
    }

    if (schedulerState.telegramEnabled) {
      const telegramResult = await withTimeout(
        sendDailyTelegramCloseReport(tradeDate),
        timeoutMs,
        'sendDailyTelegramCloseReport',
      );
      channelResults.telegram = {
        sent: true,
        chatId: telegramResult.chatId,
        messageId: telegramResult.messageId,
      };
      sentTo.push(`telegram:${telegramResult.chatId}`);
    }

    if (!schedulerState.emailEnabled && !schedulerState.telegramEnabled) {
      throw new Error('No delivery channel enabled. Enable EMAIL_SEND_ENABLED or TELEGRAM_REPORT_ENABLED.');
    }

    const response = {
      ok: true,
      skipped: false,
      reason,
      tradeDate,
      sentTo,
      date: tradeDate,
      channels: channelResults,
    };

    schedulerState.lastSentTradeDate = tradeDate;
    schedulerState.successfulRuns += 1;
    schedulerState.status = 'idle';
    schedulerState.lastSuccessAt = new Date().toISOString();
    schedulerState.lastRunResult = response;

    console.log(
      `[auto-report] sent (${reason}) tradeDate=${tradeDate} channels=${Object.keys(channelResults).join(',')}`,
    );

    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const response = {
      ok: false,
      skipped: false,
      reason,
      tradeDate,
      error: message,
    };

    schedulerState.failedRuns += 1;
    schedulerState.status = 'error';
    schedulerState.lastError = message;
    schedulerState.lastRunResult = response;

    console.error(
      `[auto-report] failed (${reason}) tradeDate=${tradeDate}:`,
      message,
    );

    return response;
  }
}

export function startAutoReportScheduler() {
  setSchedulerConfig();
  schedulerState.startedAt = new Date().toISOString();

  if (!schedulerState.enabled) {
    schedulerState.active = false;
    schedulerState.status = 'disabled';
    console.log('[auto-report] disabled by AUTO_REPORT_ENABLED=false');
    return getSchedulerSnapshot();
  }

  if (!schedulerState.emailEnabled && !schedulerState.telegramEnabled) {
    schedulerState.active = false;
    schedulerState.status = 'disabled';
    console.log('[auto-report] disabled because no delivery channel is enabled');
    return getSchedulerSnapshot();
  }

  if (!cron.validate(schedulerState.cronExpr)) {
    schedulerState.active = false;
    schedulerState.status = 'error';
    schedulerState.lastError = `invalid cron expression: ${schedulerState.cronExpr}`;
    console.error(`[auto-report] invalid cron expression: ${schedulerState.cronExpr}`);
    return getSchedulerSnapshot();
  }

  if (!schedulerJob) {
    schedulerJob = cron.schedule(
      schedulerState.cronExpr,
      async () => {
        await runAutoReportJob('scheduled');
      },
      { timezone: schedulerState.timezone },
    );
  }

  schedulerState.active = true;
  schedulerState.status = 'idle';

  console.log(
    `[auto-report] scheduler started cron='${schedulerState.cronExpr}' timezone='${schedulerState.timezone}'`,
  );

  if (String(process.env.AUTO_REPORT_RUN_ON_STARTUP || 'false') === 'true') {
    runAutoReportJob('startup', { force: true }).catch((error) => {
      console.error('[auto-report] startup run failed:', error instanceof Error ? error.message : error);
    });
  }

  return getSchedulerSnapshot();
}

export function getAutoReportDiagnostics() {
  return getSchedulerSnapshot();
}

export function runAutoReportNow(options = {}) {
  const force = options.force === undefined ? true : Boolean(options.force);
  return runAutoReportJob('manual', { force });
}
