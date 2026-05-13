export const MONITOR_ASSETS = [
  { code: 'NASDAQ', yahoo: '^IXIC' },
  { code: 'SP500', yahoo: '^GSPC' },
  { code: 'DOW', yahoo: '^DJI' },
  { code: 'TQQQ', yahoo: 'TQQQ' },
  { code: 'SOXL', yahoo: 'SOXL' },
  { code: 'TECL', yahoo: 'TECL' },
  { code: 'BULS', yahoo: 'BULS' },
  { code: 'UPRO', yahoo: 'UPRO' },
  { code: 'HIBL', yahoo: 'HIBL' },
  { code: 'TNA', yahoo: 'TNA' },
  { code: 'UDOW', yahoo: 'UDOW' },
  { code: 'MIDU', yahoo: 'MIDU' },
  { code: 'GDXU', yahoo: 'GDXU' },
  { code: 'DUSL', yahoo: 'DUSL' },
  { code: 'WEBL', yahoo: 'WEBL' },
  { code: 'LABU', yahoo: 'LABU' },
  { code: 'WANT', yahoo: 'WANT' },
  { code: 'DFEN', yahoo: 'DFEN' },
  { code: 'PILL', yahoo: 'PILL' },
  { code: 'FAS', yahoo: 'FAS' },
  { code: 'CURE', yahoo: 'CURE' },
  { code: 'TPOR', yahoo: 'TPOR' },
  { code: 'DPT', yahoo: 'DPT' },
  { code: 'UTSL', yahoo: 'UTSL' },
  { code: 'NAIL', yahoo: 'NAIL' },
  { code: 'RETL', yahoo: 'RETL' },
  { code: 'TMF', yahoo: 'TMF' },
  { code: 'OIL', yahoo: 'CL=F' },
  { code: 'BTC', yahoo: 'BTC-USD' },
  { code: 'ETH', yahoo: 'ETH-USD' },
  { code: 'US10Y', yahoo: '^TNX' },
  { code: 'DXY', yahoo: 'DX-Y.NYB' },
  { code: 'GOLD', yahoo: 'GC=F' },
  { code: 'GOOGL', yahoo: 'GOOGL' },
  { code: 'NVDA', yahoo: 'NVDA' },
  { code: 'AAPL', yahoo: 'AAPL' },
  { code: 'TSLA', yahoo: 'TSLA' },
  { code: 'MSFT', yahoo: 'MSFT' },
  { code: 'AMZN', yahoo: 'AMZN' },
];

const RSI_PERIOD = 14;
export const ETF_3X_CODES = new Set([
  'TQQQ', 'SOXL', 'TECL', 'BULS', 'UPRO', 'HIBL', 'TNA', 'UDOW', 'MIDU', 'GDXU', 'DUSL',
  'WEBL', 'LABU', 'WANT', 'DFEN', 'PILL', 'FAS', 'CURE', 'TPOR', 'DPT', 'UTSL', 'NAIL',
  'RETL', 'TMF',
]);

function getBooleanEnv(name, fallback = 'false') {
  return String(process.env[name] || fallback) === 'true';
}

function toUsd(value) {
  return `$${Number(value).toFixed(2)}`;
}

function toSignedPercent(value) {
  const sign = value >= 0 ? '+' : '-';
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

function mmddFromDateText(dateText) {
  const parts = String(dateText || '').split('-');
  if (parts.length !== 3) {
    return dateText;
  }

  return `${parts[1]}/${parts[2]}`;
}

function getNyTradeDate(referenceDate = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(referenceDate);
}

function buildHeaderLine(title) {
  return `${title}\n----------------------`;
}

function formatRowByColumns(ticker, valueText, metricText) {
  // 고정 너비 컬럼: ticker(6) + value(12) + metric(10) = 정렬된 출력
  const tickerCol = ticker.padEnd(6, ' ');
  const valueCol = valueText.padStart(12, ' ');
  const metricCol = `(${metricText.padStart(8, ' ')})`;
  return `${tickerCol}${valueCol}    ${metricCol}`;
}

function computeRsi(closes, period = RSI_PERIOD) {
  if (!Array.isArray(closes) || closes.length < period + 1) {
    return null;
  }

  const changes = [];
  for (let i = 1; i < closes.length; i += 1) {
    changes.push(closes[i] - closes[i - 1]);
  }

  let gains = 0;
  let losses = 0;
  for (let i = 0; i < period; i += 1) {
    const ch = changes[i];
    if (ch >= 0) gains += ch;
    else losses += Math.abs(ch);
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  for (let i = period; i < changes.length; i += 1) {
    const ch = changes[i];
    const gain = ch > 0 ? ch : 0;
    const loss = ch < 0 ? Math.abs(ch) : 0;
    avgGain = ((avgGain * (period - 1)) + gain) / period;
    avgLoss = ((avgLoss * (period - 1)) + loss) / period;
  }

  if (avgLoss === 0) {
    return 100;
  }

  const rs = avgGain / avgLoss;
  return 100 - (100 / (1 + rs));
}

async function fetchYahooDailyCloses(yahooSymbol) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahooSymbol)}?interval=1d&range=6mo`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`yahoo fetch failed: ${yahooSymbol} http=${response.status}`);
  }

  const payload = await response.json();
  const closes = payload?.chart?.result?.[0]?.indicators?.quote?.[0]?.close;
  if (!Array.isArray(closes)) {
    throw new Error(`no close data: ${yahooSymbol}`);
  }

  return closes
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v) && v > 0);
}

async function loadTickerRows() {
  const rows = await Promise.all(
    MONITOR_ASSETS.map(async (asset) => {
      try {
        const closes = await fetchYahooDailyCloses(asset.yahoo);
        if (closes.length < 2) {
          return null;
        }

        const latest = closes[closes.length - 1];
        const prev = closes[closes.length - 2];
        const changePct = prev === 0 ? 0 : ((latest - prev) / prev) * 100;
        const rsi = computeRsi(closes, RSI_PERIOD);

        return {
          ticker: asset.code,
          yahoo: asset.yahoo,
          close: latest,
          changePct,
          rsi,
        };
      } catch {
        return null;
      }
    }),
  );

  return rows.filter(Boolean);
}

function classifyFearGreed(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'Unknown';
  if (n <= 24) return 'Extreme Fear';
  if (n <= 44) return 'Fear';
  if (n <= 54) return 'Neutral';
  if (n <= 74) return 'Greed';
  return 'Extreme Greed';
}

async function loadFearGreed() {
  const response = await fetch('https://api.alternative.me/fng/?limit=370&format=json');
  if (!response.ok) {
    throw new Error(`fear-greed fetch failed http=${response.status}`);
  }

  const payload = await response.json();
  const items = Array.isArray(payload?.data) ? payload.data : [];

  const pick = (idx) => {
    const item = items[idx];
    if (!item) return null;
    const value = Number(item.value);
    return {
      value,
      label: item.value_classification || classifyFearGreed(value),
    };
  };

  return {
    now: pick(0),
    previousClose: pick(1),
    oneWeekAgo: pick(7),
    oneMonthAgo: pick(30),
    oneYearAgo: pick(365),
  };
}

function formatCloseSection(rows, title) {
  const sorted = [...rows].sort((a, b) => b.changePct - a.changePct);
  const overPlus10 = sorted.filter((r) => r.changePct >= 10);
  const plusToZero = sorted.filter((r) => r.changePct >= 0 && r.changePct < 10);
  const zeroToMinus10 = sorted.filter((r) => r.changePct < 0 && r.changePct > -10);
  const underMinus10 = sorted.filter((r) => r.changePct <= -10);

  const renderRow = (r) => formatRowByColumns(
    r.ticker,
    toUsd(r.close),
    toSignedPercent(r.changePct),
  );
  const lines = [buildHeaderLine(title)];

  const groups = [overPlus10, plusToZero, zeroToMinus10, underMinus10];
  let hasPrinted = false;
  groups.forEach((group) => {
    if (group.length === 0) {
      return;
    }

    if (hasPrinted) {
      lines.push('----------------------');
    }

    lines.push(...group.map(renderRow));
    hasPrinted = true;
  });

  return lines.join('\n');
}

function formatRsiSection(rows, dateLabel) {
  const available = rows.filter((r) => Number.isFinite(r.rsi));
  const sorted = [...available].sort((a, b) => b.rsi - a.rsi);
  const over80 = sorted.filter((r) => r.rsi >= 80);
  const over70 = sorted.filter((r) => r.rsi >= 70 && r.rsi < 80);
  const over50 = sorted.filter((r) => r.rsi >= 50 && r.rsi < 70);
  const under50 = sorted.filter((r) => r.rsi < 50);

  const renderRow = (r) => formatRowByColumns(
    r.ticker,
    toUsd(r.close),
    Number(r.rsi).toFixed(2),
  );
  const lines = [buildHeaderLine(`${dateLabel} RSI (${RSI_PERIOD})`)];

  const groups = [over80, over70, over50, under50];
  let hasPrinted = false;
  groups.forEach((group) => {
    if (group.length === 0) {
      return;
    }

    if (hasPrinted) {
      lines.push('----------------------');
    }

    lines.push(...group.map(renderRow));
    hasPrinted = true;
  });

  return lines.join('\n');
}

function formatFearGreedSection(dateLabel, fg) {
  const line = (title, item) => {
    if (!item || !Number.isFinite(item.value)) {
      return `${title}: N/A`;
    }

    return `${title}: ${item.value} (${item.label})`;
  };

  return [
    buildHeaderLine(`${dateLabel} Fear & Greed`),
    line('Now', fg.now),
    line('Previous Close', fg.previousClose),
    line('1 Week Ago', fg.oneWeekAgo),
    line('1 Month Ago', fg.oneMonthAgo),
    line('1 Year Ago', fg.oneYearAgo),
  ].join('\n');
}

function buildTelegramText(tradeDate, rows, fg, sectionTitle) {
  const dateLabel = mmddFromDateText(tradeDate);
  return [
    formatCloseSection(rows, `${dateLabel} ${sectionTitle} 📈`),
    '',
    formatRsiSection(rows, dateLabel),
    '',
    formatFearGreedSection(dateLabel, fg),
  ].join('\n');
}

async function sendTelegramMessage(text, token, chatId) {
  if (!token || !chatId) {
    throw new Error('Telegram token/chat id are required');
  }

  const escaped = text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');

  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const body = {
    chat_id: chatId,
    text: `<pre>${escaped}</pre>`,
    parse_mode: 'HTML',
    disable_web_page_preview: true,
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`telegram send failed http=${response.status} ${errText}`);
  }

  const data = await response.json();
  if (!data?.ok) {
    throw new Error(`telegram send failed: ${JSON.stringify(data)}`);
  }

  return {
    ok: true,
    chatId,
    messageId: data?.result?.message_id,
  };
}

export function isTelegramReportEnabled() {
  const desired = getBooleanEnv('TELEGRAM_REPORT_ENABLED', 'true');
  if (!desired) {
    return false;
  }

  const token = process.env.TELEGRAM_MAJOR_BOT_TOKEN || process.env.TELEGRAM_BOT_TOKEN || '';
  const chatId = process.env.TELEGRAM_MAJOR_CHAT_ID || process.env.TELEGRAM_NOTIFY_CHAT_ID || process.env.TELEGRAM_CHAT_ID || '';
  return Boolean(token && chatId);
}

export async function sendDailyTelegramCloseReport(tradeDate) {
  const resolvedTradeDate = tradeDate || getNyTradeDate();
  const rows = await loadTickerRows();
  if (rows.length === 0) {
    throw new Error('No ticker rows available for telegram report');
  }

  const majorRows = rows.filter((r) => !ETF_3X_CODES.has(r.ticker));
  const etfRows = rows.filter((r) => ETF_3X_CODES.has(r.ticker));
  const fearGreed = await loadFearGreed();

  const majorToken = process.env.TELEGRAM_MAJOR_BOT_TOKEN || process.env.TELEGRAM_BOT_TOKEN || '';
  const majorChatId = process.env.TELEGRAM_MAJOR_CHAT_ID || process.env.TELEGRAM_NOTIFY_CHAT_ID || process.env.TELEGRAM_CHAT_ID || '';
  const etfToken = process.env.TELEGRAM_ETF_BOT_TOKEN || '';
  const etfChatId = process.env.TELEGRAM_ETF_CHAT_ID || '';

  if (majorRows.length === 0) {
    throw new Error('No major-market rows available for telegram report');
  }

  const majorText = buildTelegramText(resolvedTradeDate, majorRows, fearGreed, '주요증시 마감 종가');
  const majorSent = await sendTelegramMessage(majorText, majorToken, majorChatId);

  let etfSent = null;
  let etfText = '';
  if (etfRows.length > 0 && etfToken && etfChatId) {
    etfText = buildTelegramText(resolvedTradeDate, etfRows, fearGreed, '3xETF 마감 종가');
    etfSent = await sendTelegramMessage(etfText, etfToken, etfChatId);
  }

  return {
    sent: true,
    chatId: majorSent.chatId,
    messageId: majorSent.messageId,
    text: majorText,
    etfSent: Boolean(etfSent),
    etfChatId: etfSent?.chatId || null,
    etfMessageId: etfSent?.messageId || null,
    etfReason: etfRows.length > 0 && !etfSent ? 'ETF bot token/chat id missing' : null,
    etfText,
    rowCount: rows.length,
  };
}
