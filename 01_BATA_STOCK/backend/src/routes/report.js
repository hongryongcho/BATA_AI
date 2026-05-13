import { Router } from 'express';

import { getDailyMarketSummary } from '../services/marketService.js';
import {
  addRecipient,
  buildReportPreviewHtml,
  getRecipients,
  removeRecipient,
  sendDailySummaryReport,
} from '../services/reportService.js';
import { sendDailyTelegramCloseReport } from '../services/telegramReportService.js';

const router = Router();

router.get('/recipients', async (req, res) => {
  try {
    const recipients = await getRecipients();
    res.json({ recipients });
  } catch (error) {
    res.status(500).json({
      message: 'Failed to load recipients',
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
});

router.post('/recipients', async (req, res) => {
  try {
    const email = req.body?.email;
    const recipients = await addRecipient(email);
    res.status(201).json({ recipients });
  } catch (error) {
    res.status(400).json({
      message: 'Failed to add recipient',
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
});

router.delete('/recipients', async (req, res) => {
  try {
    const email = req.body?.email;
    const recipients = await removeRecipient(email);
    res.json({ recipients });
  } catch (error) {
    res.status(400).json({
      message: 'Failed to remove recipient',
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
});

router.post('/send-daily', async (req, res) => {
  try {
    if (String(process.env.EMAIL_SEND_ENABLED || 'false') !== 'true') {
      res.status(403).json({
        message: 'Email sending is disabled during development',
      });
      return;
    }

    const date = req.body?.date;
    const summary = await getDailyMarketSummary(date);
    const result = await sendDailySummaryReport(summary);
    res.json(result);
  } catch (error) {
    res.status(500).json({
      message: 'Failed to send daily report email',
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
});

router.get('/preview', async (req, res) => {
  try {
    const date = req.query.date;
    const summary = await getDailyMarketSummary(date);
    const html = buildReportPreviewHtml(summary);
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.send(html);
  } catch (error) {
    res.status(500).send(
      `<pre>Failed to render preview: ${error instanceof Error ? error.message : 'Unknown error'}</pre>`,
    );
  }
});

router.post('/telegram/send-close', async (req, res) => {
  try {
    const date = req.body?.date;
    const result = await sendDailyTelegramCloseReport(date);
    res.json(result);
  } catch (error) {
    res.status(500).json({
      message: 'Failed to send telegram close report',
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
});

export default router;
