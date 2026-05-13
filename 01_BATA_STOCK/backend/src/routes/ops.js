import express from 'express';

import { getOpsDiagnostics } from '../services/opsDiagnostics.js';
import { runAutoReportNow } from '../services/autoReportScheduler.js';

const router = express.Router();

router.get('/diagnostics', async (req, res) => {
  try {
    const diagnostics = await getOpsDiagnostics();
    res.json(diagnostics);
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

router.post('/report/run-now', async (req, res) => {
  try {
    const bodyForce = req.body?.force;
    const queryForce = req.query?.force;
    const force = bodyForce !== undefined ? bodyForce : queryForce;
    const normalizedForce = force === undefined ? true : String(force) !== 'false';
    const result = await runAutoReportNow({ force: normalizedForce });

    res.status(result.ok ? (result.skipped ? 202 : 200) : 500).json(result);
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

export default router;