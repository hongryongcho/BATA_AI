import { Router } from 'express';

import { getDailyMarketSummary } from '../services/marketService.js';

const router = Router();

router.get('/daily-summary', async (req, res) => {
  try {
    const date = req.query.date;
    const summary = await getDailyMarketSummary(date);
    res.json(summary);
  } catch (error) {
    res.status(500).json({
      message: 'Failed to load daily summary',
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
});

export default router;
