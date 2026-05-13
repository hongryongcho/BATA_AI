import 'dotenv/config';
import cors from 'cors';
import express from 'express';

import marketRouter from './routes/market.js';
import opsRouter from './routes/ops.js';
import reportRouter from './routes/report.js';
import { startAutoReportScheduler } from './services/autoReportScheduler.js';
import { startPriceAlertMonitor } from './services/priceAlertService.js';

const app = express();
const port = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'bata-stock-backend' });
});

app.use('/api/market', marketRouter);
app.use('/api/ops', opsRouter);
app.use('/api/report', reportRouter);

app.listen(port, () => {
  console.log(`BATA backend listening on port ${port}`);
  startAutoReportScheduler();
  startPriceAlertMonitor();
});
