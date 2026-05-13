import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

import { MONITOR_ASSETS } from './telegramReportService.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const stateFilePath = path.resolve(__dirname, '../../data/price-alert-state.json');

const BUCKET_SIZE = 5;
const DEFAULT_INTERVAL_MS = 5 * 60 * 1000;
const DEFAULT_ICON_STYLE = 'classic';
const DEFAULT_THRESHOLDS = [1.5, 3, 5, 10, 15];

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
  lastError: null,
  checks: 0,
  alertsSent: 0,
  tradeDate: null,
};

let timer = null;

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

function getChatConfig() {
  const token = process.env.TELEGRAM_BOT_TOKEN || '';
  const chatId = process.env.TELEGRAM_NOTIFY_CHAT_ID || process.env.TELEGRAM_CHAT_ID || '';
  return { token, chatId, ready: Boolean(token && chatId) };
}

function getIntervalMs() {
  const parsed = Number(process.env.PRICE_ALERT_INTERVAL_MS || DEFAULT_INTERVAL_MS);
  if (!Number.isFinite(parsed) || parsed < 60_000) {
    return DEFAULT_INTERVAL_MS;
  }

  return parsed;
}

function getIconMultiplier() {
  const parsed = Number(process.env.PRICE_ALERT_ICON_MULTIPLIER || 1);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 1;
  }

  return Math.min(5, Math.floor(parsed));
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

function parseThresholds() {
  const raw = String(process.env.PRICE_ALERT_THRESHOLDS || '').trim();
  if (!raw) {
    return DEFAULT_THRESHOLDS;
  }

  const parsed = raw
    .split(',')
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isFinite(v) && v > 0)
    .sort((a, b) => a - b);

  return parsed.length > 0 ? [...new Set(parsed)] : DEFAULT_THRESHOLDS;
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

function iconRepeat(icon, percentAbs, multiplier = 1) {
  const bucketCount = Math.max(1, Math.floor(percentAbs / BUCKET_SIZE));
  const count = Math.max(1, bucketCount * Math.max(1, multiplier));
  return icon.repeat(count);
}

function toSignedPercent(value) {
  const sign = value >= 0 ? '+' : '-';
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

function toUsd(value) {
  return `$${Number(value).toFixed(2)}`;
}

function buildAlertText(row, threshold) {
  const up = row.changePct >= 0;
  const iconSet = getIconSet();
  const iconMultiplier = getIconMultiplier();
  const icon = up ? iconSet.bull : iconSet.bear;
  const title = up
    ? `시세 + ${threshold}% 상승 ${iconRepeat(icon, threshold, iconMultiplier)}`
    : `시세 - ${threshold}% 하락 ${iconRepeat(icon, threshold, iconMultiplier)}`;

  const body = `${row.ticker.padEnd(5, ' ')} ${toUsd(row.close)} ( ${toSignedPercent(row.changePct)})`;
  return `${title}\n${body}`;
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
  const response = await fetch(url);
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
  monitorState.lastCheckAt = new Date().toISOString();
  monitorState.checks += 1;

  const { token, chatId, ready } = getChatConfig();
  if (!ready) {
    monitorState.lastError = 'telegram token/chat id missing';
    return;
  }

  const tradeDate = getNyTradeDate();
  monitorState.tradeDate = tradeDate;

  const state = await readState();
  const thresholds = parseThresholds();
  if (state.tradeDate !== tradeDate) {
    state.tradeDate = tradeDate;
    state.tickers = {};
  }

  for (const asset of MONITOR_ASSETS) {
    try {
      const row = await fetchRealtimeRow(asset.yahoo);
      row.ticker = asset.code;

      const absChange = Math.abs(row.changePct);
      const triggeredThreshold = findTriggeredThreshold(absChange, thresholds);
      if (triggeredThreshold <= 0) {
        continue;
      }

      const dir = row.changePct >= 0 ? 'up' : 'down';
      const itemState = state.tickers[asset.code] || { up: 0, down: 0 };
      const lastThreshold = dir === 'up' ? Number(itemState.up || 0) : Number(itemState.down || 0);

      if (triggeredThreshold <= lastThreshold) {
        continue;
      }

      const text = buildAlertText(row, triggeredThreshold);
      await sendTelegram(text, token, chatId);

      if (dir === 'up') itemState.up = triggeredThreshold;
      else itemState.down = triggeredThreshold;
      state.tickers[asset.code] = itemState;
      monitorState.alertsSent += 1;
    } catch (error) {
      monitorState.lastError = error instanceof Error ? error.message : String(error);
    }
  }

  await writeState(state);
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
