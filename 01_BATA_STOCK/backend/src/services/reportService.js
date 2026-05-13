import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

import nodemailer from 'nodemailer';
import PDFDocument from 'pdfkit';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const recipientsFilePath = path.resolve(__dirname, '../../data/report-recipients.json');
const defaultRecipients = ['hongryong.cho@gmail.com'];
const MARKET_TIMEZONE = 'America/New_York';
const DELIVERY_TIMEZONE = 'Asia/Seoul';

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function getRecipients() {
  const recipients = await loadRecipients();
  return recipients;
}

export async function addRecipient(email) {
  const normalized = normalizeEmail(email);
  if (!normalized || !emailPattern.test(normalized)) {
    throw new Error('Invalid email format');
  }

  const recipients = await loadRecipients();
  if (recipients.includes(normalized)) {
    return recipients;
  }

  const next = [...recipients, normalized].sort((a, b) => a.localeCompare(b));
  await saveRecipients(next);
  return next;
}

export async function removeRecipient(email) {
  const normalized = normalizeEmail(email);
  const recipients = await loadRecipients();
  const next = recipients.filter((item) => item !== normalized);
  await saveRecipients(next);
  return next;
}

export async function sendDailySummaryReport(summary) {
  const recipients = await loadRecipients();
  if (recipients.length === 0) {
    throw new Error('No recipients registered');
  }

  const reportContext = buildReportContext(summary);
  const transporter = createTransporter();
  const subject = `[BATA] US Market Close Report | Market ${reportContext.marketDate} | Sent ${reportContext.deliveryDate}`;
  const pdfBuffer = await buildPdfBuffer(reportContext);
  const html = buildReportHtml(reportContext);

  await transporter.sendMail({
    from: process.env.SMTP_FROM || process.env.SMTP_USER,
    to: recipients.join(','),
    subject,
    text: buildPlainText(reportContext),
    html,
    attachments: [
      {
        filename: `bata-daily-report-${reportContext.marketDate}.pdf`,
        content: pdfBuffer,
        contentType: 'application/pdf',
      },
    ],
  });

  return {
    sent: true,
    sentTo: recipients,
    subject,
    date: reportContext.marketDate,
  };
}

export function buildReportPreviewHtml(summary) {
  return buildReportHtml(buildReportContext(summary));
}

async function loadRecipients() {
  await ensureRecipientsFile();
  const raw = await fs.readFile(recipientsFilePath, 'utf8');
  const parsed = JSON.parse(raw);
  const recipients = Array.isArray(parsed.recipients)
    ? parsed.recipients.map(normalizeEmail).filter(Boolean)
    : [];

  if (recipients.length === 0) {
    await saveRecipients(defaultRecipients);
    return [...defaultRecipients];
  }

  return [...new Set(recipients)];
}

async function ensureRecipientsFile() {
  const directory = path.dirname(recipientsFilePath);
  await fs.mkdir(directory, { recursive: true });

  try {
    await fs.access(recipientsFilePath);
  } catch {
    await saveRecipients(defaultRecipients);
  }
}

async function saveRecipients(recipients) {
  const payload = {
    recipients,
    updatedAt: new Date().toISOString(),
  };
  await fs.writeFile(recipientsFilePath, JSON.stringify(payload, null, 2), 'utf8');
}

function normalizeEmail(value) {
  if (typeof value !== 'string') {
    return '';
  }

  return value.trim().toLowerCase();
}

function createTransporter() {
  const host = process.env.SMTP_HOST;
  const port = Number(process.env.SMTP_PORT || 587);
  const secure = String(process.env.SMTP_SECURE || 'false') === 'true';
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASS;

  if (!host || !user || !pass) {
    throw new Error('SMTP env is missing. Set SMTP_HOST, SMTP_USER, SMTP_PASS and SMTP_FROM.');
  }

  return nodemailer.createTransport({
    host,
    port,
    secure,
    auth: {
      user,
      pass,
    },
  });
}

function buildPlainText(summary) {
  const lines = [
    `Delivery Date (KST): ${summary.deliveryDate}`,
    `Market Date (NY): ${summary.marketDate}`,
    `Rendered At (KST): ${summary.deliveryTimestamp}`,
    `Updated At (KST): ${summary.updatedAtDisplay}`,
    '',
    `Summary: ${summary.summary}`,
    '',
    'Tracked Assets:',
    ...summary.trackedAssets.map((asset) => {
      const sign = asset.changePercent >= 0 ? '+' : '';
      return `- ${asset.name} (${asset.symbol}) ${asset.close} (${sign}${asset.changePercent.toFixed(2)}%)`;
    }),
    '',
    'Top Headlines (Market-date first):',
    ...summary.articles.map((article, index) => `${index + 1}. ${article.title} (${article.source}, ${formatArticleTimestamp(article.publishedAt)})`),
  ];

  return lines.join('\n');
}

function buildReportHtml(summary) {
  const cards = summary.trackedAssets.map((asset) => {
    const changeColor = asset.changePercent >= 0 ? '#12b981' : '#ef4444';
    const prefix = asset.changePercent >= 0 ? '+' : '';
    const sparkline = buildSparklineSvg(asset.dailySeries, changeColor, asset.previousClose);

    return `
      <div class="asset-card">
        <div class="asset-top">
          <div>
            <div class="asset-name">${escapeHtml(asset.name)}</div>
            <div class="asset-symbol">${escapeHtml(asset.symbol)}</div>
          </div>
          <div class="asset-price-block">
            <div class="asset-price">${formatPrice(asset.close)}</div>
            <div class="asset-change" style="color:${changeColor}">${prefix}${asset.changePercent.toFixed(2)}%</div>
          </div>
        </div>
        <div class="sparkline-wrap">${sparkline}</div>
        <div class="axis-row">
          <span>오전 9:30</span>
          <span>오후 12:00</span>
          <span>오후 2:30</span>
          <span>오후 4:00</span>
        </div>
      </div>
    `;
  }).join('');

  const news = summary.articles.map((article, index) => `
    <div class="news-item">
      <div class="news-issue-num">${index + 1}</div>
      <div class="news-issue-title">${escapeHtml(article.title)}</div>
      <div class="news-meta">${escapeHtml(article.source)} | ${escapeHtml(formatArticleTimestamp(article.publishedAt))}</div>
      <div class="news-issue-body">${escapeHtml(article.content || article.description || '')}</div>
      ${article.url ? `<div class="news-link"><a href="${escapeHtml(article.url)}" target="_blank" rel="noopener noreferrer">관련 기사 보기 →</a></div>` : ''}
    </div>
  `).join('');

  return `
  <!doctype html>
  <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>BATA Daily Report</title>
      <style>
        :root {
          --bg: #f3f6fb;
          --card: #ffffff;
          --ink: #0f172a;
          --muted: #64748b;
          --line: #e2e8f0;
          --accent: #1d4ed8;
          --up: #12b981;
          --down: #ef4444;
        }
        body {
          margin: 0;
          background:
            radial-gradient(1200px 500px at -20% -10%, #dbeafe 0%, transparent 65%),
            radial-gradient(900px 420px at 120% -20%, #e0e7ff 0%, transparent 62%),
            var(--bg);
          font-family: 'Segoe UI', -apple-system, sans-serif;
          color: var(--ink);
        }
        .container { max-width: 960px; margin: 0 auto; padding: 26px; }
        .header {
          background: linear-gradient(135deg,#0ea5e9,#1d4ed8);
          color:#fff;
          border-radius:18px;
          padding:22px;
          box-shadow: 0 10px 28px rgba(29,78,216,0.24);
        }
        .title { font-size:24px; font-weight:800; margin-bottom:6px; letter-spacing: 0.1px; }
        .sub { font-size:13px; opacity:0.92; }
        .meta-row { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
        .meta-pill {
          display:inline-flex;
          align-items:center;
          padding:6px 10px;
          border-radius:999px;
          background:rgba(255,255,255,0.18);
          border:1px solid rgba(255,255,255,0.28);
          font-size:12px;
          font-weight:600;
        }
        .section { margin-top:18px; }
        .card {
          background: var(--card);
          border-radius:16px;
          padding:16px;
          box-shadow: 0 6px 22px rgba(15,23,42,0.06);
          border: 1px solid rgba(148,163,184,0.18);
        }
        .summary { line-height:1.6; font-size:14px; }
        .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:12px; }
        .asset-card {
          border:1px solid var(--line);
          border-radius:12px;
          padding:12px;
          background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
        }
        .asset-top { display:flex; justify-content:space-between; align-items:flex-start; }
        .asset-name { font-size:15px; font-weight:800; }
        .asset-symbol { font-size:12px; color:var(--muted); margin-top:2px; }
        .asset-price-block { text-align:right; }
        .asset-price { font-size:16px; font-weight:800; letter-spacing: 0.15px; }
        .asset-change { font-size:13px; font-weight:700; margin-top:2px; }
        .sparkline-wrap { margin-top:8px; height:54px; }
        .axis-row {
          margin-top: 4px;
          display: flex;
          justify-content: space-between;
          font-size: 11px;
          color: var(--muted);
          opacity: 0.9;
        }
        .news-item { border-bottom:1px solid #e2e8f0; padding:14px 0; }
        .news-item:last-child { border-bottom:none; }
        .news-issue-num { display:inline-block; background:#1d4ed8; color:#fff; border-radius:50%; width:22px; height:22px; text-align:center; line-height:22px; font-size:11px; font-weight:700; margin-bottom:6px; }
        .news-issue-title { font-size:15px; font-weight:700; color:#0f172a; line-height:1.4; margin-bottom:6px; }
        .news-meta { font-size:12px; color:var(--muted); margin-bottom:6px; }
        .news-issue-body { font-size:13px; color:#334155; line-height:1.65; }
        .news-link { margin-top:6px; font-size:12px; }
        .news-link a { color:#1d4ed8; text-decoration:none; font-weight:600; }
        .news-link a:hover { text-decoration: underline; }
        @media (max-width: 768px) {
          .container { padding: 14px; }
          .grid { grid-template-columns: 1fr; }
        }
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <div class="title">BATA US Market Daily Report</div>
          <div class="sub">미국장 기준일 기사 우선으로 정리한 장마감 리포트</div>
          <div class="meta-row">
            <div class="meta-pill">발송일(KST): ${escapeHtml(summary.deliveryDate)}</div>
            <div class="meta-pill">시장기준일(NY): ${escapeHtml(summary.marketDate)}</div>
            <div class="meta-pill">갱신시각(KST): ${escapeHtml(summary.updatedAtDisplay)}</div>
          </div>
        </div>

        <div class="section card">
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;">마감 요약</div>
          <div class="summary">${escapeHtml(summary.summary)}</div>
        </div>

        <div class="section card">
          <div style="font-size:16px;font-weight:700;margin-bottom:4px;">주요 지수 및 ETF (데일리 5분봉)</div>
          <div class="grid">${cards}</div>
        </div>

        <div class="section card">
          <div style="font-size:16px;font-weight:700;margin-bottom:6px;">시장기준일 우선 핵심 이슈</div>
          ${news}
        </div>
      </div>
    </body>
  </html>
  `;
}

function buildSparklineSvg(series, color, previousClose) {
  const values = Array.isArray(series) && series.length >= 2
    ? series.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0)
    : [1, 1.02, 1.01, 1.03, 1.02, 1.04, 1.05];

  const width = 220;
  const height = 44;
  const padding = 4;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const points = values.map((value, index) => {
    const x = padding + ((width - (padding * 2)) * (index / (values.length - 1)));
    const y = height - padding - (((value - min) / span) * (height - (padding * 2)));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const baseline = Number.isFinite(previousClose) && previousClose > 0 ? previousClose : values[0];
  const baselineY = height - padding - (((baseline - min) / span) * (height - (padding * 2)));
  const safeBaselineY = Math.max(padding, Math.min(height - padding, baselineY));
  const lastX = padding + ((width - (padding * 2)) * ((values.length - 1) / (values.length - 1)));
  const lastY = height - padding - (((values[values.length - 1] - min) / span) * (height - (padding * 2)));

  const area = `${padding},${height - padding} ${points} ${width - padding},${height - padding}`;

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" preserveAspectRatio="none">
    <defs>
      <linearGradient id="grad-${Math.abs(color.split('').reduce((a, c) => a + c.charCodeAt(0), 0))}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.22" />
        <stop offset="100%" stop-color="${color}" stop-opacity="0" />
      </linearGradient>
    </defs>
    <line x1="${padding}" y1="${safeBaselineY.toFixed(1)}" x2="${width - padding}" y2="${safeBaselineY.toFixed(1)}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 3" stroke-opacity="0.85" />
    <polygon points="${area}" fill="url(#grad-${Math.abs(color.split('').reduce((a, c) => a + c.charCodeAt(0), 0))})" />
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="2.8" fill="${color}" stroke="#ffffff" stroke-width="1.2" />
  </svg>`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatPrice(value) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) {
    return '0.00';
  }

  const abs = Math.abs(number);
  if (abs >= 1000) {
    return number.toFixed(2);
  }
  if (abs >= 1) {
    return number.toFixed(2);
  }
  if (abs >= 0.01) {
    return number.toFixed(4);
  }
  return number.toFixed(6);
}

function buildPdfBuffer(summary) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ size: 'A4', margin: 40 });
    const chunks = [];

    doc.on('data', (chunk) => chunks.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);

    doc.fontSize(18).text('BATA US Market Daily Report', { align: 'left' });
    doc.moveDown(0.5);
    doc.fontSize(11).text(`Delivery Date (KST): ${summary.deliveryDate}`);
    doc.text(`Market Date (NY): ${summary.marketDate}`);
    doc.text(`Updated At (KST): ${summary.updatedAtDisplay}`);
    doc.moveDown();

    doc.fontSize(13).text('Market Summary');
    doc.fontSize(11).text(summary.summary);
    doc.moveDown();

    doc.fontSize(13).text('Tracked Assets');
    summary.trackedAssets.forEach((asset) => {
      const sign = asset.changePercent >= 0 ? '+' : '';
      doc
        .fontSize(11)
        .text(`${asset.name} (${asset.symbol})  Close: ${formatPrice(asset.close)}  Change: ${sign}${asset.changePercent.toFixed(2)}%`);
    });

    doc.moveDown();
    doc.fontSize(13).text('Top News');
    summary.articles.forEach((article, index) => {
      doc
        .fontSize(11)
        .text(`${index + 1}. ${article.title}`)
        .fontSize(10)
        .text(`Source: ${article.source} | ${formatArticleTimestamp(article.publishedAt)}`)
        .fillColor('#1a0dab')
        .text(article.url)
        .fillColor('black')
        .moveDown(0.4);
    });

    doc.end();
  });
}

function buildReportContext(summary, referenceDate = new Date()) {
  return {
    ...summary,
    marketDate: summary.date,
    deliveryDate: formatDateInTimezone(referenceDate, DELIVERY_TIMEZONE),
    deliveryTimestamp: formatDateTimeInTimezone(referenceDate, DELIVERY_TIMEZONE),
    updatedAtDisplay: formatDateTimeInTimezone(summary.updatedAt, DELIVERY_TIMEZONE),
  };
}

function formatArticleTimestamp(value) {
  return formatDateTimeInTimezone(value, MARKET_TIMEZONE);
}

function formatDateInTimezone(value, timeZone) {
  const parsed = toValidDate(value);
  if (!parsed) {
    return '';
  }

  return new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(parsed);
}

function formatDateTimeInTimezone(value, timeZone) {
  const parsed = toValidDate(value);
  if (!parsed) {
    return '';
  }

  return new Intl.DateTimeFormat('ko-KR', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(parsed);
}

function toValidDate(value) {
  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
