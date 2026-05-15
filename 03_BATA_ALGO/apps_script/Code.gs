const SHEET_SUMMARY = 'Summary';
const SHEET_BACKTEST = 'BackTest';
const HEADER_ROW = 12;
const DATA_START_ROW = HEADER_ROW + 1;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('BackTest3x')
    .addItem('초기 템플릿 생성', 'setupWorkbook')
    .addItem('백테스트 실행', 'runBacktestNow')
    .addItem('Summary 디자인 적용', 'applySummaryDesign')
    .addItem('자동실행 트리거 설치', 'installOnEditTrigger')
    .addToUi();
}

function setupWorkbook() {
  const ss = SpreadsheetApp.getActive();
  const summary = ensureSheet_(ss, SHEET_SUMMARY);
  const back = ensureSheet_(ss, SHEET_BACKTEST);

  createSummaryTemplate_(summary);
  initializeBackTestSheet_(back);
  applySummaryDesign();

  SpreadsheetApp.getActive().toast('초기 템플릿 생성 완료', 'BackTest3x', 5);
}

function onEdit(e) {
  if (!e || !e.range) return;
  const sh = e.range.getSheet();
  if (sh.getName() !== SHEET_SUMMARY) return;
  const row = e.range.getRow();
  const col = e.range.getColumn();
  // B2:B15 변경 시 자동 실행
  if (col === 2 && row >= 2 && row <= 15) {
    runBacktestNow();
  }
}

function installOnEditTrigger() {
  const ss = SpreadsheetApp.getActive();
  const triggers = ScriptApp.getProjectTriggers();
  for (const t of triggers) {
    if (t.getHandlerFunction() === 'onEdit') {
      ScriptApp.deleteTrigger(t);
    }
  }
  ScriptApp.newTrigger('onEdit').forSpreadsheet(ss).onEdit().create();
  SpreadsheetApp.getActive().toast('onEdit 트리거 설치 완료', 'BackTest3x', 5);
}

function runBacktestNow() {
  const ss = SpreadsheetApp.getActive();
  const summary = ensureSheet_(ss, SHEET_SUMMARY);
  const back = ensureSheet_(ss, SHEET_BACKTEST);

  // Summary 템플릿이 없으면 자동 초기화
  if (!summary.getRange('A1').getValue()) {
    createSummaryTemplate_(summary);
  }

  const p = readParams(summary);
  applySummaryDesign();

  const prices = fetchCloseSeriesByGoogleFinance_(p.ticker, p.startDate, p.endDate);
  if (prices.length === 0) throw new Error('가격 데이터를 불러오지 못했습니다. 티커/기간을 확인하세요.');

  const result = runAlgorithm_(p, prices);
  const bench = calcSpyBenchmark_(p.initialCapital, p.startDate, p.endDate);

  const totalReturn = result.summary.totalReturnPct;
  const spyReturn = bench.returnPct;
  const alpha = totalReturn - spyReturn;

  const summaryPayload = {
    ticker: p.ticker,
    startDate: p.startDate,
    endDate: p.endDate,
    finalAssets: result.summary.finalAssets,
    totalReturnPct: totalReturn,
    cagrPct: result.summary.cagrPct,
    mddPct: result.summary.mddPct,
    spyReturnPct: spyReturn,
    alphaVsSpyPct: alpha,
  };

  writeBackTest_(back, result.rows, summaryPayload);
  writeSummaryDashboard_(summary, summaryPayload);

  SpreadsheetApp.getActive().toast('백테스트 완료', 'BackTest3x', 5);
}

function readParams(summary) {
  const ticker = String(summary.getRange('B2').getValue() || '').trim().toUpperCase();
  if (!ticker) throw new Error('Summary B2 티커가 비어있습니다.');

  const initialCapital = Number(summary.getRange('B3').getValue() || 100000);
  const nSplits = Number(summary.getRange('B4').getValue() || 40);
  const startDate = toDateStr_(summary.getRange('B5').getValue() || '2022-01-01');
  const endRaw = summary.getRange('B6').getValue();
  const endDate = endRaw ? toDateStr_(endRaw) : toDateStr_(new Date());

  const baseProfitPct = Number(summary.getRange('B7').getValue() || 3);
  const buy1 = Number(summary.getRange('B8').getValue() || 10);
  const buy2 = Number(summary.getRange('B9').getValue() || 15);
  const buy3 = Number(summary.getRange('B10').getValue() || 20);
  const sell1 = Number(summary.getRange('B11').getValue() || 10);
  const sell2 = Number(summary.getRange('B12').getValue() || 20);
  const sell3 = Number(summary.getRange('B13').getValue() || 30);
  const gapUpPct = Number(summary.getRange('B14').getValue() || 2);

  const is3xRaw = summary.getRange('B15').getValue();
  const is3x = isTruthy_(is3xRaw) || is3xTicker_(ticker);
  const k = is3x ? 3 : 1;

  return {
    ticker,
    initialCapital,
    nSplits,
    startDate,
    endDate,
    is3x,
    baseProfitPct: baseProfitPct * k,
    buyThresholds: [buy1 * k, buy2 * k, buy3 * k],
    sellThresholds: [sell1 * k, sell2 * k, sell3 * k],
    gapUpPct: gapUpPct * k,
  };
}

function fetchCloseSeriesByGoogleFinance_(ticker, startDate, endDate) {
  const ss = SpreadsheetApp.getActive();
  const tempName = '__BT_TEMP__';
  let ws = ss.getSheetByName(tempName);
  if (!ws) ws = ss.insertSheet(tempName);
  ws.clear();
  ws.hideSheet();

  const formula = '=QUERY(GOOGLEFINANCE("' + ticker + '","close",DATEVALUE("' + startDate + '"),DATEVALUE("' + endDate + '"),"DAILY"),"select Col1,Col2 offset 1",0)';
  ws.getRange('A1').setFormula(formula);

  SpreadsheetApp.flush();
  Utilities.sleep(1500);
  SpreadsheetApp.flush();

  const lastRow = ws.getLastRow();
  if (lastRow < 1) return [];

  const values = ws.getRange(1, 1, lastRow, 2).getValues();
  const out = [];
  for (const r of values) {
    const d = r[0];
    const c = Number(r[1]);
    if (!(d instanceof Date) || !isFinite(c) || c <= 0) continue;
    out.push({ date: new Date(d), close: c });
  }
  return out;
}

function runAlgorithm_(p, prices) {
  const closes = prices.map(x => x.close);
  const highs = rollingMax_(closes, 252);

  let cash = p.initialCapital;
  let shares = 0;
  let avgCost = 0;
  let unitQty = 0;
  let cycle = 1;

  const rows = [];

  for (let i = 0; i < prices.length; i++) {
    const date = prices[i].date;
    const close = prices[i].close;
    const prev = i > 0 ? prices[i - 1].close : close;
    const high52 = highs[i];

    const drawdownPct = high52 > 0 ? (close / high52 - 1) * 100 : 0;
    const profitPct = (shares > 0 && avgCost > 0) ? (close / avgCost - 1) * 100 : 0;
    const gapUpPctToday = (close / prev - 1) * 100;

    if (unitQty === 0 && shares === 0) {
      unitQty = Math.max(1, Math.floor(cash / p.nSplits / close));
    }

    let action = 'HOLD';
    let qty = 0;
    let amount = 0;
    let memo = '';

    if (shares > 0 && gapUpPctToday >= p.gapUpPct) {
      qty = Math.min(unitQty, shares);
      cash += qty * close;
      shares -= qty;
      action = 'SELL';
      amount = qty * close;
      memo = '갭업강제매도';
      if (shares === 0) {
        avgCost = 0;
        cycle += 1;
        unitQty = 0;
      }
    } else if (shares === 0) {
      qty = unitQty;
      const cost = qty * close;
      if (cash >= cost) {
        cash -= cost;
        shares += qty;
        avgCost = close;
        action = 'BUY';
        amount = cost;
        memo = '신규진입';
      } else {
        action = 'SKIP';
        memo = '현금부족';
      }
    } else if (profitPct >= p.baseProfitPct) {
      qty = Math.min(unitQty * sellMultiplier_(profitPct, p.sellThresholds), shares);
      cash += qty * close;
      shares -= qty;
      action = 'SELL';
      amount = qty * close;
      if (shares === 0) {
        avgCost = 0;
        cycle += 1;
        unitQty = 0;
      }
    } else {
      qty = unitQty * buyMultiplier_(drawdownPct, p.buyThresholds);
      const cost = qty * close;
      if (cash >= cost) {
        avgCost = weightedAvg_(avgCost, shares, close, qty);
        cash -= cost;
        shares += qty;
        action = 'BUY';
        amount = cost;
      } else {
        action = 'SKIP';
        memo = '현금부족';
      }
    }

    const portfolio = shares * close;
    const totalAssets = cash + portfolio;
    const retPct = (totalAssets / p.initialCapital - 1) * 100;

    rows.push([
      date,
      round4_(close),
      round4_(high52),
      round2_(drawdownPct),
      shares > 0 ? round4_(avgCost) : 0,
      shares > 0 ? round2_(profitPct) : 0,
      50,
      action,
      qty,
      round2_(amount),
      shares,
      round2_(cash),
      round2_(portfolio),
      round2_(totalAssets),
      round2_(retPct),
      cycle,
      memo,
    ]);
  }

  const finalAssets = rows[rows.length - 1][13];
  const totalReturnPct = (finalAssets / p.initialCapital - 1) * 100;
  const mddPct = calcMddPct_(rows.map(r => Number(r[13])));
  const cagrPct = calcCagrPct_(p.startDate, p.endDate, p.initialCapital, finalAssets);

  return {
    rows,
    summary: {
      finalAssets: round2_(finalAssets),
      totalReturnPct: round2_(totalReturnPct),
      mddPct: round2_(mddPct),
      cagrPct: round2_(cagrPct),
    },
  };
}

function calcSpyBenchmark_(initialCapital, startDate, endDate) {
  const spy = fetchCloseSeriesByGoogleFinance_('SPY', startDate, endDate);
  if (!spy.length) return { returnPct: 0 };
  const first = spy[0].close;
  const last = spy[spy.length - 1].close;
  const shares = Math.floor(initialCapital / first);
  const cash = initialCapital - shares * first;
  const finalAssets = cash + shares * last;
  return { returnPct: round2_((finalAssets / initialCapital - 1) * 100) };
}

function writeBackTest_(ws, rows, s) {
  ws.clear();

  const top = [
    ['BackTest 통합 결과', ''],
    ['생성시간', new Date()],
    ['티커', s.ticker],
    ['시작일', s.startDate],
    ['종료일', s.endDate],
    ['최종수익률(%)', s.totalReturnPct],
    ['SPY수익률(%)', s.spyReturnPct],
    ['SPY대비초과수익(%)', s.alphaVsSpyPct],
    ['CAGR(%)', s.cagrPct],
    ['MDD(%)', s.mddPct],
  ];
  ws.getRange(1, 1, top.length, 2).setValues(top);

  const headers = [[
    '날짜','종가','52주전고점','전고점낙폭(%)','평단가','평단대비수익률(%)','Fear&Greed',
    '매매구분','거래수량','거래금액','보유주식수','현금잔고','평가금액','총자산','수익률(%)','사이클','메모'
  ]];
  ws.getRange(HEADER_ROW, 1, 1, 17).setValues(headers);

  if (rows.length > 0) {
    ws.getRange(DATA_START_ROW, 1, rows.length, 17).setValues(rows);
  }

  ws.getRange('A1:B1').setBackground('#19324d').setFontColor('white').setFontWeight('bold');
  ws.getRange('A2:A10').setFontWeight('bold');
  ws.getRange(HEADER_ROW, 1, 1, 17).setBackground('#eaf2ff').setFontWeight('bold');
}

function writeSummaryDashboard_(ws, s) {
  const rows = [
    ['백테스트 결과 (강조형)', '값', ''],
    ['티커', s.ticker, ''],
    ['시작일', s.startDate, ''],
    ['종료일', s.endDate, ''],
    ['최종총자산', s.finalAssets, ''],
    ['최종 수익률(%)', s.totalReturnPct, ''],
    ['SPY 수익률(%)', s.spyReturnPct, ''],
    ['SPY 대비 초과수익(%)', s.alphaVsSpyPct, ''],
    ['CAGR(%)', s.cagrPct, ''],
    ['MDD(%)', s.mddPct, ''],
    ['', '', ''],
    ['시작일~종료일 누적 총자산 그래프', '', ''],
    ['', '=SPARKLINE(BackTest!N' + DATA_START_ROW + ':N,{"charttype","line";"color","#0b57d0";"linewidth",3})', ''],
  ];
  ws.getRange(1, 4, rows.length, 3).setValues(rows);
  ws.getRange('D1:F1').setBackground('#0d1a33').setFontColor('white').setFontWeight('bold');
  ws.getRange('D2:D10').setFontWeight('bold');
  ws.getRange('E5:E10').setNumberFormat('0.00');
  ws.getRange('E5:E8').setBackground('#eff6ff').setFontWeight('bold');
}

function applySummaryDesign() {
  const ss = SpreadsheetApp.getActive();
  const ws = ss.getSheetByName(SHEET_SUMMARY);
  if (!ws) return;

  ws.getRange('A1:B1').setBackground('#1f5b42').setFontColor('white').setFontWeight('bold').setFontSize(14);
  ws.getRange('A2:B2').setBackground('#edf7ef').setFontWeight('bold');
  ws.getRange('A3:A15').setFontWeight('bold');
  ws.getRange('B2:B15').setBackground('#fff7d6').setFontWeight('bold');

  const algo = [
    ['Algorithm', '규칙 설명'],
    ['기본매매', '보유 0주면 1회매수, 아니면 평단기준 수익률로 매수/매도'],
    ['매수배수', '52주 전고점 대비 낙폭 기준 (1x:10/15/20, 3x:30/45/60)'],
    ['매도배수', '평단 대비 수익률 기준 (1x:10/20/30, 3x:30/60/90)'],
    ['갭업조건', '1x +2%, 3x +6% 이상 시 1회 강제매도'],
    ['Fear&Greed', 'Extreme Fear=매수만, Extreme Greed=매도만'],
    ['사이클리셋', '전량청산 후 총자산/N으로 unit 재계산'],
    ['자동실행', 'B2:B15 변경 시 자동 재실행'],
  ];
  ws.getRange(15, 4, algo.length, 2).setValues(algo);
  ws.getRange('D15:E15').setBackground('#5a256b').setFontColor('white').setFontWeight('bold');
  ws.getRange('D16:D22').setFontWeight('bold');
}

function createSummaryTemplate_(ws) {
  ws.clear();
  const rows = [
    ['BATA 투자 알고리즘 파라미터 (Summary)', ''],
    ['대상 자산 티커', 'SPY'],
    ['초기자본 (USD)', 100000],
    ['등분수(N)', 40],
    ['백테스트 시작일', '2022-01-01'],
    ['백테스트 종료일 (빈칸=오늘)', ''],
    ['기본수익기준(%)', 3],
    ['매수2배수낙폭(%)', 10],
    ['매수3배수낙폭(%)', 15],
    ['매수4배수낙폭(%)', 20],
    ['매도2배수수익(%)', 10],
    ['매도3배수수익(%)', 20],
    ['매도4배수수익(%)', 30],
    ['갭업강제매도기준(%)', 2],
    ['3배수ETF여부(TRUE/FALSE)', 'FALSE'],
    ['실시간 현재가(GOOGLEFINANCE)', '=IF(B2="","",INDEX(GOOGLEFINANCE(B2,"price"),2,2))'],
    ['전일 종가(GOOGLEFINANCE)', '=IF(B2="","",INDEX(GOOGLEFINANCE(B2,"closeyest"),2,2))'],
    ['당일 변동률(%)', '=IFERROR((B16/B17-1)*100,)'],
  ];

  ws.getRange(1, 1, rows.length, 2).setValues(rows);
  ws.getRange('B18').setNumberFormat('0.00');
}

function initializeBackTestSheet_(ws) {
  ws.clear();
  const top = [
    ['BackTest 통합 결과', ''],
    ['생성시간', new Date()],
    ['티커', ''],
    ['시작일', ''],
    ['종료일', ''],
    ['최종수익률(%)', ''],
    ['SPY수익률(%)', ''],
    ['SPY대비초과수익(%)', ''],
    ['CAGR(%)', ''],
    ['MDD(%)', ''],
  ];
  ws.getRange(1, 1, top.length, 2).setValues(top);

  const headers = [[
    '날짜','종가','52주전고점','전고점낙폭(%)','평단가','평단대비수익률(%)','Fear&Greed',
    '매매구분','거래수량','거래금액','보유주식수','현금잔고','평가금액','총자산','수익률(%)','사이클','메모'
  ]];
  ws.getRange(HEADER_ROW, 1, 1, 17).setValues(headers);
  ws.getRange('A1:B1').setBackground('#19324d').setFontColor('white').setFontWeight('bold');
  ws.getRange('A2:A10').setFontWeight('bold');
  ws.getRange(HEADER_ROW, 1, 1, 17).setBackground('#eaf2ff').setFontWeight('bold');
}

function ensureSheet_(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function buyMultiplier_(drawdownPct, t) {
  const drop = Math.abs(drawdownPct);
  if (drop >= t[2]) return 4;
  if (drop >= t[1]) return 3;
  if (drop >= t[0]) return 2;
  return 1;
}

function sellMultiplier_(profitPct, t) {
  if (profitPct >= t[2]) return 4;
  if (profitPct >= t[1]) return 3;
  if (profitPct >= t[0]) return 2;
  return 1;
}

function rollingMax_(arr, windowSize) {
  const out = [];
  for (let i = 0; i < arr.length; i++) {
    const start = Math.max(0, i - windowSize + 1);
    let m = -Infinity;
    for (let j = start; j <= i; j++) m = Math.max(m, arr[j]);
    out.push(m);
  }
  return out;
}

function weightedAvg_(prevAvg, prevQty, price, qty) {
  if (prevQty === 0) return price;
  return (prevAvg * prevQty + price * qty) / (prevQty + qty);
}

function calcMddPct_(assets) {
  let peak = assets[0] || 0;
  let mdd = 0;
  for (const a of assets) {
    if (a > peak) peak = a;
    if (peak > 0) {
      const dd = (a / peak - 1) * 100;
      if (dd < mdd) mdd = dd;
    }
  }
  return mdd;
}

function calcCagrPct_(startDateStr, endDateStr, initialCapital, finalAssets) {
  const s = new Date(startDateStr);
  const e = new Date(endDateStr);
  const days = Math.max(1, (e - s) / (1000 * 60 * 60 * 24));
  const years = days / 365.25;
  if (initialCapital <= 0 || finalAssets <= 0 || years <= 0) return 0;
  return (Math.pow(finalAssets / initialCapital, 1 / years) - 1) * 100;
}

function isTruthy_(v) {
  const s = String(v).trim().toLowerCase();
  return s === 'true' || s === '1' || s === 'yes' || s === 'y';
}

function is3xTicker_(ticker) {
  const set = new Set(['SPXL', 'UPRO', 'TQQQ', 'SOXL', 'TECL', 'FNGU', 'LABU', 'CURE', 'DFEN', 'NAIL', 'WANT', 'WEBL', 'HIBL']);
  return set.has(String(ticker || '').toUpperCase());
}

function toDateStr_(v) {
  const d = (v instanceof Date) ? v : new Date(v);
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}

function round2_(n) { return Math.round((Number(n) + Number.EPSILON) * 100) / 100; }
function round4_(n) { return Math.round((Number(n) + Number.EPSILON) * 10000) / 10000; }
