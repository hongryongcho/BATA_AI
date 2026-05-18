import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

import { ETF_3X_CODES, MONITOR_ASSETS } from './telegramReportService.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const stateFilePath = path.resolve(__dirname, '../../data/price-alert-state.json');

const DEFAULT_INTERVAL_MS = 5 * 60 * 1000;
const DEFAULT_ICON_STYLE = 'classic';
const DEFAULT_THRESHOLDS = [1.5, 3, 5, 10, 15];
const DEFAULT_FETCH_TIMEOUT_MS = 15000;

const ICON_PRESETS = {
  classic: { bull: '🐂', bear: '🐻' },
  strong: { bull: '🦬', bear: '🐻' },
  soft: { bull: '🐮', bear: '🐻' },
  mini: { bull: '🐃', bear: '🐻' },
};

const monitorState = {
  active: false,
  enabled: false,
  intervalMs: DEFAULT_INTERVAL_MS,
  startedAt: null,
  lastCheckAt: null,
  lastDurationMs: 0,
  lastError: null,
  checks: 0,
  busySkips: 0,
  alertsSent: 0,
  tradeDate: null,
};

let timer = null;
let checkInProgress = false;

function getBooleanEnv(name, fallback = 'false') {
  return String(process.env[name] || fallback) === 'true';
}

function getNyTradeDate(referenceDate = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(referenceDate);
}

function getMajorChatConfig() {
  const token = process.env.TELEGRAM_MAJOR_BOT_TOKEN || process.env.TELEGRAM_BOT_TOKEN || '';
  const chatId = process.env.TELEGRAM_MAJOR_CHAT_ID || process.env.TELEGRAM_NOTIFY_CHAT_ID || process.env.TELEGRAM_CHAT_ID || '';
  return { token, chatId, ready: Boolean(token && chatId) };
}

function getEtfChatConfig() {
  const token = process.env.TELEGRAM_ETF_BOT_TOKEN || '';
  const chatId = process.env.TELEGRAM_ETF_CHAT_ID || '';
  return { token, chatId, ready: Boolean(token && chatId) };
}

function getIntervalMs() {
  const parsed = Number(process.env.PRICE_ALERT_INTERVAL_MS || DEFAULT_INTERVAL_MS);
  if (!Number.isFinite(parsed) || parsed < 60_000) {
    return DEFAULT_INTERVAL_MS;
  }

  return parsed;
}

function getIconSet() {
  const style = String(process.env.PRICE_ALERT_ICON_STYLE || DEFAULT_ICON_STYLE).trim().toLowerCase();
  const preset = ICON_PRESETS[style] || ICON_PRESETS[DEFAULT_ICON_STYLE];

  const customBull = String(process.env.PRICE_ALERT_BULL_ICON || '').trim();
  const customBear = String(process.env.PRICE_ALERT_BEAR_ICON || '').trim();

  return {
    style,
    bull: customBull || preset.bull,
    bear: customBear || preset.bear,
  };
}

function parseThresholds(envKey = 'PRICE_ALERT_THRESHOLDS', fallback = DEFAULT_THRESHOLDS) {
  const raw = String(process.env[envKey] || '').trim();
  if (!raw) return fallback;

  const parsed = raw
    .split(',')
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isFinite(v) && v > 0)
    .sort((a, b) => a - b);

  return parsed.length > 0 ? [...new Set(parsed)] : fallback;
}

function parseMajorThresholds() {
  return parseThresholds('PRICE_ALERT_THRESHOLDS', [1.5, 3, 5, 10, 15]);
}

function parseEtfThresholds() {
  return parseThresholds('PRICE_ALERT_ETF_THRESHOLDS', [5, 10, 15]);
}

function findTriggeredThreshold(absChange, thresholds) {
  let selected = 0;
  for (const th of thresholds) {
    if (absChange >= th) {
      selected = th;
    }
  }

  return selected;
}

function getFetchTimeoutMs() {
  const parsed = Number(process.env.PRICE_ALERT_FETCH_TIMEOUT_MS || DEFAULT_FETCH_TIMEOUT_MS);
  if (!Number.isFinite(parsed) || parsed < 1000) {
    return DEFAULT_FETCH_TIMEOUT_MS;
  }

  return parsed;
}

function getThresholdLevel(threshold, thresholds) {
  const ordered = [...new Set((thresholds || [])
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v) && v > 0))]
    .sort((a, b) => a - b);

  const exactIndex = ordered.findIndex((value) => value === threshold);
  if (exactIndex >= 0) {
    return exactIndex + 1;
  }

  const fallbackIndex = ordered.findIndex((value) => threshold <= value);
  if (fallbackIndex >= 0) {
    return fallbackIndex + 1;
  }

  return 1;
}

function iconRepeat(icon, threshold, thresholds) {
  const count = Math.max(1, getThresholdLevel(threshold, thresholds));
  return icon.repeat(count);
}

function toSignedPercent(value) {
  const sign = value >= 0 ? '+' : '-';
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

function toUsd(value) {
  return `$${Number(value).toFixed(2)}`;
}

function buildBatchAlertText(alerts) {
  const iconSet = getIconSet();

  // 상승/하락 분리
  const upAlerts = alerts.filter((a) => a.row.changePct >= 0);
  const downAlerts = alerts.filter((a) => a.row.changePct < 0);

  const lines = [];
  const now = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'America/New_York',
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date());

  lines.push(`📊 시세 알림 [${now} NY] (${alerts.length}건)`);
  lines.push('──────────────────');

  for (const { row, threshold } of upAlerts) {
    const icon = iconRepeat(iconSet.bull, threshold, row.thresholds);
    lines.push(`${icon} ${row.ticker.padEnd(6)} ${toUsd(row.close).padStart(10)}  (${toSignedPercent(row.changePct).padStart(8)})  ≥${threshold}%`);
  }
  if (upAlerts.length > 0 && downAlerts.length > 0) lines.push('──────────────────');
  for (const { row, threshold } of downAlerts) {
    const icon = iconRepeat(iconSet.bear, threshold, row.thresholds);
    lines.push(`${icon} ${row.ticker.padEnd(6)} ${toUsd(row.close).padStart(10)}  (${toSignedPercent(row.changePct).padStart(8)})  ≥${threshold}%`);
  }

  return lines.join('\n');
}

async function readState() {
  try {
    const raw = await fs.readFile(stateFilePath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return { tradeDate: null, tickers: {} };
    }

    return {
      tradeDate: typeof parsed.tradeDate === 'string' ? parsed.tradeDate : null,
      tickers: parsed.tickers && typeof parsed.tickers === 'object' ? parsed.tickers : {},
    };
  } catch {
    return { tradeDate: null, tickers: {} };
  }
}

async function writeState(state) {
  await fs.mkdir(path.dirname(stateFilePath), { recursive: true });
  await fs.writeFile(stateFilePath, JSON.stringify(state, null, 2), 'utf8');
}

async function fetchRealtimeRow(ticker) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=5m&range=1d`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), getFetchTimeoutMs());
  const response = await fetch(url, { signal: controller.signal }).finally(() => {
    clearTimeout(timeout);
  });
  if (!response.ok) {
    throw new Error(`chart fetch failed ${ticker} http=${response.status}`);
  }

  const payload = await response.json();
  const result = payload?.chart?.result?.[0];
  const closes = result?.indicators?.quote?.[0]?.close;
  const previousClose = Number(result?.meta?.previousClose ?? result?.meta?.chartPreviousClose ?? 0);

  if (!Array.isArray(closes) || !Number.isFinite(previousClose) || previousClose <= 0) {
    throw new Error(`invalid realtime data ${ticker}`);
  }

  const filtered = closes
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v) && v > 0);

  if (filtered.length === 0) {
    throw new Error(`empty realtime close ${ticker}`);
  }

  const close = filtered[filtered.length - 1];
  const changePct = ((close - previousClose) / previousClose) * 100;

  return {
    ticker,
    close,
    changePct,
  };
}

async function sendTelegram(text, token, chatId) {
  const escaped = text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');

  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      text: `<pre>${escaped}</pre>`,
      parse_mode: 'HTML',
      disable_web_page_preview: true,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`telegram alert failed http=${response.status} ${errorText}`);
  }
}

async function checkPriceAlerts() {
  if (checkInProgress) {
    monitorState.busySkips += 1;
    return;
  }

  checkInProgress = true;
  const startedAt = Date.now();
  monitorState.lastCheckAt = new Date().toISOString();
  monitorState.checks += 1;

  try {
    const majorCfg = getMajorChatConfig();
    if (!majorCfg.ready) {
      monitorState.lastError = 'major telegram token/chat id missing';
      return;
    }
    const etfCfg = getEtfChatConfig();

    const tradeDate = getNyTradeDate();
    monitorState.tradeDate = tradeDate;

    const state = await readState();
    if (state.tradeDate !== tradeDate) {
      state.tradeDate = tradeDate;
      state.tickers = {};
    }

    const majorAlerts = [];
    const etfAlerts = [];
    let fetchRejectedCount = 0;
    let lastFetchFailure = '';

    const jobs = MONITOR_ASSETS.map(async (asset) => {
      const isEtf = ETF_3X_CODES.has(asset.code);
      const thresholds = isEtf ? parseEtfThresholds() : parseMajorThresholds();

      const row = await fetchRealtimeRow(asset.yahoo);
      row.ticker = asset.code;
      row.thresholds = thresholds;

      const absChange = Math.abs(row.changePct);
      const triggeredThreshold = findTriggeredThreshold(absChange, thresholds);
      if (triggeredThreshold <= 0) return null;

      const dir = row.changePct >= 0 ? 'up' : 'down';
      const itemState = state.tickers[asset.code] || { up: 0, down: 0 };
      const lastThreshold = dir === 'up' ? Number(itemState.up || 0) : Number(itemState.down || 0);
      if (triggeredThreshold <= lastThreshold) return null;

      return {
        isEtf,
        row,
        threshold: triggeredThreshold,
        dir,
        itemState,
        asset,
      };
    });

    const settled = await Promise.allSettled(jobs);
    for (const result of settled) {
      if (result.status === 'rejected') {
        fetchRejectedCount += 1;
        lastFetchFailure = result.reason instanceof Error ? result.reason.message : String(result.reason);
        continue;
      }

      const entry = result.value;
      if (!entry) continue;

      if (entry.isEtf) etfAlerts.push(entry);
      else majorAlerts.push(entry);
    }

    if (fetchRejectedCount >= settled.length && settled.length > 0) {
      monitorState.lastError = `all ticker fetch failed (${fetchRejectedCount}/${settled.length}): ${lastFetchFailure}`;
    } else {
      monitorState.lastError = null;
    }

    // 주요증시 일괄 전송
    if (majorAlerts.length > 0 && majorCfg.ready) {
      try {
        await sendTelegram(buildBatchAlertText(majorAlerts), majorCfg.token, majorCfg.chatId);
        for (const { dir, itemState, asset, threshold } of majorAlerts) {
          if (dir === 'up') itemState.up = threshold;
          else itemState.down = threshold;
          state.tickers[asset.code] = itemState;
          monitorState.alertsSent += 1;
        }
      } catch (error) {
        monitorState.lastError = error instanceof Error ? error.message : String(error);
      }
    }

    // 3xETF 일괄 전송
    if (etfAlerts.length > 0) {
      if (etfCfg.ready) {
        try {
          await sendTelegram(buildBatchAlertText(etfAlerts), etfCfg.token, etfCfg.chatId);
          for (const { dir, itemState, asset, threshold } of etfAlerts) {
            if (dir === 'up') itemState.up = threshold;
            else itemState.down = threshold;
            state.tickers[asset.code] = itemState;
            monitorState.alertsSent += 1;
          }
        } catch (error) {
          monitorState.lastError = error instanceof Error ? error.message : String(error);
        }
      } else {
        monitorState.lastError = 'ETF telegram token/chat id missing';
      }
    }

    await writeState(state);
  } finally {
    monitorState.lastDurationMs = Date.now() - startedAt;
    checkInProgress = false;
  }
}

export function getPriceAlertDiagnostics() {
  return {
    ...monitorState,
    timerActive: Boolean(timer),
  };
}

export function startPriceAlertMonitor() {
  const enabled = getBooleanEnv('PRICE_ALERT_ENABLED', 'true');
  const intervalMs = getIntervalMs();

  monitorState.enabled = enabled;
  monitorState.intervalMs = intervalMs;
  monitorState.startedAt = new Date().toISOString();

  if (!enabled) {
    monitorState.active = false;
    return getPriceAlertDiagnostics();
  }

  if (timer) {
    clearInterval(timer);
    timer = null;
  }

  timer = setInterval(() => {
    checkPriceAlerts().catch((error) => {
      monitorState.lastError = error instanceof Error ? error.message : String(error);
    });
  }, intervalMs);

  checkPriceAlerts().catch((error) => {
    monitorState.lastError = error instanceof Error ? error.message : String(error);
  });

  monitorState.active = true;
  return getPriceAlertDiagnostics();
}
