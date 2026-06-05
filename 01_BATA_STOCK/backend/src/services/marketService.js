import { readJsonCache, writeJsonCache } from '../utils/fileCache.js';

const CACHE_VERSION = 'v7';

const MARKET_TIMEZONE = 'America/New_York';

const trackedAssets = [
  { symbol: '^IXIC', fetchSymbol: 'QQQ', yahooSymbol: 'QQQ', name: 'NASDAQ', kind: 'index' },
  { symbol: '^GSPC', fetchSymbol: 'SPY', yahooSymbol: 'SPY', name: 'S&P 500', kind: 'index' },
  { symbol: '^DJI', fetchSymbol: 'DIA', yahooSymbol: 'DIA', name: 'Dow Jones', kind: 'index' },
  { symbol: 'TQQQ', fetchSymbol: 'TQQQ', yahooSymbol: 'TQQQ', name: 'TQQQ', kind: 'etf' },
  { symbol: 'SOXL', fetchSymbol: 'SOXL', yahooSymbol: 'SOXL', name: 'SOXL', kind: 'etf' },
  { symbol: 'TMF', fetchSymbol: 'TMF', yahooSymbol: 'TMF', name: 'TMF 20Y Treasury 3x', kind: 'bond' },
  { symbol: 'BTCUSD', fetchSymbol: 'BINANCE:BTCUSDT', yahooSymbol: 'BTC-USD', name: 'Bitcoin', kind: 'crypto' },
  { symbol: 'ETHUSD', fetchSymbol: 'BINANCE:ETHUSDT', yahooSymbol: 'ETH-USD', name: 'Ethereum', kind: 'crypto' },
  { symbol: 'USO', fetchSymbol: 'USO', yahooSymbol: 'USO', name: 'US Oil Fund', kind: 'oil' },
  {
    symbol: 'USD/KRW',
    fetchSymbol: 'OANDA:USD_KRW',
    quoteSymbol: 'OANDA:USD_KRW',
    yahooSymbol: 'KRW=X',
    name: '원/달러 (1달러당 원화)',
    kind: 'fx',
  },
  {
    symbol: 'DXY',
    fetchSymbol: 'DXY',
    quoteSymbol: 'DXY',
    yahooSymbol: 'DX-Y.NYB',
    name: 'US Dollar Index (DXY)',
    kind: 'dollar-index',
  },
];

const newsSymbols = ['AAPL', 'MSFT', 'NVDA', 'QQQ', 'SPY', 'BTCUSDT', 'USO', 'TMF'];
const finnhubBaseUrl = 'https://finnhub.io/api/v1';
const newsApiBaseUrl = 'https://newsapi.org/v2/everything';

export async function getDailyMarketSummary(date, skipNewsCache = false) {
  const targetDate = normalizeDate(date);
  const cacheKey = `daily-summary-${CACHE_VERSION}-${targetDate}`;
  const cached = await readJsonCache(cacheKey);
  const hasLiveKeys = Boolean(process.env.FINNHUB_API_KEY || process.env.NEWS_API_KEY);

  // 뉴스는 항상 새로 가져오기 (캐시 무시)
  try {
    const [trackedAssetsResult, newsArticles] = await Promise.all([
      // 마켓 데이터는 캐시 사용 가능
      loadTrackedAssets(targetDate),
      // 뉴스는 항상 새로 가져오기
      loadNewsArticles(targetDate),
    ]);

    const nasdaqAnalysis = await generateNasdaqAnalysis(trackedAssetsResult, newsArticles);

    const payload = {
      date: targetDate,
      updatedAt: new Date().toISOString(),
      summary: buildSummary(trackedAssetsResult, newsArticles),
      nasdaqAnalysis,
      headlines: newsArticles.map((article) => article.title),
      articles: newsArticles,
      trackedAssets: trackedAssetsResult,
      offlineSupported: true,
    };

    await writeJsonCache(cacheKey, payload);
    return payload;
  } catch (error) {
    console.error('[marketService] getDailyMarketSummary error:', error.message);
    if (cached) {
      return {
        ...cached,
        isCached: true,
        offlineSupported: true,
      };
    }

    return buildFallbackPayload(targetDate, error);
  }
}

function normalizeDate(dateText) {
  if (!dateText) {
    return new Date().toISOString().slice(0, 10);
  }

  const parsed = new Date(dateText);
  if (Number.isNaN(parsed.getTime())) {
    return new Date().toISOString().slice(0, 10);
  }

  return parsed.toISOString().slice(0, 10);
}

async function loadTrackedAssets(targetDate) {
  const finnhubToken = process.env.FINNHUB_API_KEY;

  if (!finnhubToken) {
    return trackedAssets.map((asset, index) => {
      const fallback = buildAssetFallbackQuote(asset, index, 0.5, 0.4);
      return {
        symbol: asset.symbol,
        name: asset.name,
        kind: asset.kind,
        close: fallback.close,
        previousClose: fallback.previousClose,
        changePercent: fallback.changePercent,
        changeAmount: fallback.changeAmount,
        dailySeries: buildFallbackDailySeries(fallback.close, fallback.changePercent),
        strategyHint: buildStrategyHint(fallback.changePercent),
      };
    });
  }

  const results = await Promise.all(
    trackedAssets.map(async (asset, index) => {
      try {
        const quoteSymbol = asset.quoteSymbol ?? asset.fetchSymbol;
        let closeRaw = 0;
        let previousRaw = 0;

        try {
          const quote = await fetchJson(
            `${finnhubBaseUrl}/quote?symbol=${encodeURIComponent(quoteSymbol)}&token=${finnhubToken}`,
          );
          closeRaw = Number(quote.c ?? 0);
          previousRaw = Number(quote.pc ?? 0);
        } catch {
          // 일부 자산(환율/지수)은 quote 엔드포인트가 제한될 수 있어 시계열로 보완
        }

        const dailySeries = await loadDailySeries(asset, targetDate, finnhubToken);

        const defaultQuote = buildAssetFallbackQuote(asset, index, 0.5, 0.4);
        const seriesClose = dailySeries.length > 0 ? dailySeries[dailySeries.length - 1] : 0;
        const seriesPrevious = dailySeries.length > 1 ? dailySeries[0] : 0;

        const normalized = normalizeAssetValues(
          asset,
          closeRaw > 0 ? closeRaw : (seriesClose > 0 ? seriesClose : defaultQuote.close),
          previousRaw > 0
            ? previousRaw
            : (seriesPrevious > 0 ? seriesPrevious : (closeRaw > 0 ? closeRaw * 0.995 : defaultQuote.previousClose)),
          dailySeries,
        );

        const close = roundMarketValue(normalized.close);
        const previousClose = roundMarketValue(normalized.previousClose);
        const changeAmount = roundMarketValue(close - previousClose);
        const changePercent = previousClose === 0
          ? 0
          : Number((((close - previousClose) / previousClose) * 100).toFixed(2));

        return {
          symbol: asset.symbol,
          name: asset.name,
          kind: asset.kind,
          close,
          previousClose,
          changeAmount,
          changePercent,
          dailySeries: normalized.series.length >= 2
            ? normalized.series.map((value) => roundMarketValue(value))
            : buildFallbackDailySeries(close, changePercent),
          strategyHint: buildStrategyHint(changePercent),
        };
      } catch {
        // 개별 자산 조회 실패 시 폴백 데이터 반환
        const fallback = buildAssetFallbackQuote(asset, index, 0.5, 0.4);
        return {
          symbol: asset.symbol,
          name: asset.name,
          kind: asset.kind,
          close: fallback.close,
          previousClose: fallback.previousClose,
          changeAmount: fallback.changeAmount,
          changePercent: fallback.changePercent,
          dailySeries: buildFallbackDailySeries(fallback.close, fallback.changePercent),
          strategyHint: buildStrategyHint(fallback.changePercent),
        };
      }
    }),
  );

  return results;
}

async function loadDailySeries(asset, targetDate, finnhubToken) {
  const symbol = asset.fetchSymbol;
  // 5분봉 우선, 불가 시 30분봉/60분봉 순서로 폴백
  // 대상 날짜 당일 데이터가 비어 있으면 최근 거래일을 역방향 탐색
  const targetEndTs = Math.floor(new Date(`${targetDate}T23:59:59Z`).getTime() / 1000);
  const nowTs = Math.floor(Date.now() / 1000);
  const baseEndTs = Math.min(targetEndTs, nowTs);

  const resolutions = ['5', '30', '60'];

  try {
    // Yahoo 5분봉 우선 사용
    const yahooSeries = await loadYahooIntradaySeries(asset.yahooSymbol);
    if (yahooSeries.length >= 10) {
      return yahooSeries;
    }

    for (let dayOffset = 0; dayOffset <= 5; dayOffset += 1) {
      const endTs = baseEndTs - (dayOffset * 24 * 60 * 60);
      const fromTs = endTs - (24 * 60 * 60);

      for (const resolution of resolutions) {
        const candle = await fetchJson(
          `${finnhubBaseUrl}/stock/candle?symbol=${encodeURIComponent(symbol)}&resolution=${resolution}&from=${fromTs}&to=${endTs}&token=${finnhubToken}`,
        );

        if (candle?.s === 'ok' && Array.isArray(candle?.c) && candle.c.length >= 10) {
          return candle.c
            .map((v) => Number(v))
            .filter((v) => Number.isFinite(v) && v > 0)
            .map((v) => Number(v.toFixed(6)));
        }
      }
    }

    // 인트라데이 없으면 일봉 7개 폴백
    const fallbackFrom = baseEndTs - (7 * 24 * 60 * 60);
    const daily = await fetchJson(
      `${finnhubBaseUrl}/stock/candle?symbol=${encodeURIComponent(symbol)}&resolution=D&from=${fallbackFrom}&to=${baseEndTs}&token=${finnhubToken}`,
    );
    if (daily?.s !== 'ok' || !Array.isArray(daily?.c)) return [];
    return daily.c
      .map((v) => Number(v))
      .filter((v) => Number.isFinite(v) && v > 0)
      .slice(-7)
      .map((v) => Number(v.toFixed(2)));
  } catch {
    return [];
  }
}

async function loadYahooIntradaySeries(yahooSymbol) {
  if (!yahooSymbol) {
    return [];
  }

  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahooSymbol)}?interval=5m&range=1d`;
    const payload = await fetchJson(url);
    const closes = payload?.chart?.result?.[0]?.indicators?.quote?.[0]?.close;
    if (!Array.isArray(closes) || closes.length < 2) {
      return [];
    }

    return closes
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0)
      .map((value) => Number(value.toFixed(6)));
  } catch {
    return [];
  }
}

function normalizeAssetValues(asset, close, previousClose, series) {
  return {
    close,
    previousClose,
    series,
  };
}

function roundMarketValue(value) {
  if (!Number.isFinite(value)) return 0;
  const abs = Math.abs(value);
  if (abs >= 100) return Number(value.toFixed(2));
  if (abs >= 1) return Number(value.toFixed(4));
  return Number(value.toFixed(6));
}

// ─── 주간 이슈 테마 정의 ────────────────────────────────────────────────────
const ISSUE_THEMES = [
  {
    key: 'fed',
    title: '연준 · 금리 · 인플레이션',
    keywords: ['fed', 'federal reserve', 'rate', 'interest rate', 'inflation', 'cpi', 'pce',
      'treasury', 'yield', 'fomc', 'powell', 'monetary', 'taper', 'rate cut', 'rate hike', 'hawkish', 'dovish'],
  },
  {
    key: 'tech',
    title: '기술주 · AI · 반도체',
    keywords: ['nvidia', 'artificial intelligence', ' ai ', 'semiconductor', 'chip', 'apple',
      'microsoft', 'google', 'meta', 'amazon', 'tech stock', 'technology', 'qqq', 'soxl', 'tsmc', 'openai'],
  },
  {
    key: 'market',
    title: '시장 전반 · 지수 흐름',
    keywords: ['s&p 500', 's&p500', 'dow jones', 'wall street', 'market rally', 'stock market',
      'equities', 'earnings', 'bull market', 'bear market', 'correction', 'vix', 'volatility',
      'tariff', 'trade war', 'sell-off', 'selloff'],
  },
  {
    key: 'crypto',
    title: '코인 · 디지털 자산',
    keywords: ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'cryptocurrency',
      'blockchain', 'digital asset', 'defi', 'binance', 'coinbase', 'altcoin'],
  },
  {
    key: 'macro',
    title: '원유 · 달러 · 글로벌 경제',
    keywords: ['oil', 'crude', 'energy', 'opec', 'dollar index', 'usd dollar', 'currency',
      'exchange rate', 'trade deficit', 'china economy', 'gdp', 'recession', 'global economy'],
  },
];

async function loadNewsArticles(targetDate) {
  const newsApiKey = process.env.NEWS_API_KEY;
  const finnhubToken = process.env.FINNHUB_API_KEY;

  let rawArticles = [];
  let newsApiError = null;
  let finnhubNewsError = null;

  if (newsApiKey) {
    const query = encodeURIComponent(
      '"stock market" OR "S&P 500" OR Nasdaq OR "Dow Jones" OR ETF OR semiconductor OR "Federal Reserve" OR bitcoin OR "oil price"',
    );
    const domains = encodeURIComponent(
      'reuters.com,bloomberg.com,cnbc.com,wsj.com,marketwatch.com,finance.yahoo.com',
    );

    // 날짜 필터로 먼저 시도, 없으면 최신 기사로 폴백
    const dateUrl = `${newsApiBaseUrl}?q=${query}&searchIn=title,description&domains=${domains}&from=${targetDate}&to=${targetDate}&language=en&sortBy=relevancy&pageSize=30&apiKey=${newsApiKey}`;
    const latestUrl = `${newsApiBaseUrl}?q=${query}&searchIn=title,description&domains=${domains}&language=en&sortBy=publishedAt&pageSize=30&apiKey=${newsApiKey}`;

    try {
      const response = await fetchJson(dateUrl, { headers: { 'X-Api-Key': newsApiKey } });

      rawArticles = filterArticlesByMarketDate(
        (response.articles ?? []).map((a) => ({
          title: a.title ?? '',
          description: a.description ?? '',
          content: a.content ?? '',
          source: a.source?.name ?? 'NewsAPI',
          publishedAt: a.publishedAt,
          url: a.url,
        })),
        targetDate,
      );

      if (rawArticles.length < 5) {
        const latestResponse = await fetchJson(latestUrl, { headers: { 'X-Api-Key': newsApiKey } });
        const latestArticles = filterArticlesByMarketDate(
          (latestResponse.articles ?? []).map((a) => ({
            title: a.title ?? '',
            description: a.description ?? '',
            content: a.content ?? '',
            source: a.source?.name ?? 'NewsAPI',
            publishedAt: a.publishedAt,
            url: a.url,
          })),
          targetDate,
        );

        rawArticles = dedupeArticles([...rawArticles, ...latestArticles]);
      }
    } catch (error) {
      newsApiError = error instanceof Error ? error.message : String(error);
      console.warn(`[marketService] NewsAPI fetch failed: ${newsApiError}`);
    }
  }

  if (rawArticles.length === 0 && finnhubToken) {
    try {
      const responseSets = await Promise.all(
        newsSymbols.map((symbol) =>
          fetchJson(
            `${finnhubBaseUrl}/company-news?symbol=${encodeURIComponent(symbol)}&from=${targetDate}&to=${targetDate}&token=${finnhubToken}`,
          ),
        ),
      );

      rawArticles = filterArticlesByMarketDate(
        responseSets.flat().map((a) => ({
          title: a.headline ?? '',
          description: a.summary ?? '',
          content: a.summary ?? '',
          source: a.source ?? 'Finnhub',
          publishedAt: a.datetime ? new Date(a.datetime * 1000).toISOString() : new Date().toISOString(),
          url: a.url ?? '',
        })),
        targetDate,
      );
    } catch (error) {
      finnhubNewsError = error instanceof Error ? error.message : String(error);
      console.warn(`[marketService] Finnhub news fetch failed: ${finnhubNewsError}`);
    }
  }

  if (rawArticles.length === 0) {
    return buildFallbackArticles({ newsApiError, finnhubNewsError });
  }

  return buildWeeklyIssues(rawArticles);
}

// ─── 원시 기사 → 주간 이슈 요약 변환 ──────────────────────────────────────
function buildWeeklyIssues(rawArticles) {
  const issues = [];
  const usedUrls = new Set();

  for (const theme of ISSUE_THEMES) {
    const matched = rawArticles.filter((a) => {
      const text = `${a.title} ${a.description}`.toLowerCase();
      return theme.keywords.some((kw) => text.includes(kw));
    });

    if (matched.length === 0) continue;

    // 대표 기사: 키워드 매칭 수가 가장 많은 기사
    const scored = matched
      .map((a) => {
        const text = `${a.title} ${a.description}`.toLowerCase();
        const score = theme.keywords.filter((kw) => text.includes(kw)).length;
        return { a, score };
      })
      .sort((x, y) => y.score - x.score);

    const repArticle = scored[0].a;
    const repUrl = repArticle.url;
    usedUrls.add(repUrl);

    const summaryText = buildIssueSummary(theme.key, matched);

    issues.push({
      title: theme.title,
      description: summaryText,
      content: summaryText,
      source: '주간 이슈 요약',
      publishedAt: repArticle.publishedAt ?? new Date().toISOString(),
      url: repUrl,
      koreanSummary: summaryText.split('. ')[0] + '.',
    });

    if (issues.length >= 5) break;
  }

  // 테마 매칭이 부족하면 미분류 기사로 보충
  if (issues.length < 3) {
    const remaining = rawArticles.filter((a) => !usedUrls.has(a.url));
    const pool = remaining.length > 0 ? remaining : rawArticles;
    issues.push(buildGeneralIssue(pool));
  }

  return issues.slice(0, 5);
}

function buildIssueSummary(themeKey, articles) {
  const combined = articles
    .slice(0, 6)
    .map((a) => `${a.title} ${a.description}`)
    .join(' ')
    .toLowerCase();

  const lines = [];

  if (themeKey === 'fed') {
    if (combined.includes('cut') || combined.includes('rate reduction') || combined.includes('lower rate')) {
      lines.push('이번 주 연준은 금리 인하 가능성을 시사하거나 실제 인하를 단행하며 시장에 강한 호재로 작용했습니다.');
    } else if (combined.includes('hike') || combined.includes('raise rate') || combined.includes('higher for longer')) {
      lines.push('연준의 금리 인상 또는 고금리 유지 기조가 재확인되며 시장 전반에 조정 압력이 가해졌습니다.');
    } else if (combined.includes('hold') || combined.includes('pause') || combined.includes('unchanged')) {
      lines.push('연준이 금리 동결을 결정하면서 시장은 향후 정책 전환 시점에 촉각을 곤두세우는 모습이었습니다.');
    } else {
      lines.push('연준의 통화정책 기조와 물가 동향이 이번 주 시장 방향성을 결정짓는 핵심 변수로 부상했습니다.');
    }
    if (combined.includes('inflation') || combined.includes('cpi') || combined.includes('pce')) {
      lines.push('물가 지표 발표 결과가 채권 수익률과 위험자산 선호도에 직접적인 영향을 미쳤습니다.');
    }
    if (combined.includes('yield') || combined.includes('treasury')) {
      lines.push('국채 수익률 변화는 성장주 밸류에이션과 섹터 로테이션 흐름을 촉진시켰습니다.');
    }

  } else if (themeKey === 'tech') {
    if (combined.includes('nvidia') || combined.includes('ai chip')) {
      lines.push('엔비디아를 중심으로 AI 반도체 섹터에 강한 수요 모멘텀이 확인되며 기술주 전반의 상승을 견인했습니다.');
    } else if (combined.includes('earnings') || combined.includes('revenue') || combined.includes('profit')) {
      lines.push('주요 기술 대형주의 실적 발표가 시장 예상에 부합하거나 상회하며 기술주 투자심리를 개선시켰습니다.');
    } else {
      lines.push('AI·반도체 관련 수급 동향이 나스닥 및 기술주 ETF(QQQ, SOXL)의 방향성을 주도한 한 주였습니다.');
    }
    if (combined.includes('microsoft') || combined.includes('openai') || combined.includes('chatgpt')) {
      lines.push('마이크로소프트·오픈AI 생태계 확장 관련 소식이 AI 인프라 투자 심리를 자극했습니다.');
    }
    if (combined.includes('export') || combined.includes('restriction') || combined.includes('ban')) {
      lines.push('반도체 수출 규제 또는 정책 리스크가 일부 공급망 불확실성을 높이는 요인으로 작용했습니다.');
    }

  } else if (themeKey === 'market') {
    if (combined.includes('rally') || combined.includes('surge') || combined.includes('gain') || combined.includes(' rise')) {
      lines.push('이번 주 미국 주식시장은 전반적인 상승 흐름 속에 S&P 500·나스닥 지수가 의미 있는 반등을 기록했습니다.');
    } else if (combined.includes('sell-off') || combined.includes('selloff') || combined.includes('decline') || combined.includes('drop')) {
      lines.push('이번 주 미국 주요 지수는 매도세 확대로 하락 압력을 받았으며 변동성 지수(VIX)가 상승하는 모습을 보였습니다.');
    } else {
      lines.push('미국 증시는 이번 주 혼조세를 보이며 방향성을 탐색하는 국면을 이어갔습니다.');
    }
    if (combined.includes('tariff') || combined.includes('trade war')) {
      lines.push('미국의 관세 정책 변화 또는 무역 분쟁 관련 재료가 기업 이익 전망에 불확실성을 더했습니다.');
    }
    if (combined.includes('earnings') || combined.includes('beat') || combined.includes('miss')) {
      lines.push('주요 기업 실적 발표 결과가 섹터별 차별화 장세를 만들어내는 데 영향을 미쳤습니다.');
    }

  } else if (themeKey === 'crypto') {
    if (combined.includes('bitcoin') && (combined.includes('rally') || combined.includes('surge') || combined.includes(' high'))) {
      lines.push('비트코인이 강한 상승 흐름을 이어가며 코인 시장 전반의 투자심리 개선을 이끌었습니다.');
    } else if (combined.includes('bitcoin') && (combined.includes('drop') || combined.includes('fall') || combined.includes('decline'))) {
      lines.push('비트코인 가격이 하락 압력을 받으며 전체 암호화폐 시장의 리스크 오프 분위기를 반영했습니다.');
    } else {
      lines.push('암호화폐 시장에서 비트코인·이더리움을 중심으로 수급 변화가 디지털 자산 전반의 투자심리를 결정지었습니다.');
    }
    if (combined.includes('etf') || combined.includes('institutional')) {
      lines.push('기관 투자자의 비트코인 ETF 자금 유출입 동향이 가격 방향성에 영향을 주는 핵심 변수로 주목받았습니다.');
    }
    if (combined.includes('regulation') || combined.includes('sec') || combined.includes('government')) {
      lines.push('규제 관련 뉴스가 코인 시장의 단기 변동성을 높이는 재료로 작용했습니다.');
    }

  } else if (themeKey === 'macro') {
    if (combined.includes('oil') || combined.includes('crude') || combined.includes('opec')) {
      lines.push('국제 유가는 OPEC 정책 변화와 수요 전망에 따라 에너지 섹터 수익성과 물가 전망에 영향을 미쳤습니다.');
    }
    if (combined.includes('dollar') || combined.includes('dxy') || combined.includes('usd')) {
      lines.push('달러 강세 또는 약세 기조는 신흥국 자산 및 원자재 가격, USD/KRW 환율 변동에 직접적인 영향을 줬습니다.');
    }
    if (combined.includes('china') || combined.includes('trade')) {
      lines.push('미중 무역 관계 및 중국 경기 흐름이 글로벌 성장 전망과 한국 수출 시장에 시사점을 남겼습니다.');
    }
    if (lines.length === 0) {
      lines.push('원유·달러·환율 등 글로벌 거시 변수의 변화가 주요 자산군의 상대적 강도 변화를 촉발한 한 주였습니다.');
    }
  }

  if (lines.length === 0) {
    lines.push('관련 시장 뉴스가 투자심리에 영향을 미친 한 주였으며, 주요 자산군 흐름을 면밀히 점검할 필요가 있습니다.');
  }

  return lines.join(' ');
}

function buildGeneralIssue(articles) {
  const repArticle = articles[0];
  const summary =
    '이번 주 미국 증시는 다양한 거시·미시 경제 재료가 복합적으로 작용하며 변동성이 확대된 한 주였습니다. ' +
    '주요 지수의 방향성을 좌우한 핵심 이벤트를 중심으로 다음 주 투자 전략을 점검해 볼 필요가 있습니다.';

  return {
    title: '시장 전반 동향',
    description: summary,
    content: summary,
    source: '주간 이슈 요약',
    publishedAt: repArticle?.publishedAt ?? new Date().toISOString(),
    url: repArticle?.url ?? '',
    koreanSummary: '이번 주 미국 증시는 복합 재료 속 변동성이 확대되었습니다.',
  };
}

async function generateNasdaqAnalysis(assets, articles) {
  const claudeApiKey = process.env.CLAUDE_API_KEY || process.env.ANTHROPIC_API_KEY;
  if (!claudeApiKey) {
    return '';
  }

  const assetSummary = assets
    .map((a) => {
      const sign = a.changePercent >= 0 ? '+' : '';
      return `${a.name}(${a.symbol}): ${sign}${a.changePercent.toFixed(2)}%`;
    })
    .join('\n');

  const topArticles = articles.slice(0, 10).map((a, i) =>
    `${i + 1}. [${a.source}] ${a.title}\n   ${a.content || a.description || ''}`,
  ).join('\n');

  const prompt = `오늘 미국 주식시장 주요 지수/ETF 등락과 뉴스입니다.\n\n## 주요 지수/ETF 등락\n${assetSummary}\n\n## 주요 뉴스\n${topArticles}\n\n위 정보를 바탕으로 오늘 나스닥 변동의 핵심 요인을 아래 형식으로 간결하게 정리해주세요:\n- 상승/하락 원인 2~4가지를 불릿 포인트(•)로\n- 각 요인에 구체적인 기업명·지표·수치 포함\n- 전체 4~8줄 이내, 한국어로 작성`;

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': claudeApiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 512,
        messages: [{ role: 'user', content: prompt }],
      }),
    });

    const data = await response.json();
    return (data?.content?.[0]?.text ?? '').trim();
  } catch (error) {
    console.warn('[marketService] Claude nasdaqAnalysis failed:', error.message);
    return '';
  }
}

function buildSummary(assets, articles) {
  const strongest = [...assets].sort((left, right) => right.changePercent - left.changePercent)[0];
  const weakest = [...assets].sort((left, right) => left.changePercent - right.changePercent)[0];
  const risingCount = assets.filter((asset) => asset.changePercent >= 0).length;
  const articleLead = articles[0]?.title ?? '주요 뉴스가 아직 정리되지 않았습니다.';

  return [
    `${risingCount}/${assets.length}개 추적 자산이 상승 마감했습니다.`,
    `상대 강세는 ${strongest?.name ?? 'N/A'} ${formatPercent(strongest?.changePercent ?? 0)} 입니다.`,
    `상대 약세는 ${weakest?.name ?? 'N/A'} ${formatPercent(weakest?.changePercent ?? 0)} 입니다.`,
    `주요 헤드라인: ${articleLead}`,
  ].join(' ');
}

function buildStrategyHint(changePercent) {
  if (changePercent >= 2) {
    return '강한 추세 구간이라 단기 과열 여부를 확인하는 접근이 유리합니다.';
  }

  if (changePercent >= 0) {
    return '상승 흐름 유지 여부를 보며 눌림목 대응이 적합합니다.';
  }

  if (changePercent <= -2) {
    return '변동성 확대 구간이라 무리한 추격보다는 지지선 확인이 우선입니다.';
  }

  return '방향성이 약해 분할 대응과 보수적 관찰이 적합합니다.';
}

function formatPercent(value) {
  const prefix = value >= 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)}%`;
}

function dedupeArticles(articles) {
  const seen = new Set();

  return articles.filter((article) => {
    if (!article.title || !article.url) {
      return false;
    }

    const key = `${article.title}::${article.url}`;
    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function filterArticlesByMarketDate(articles, targetDate) {
  return dedupeArticles(articles)
    .filter((article) => formatDateInTimezone(article.publishedAt, MARKET_TIMEZONE) === targetDate)
    .sort((left, right) => new Date(right.publishedAt).getTime() - new Date(left.publishedAt).getTime());
}

function formatDateInTimezone(value, timeZone) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }

  return new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(parsed);
}

function buildFallbackDailySeries(close, changePercent) {
  const values = [];
  const baseline = close / (1 + (changePercent / 100));
  const start = Number.isFinite(baseline) && baseline > 0 ? baseline : close * 0.985;

  for (let index = 0; index < 8; index += 1) {
    const ratio = index / 7;
    const value = start + ((close - start) * ratio);
    values.push(roundMarketValue(value));
  }

  return values;
}

function buildAssetFallbackQuote(asset, index, baseRate, stepRate) {
  if (asset.kind === 'fx') {
    const previousClose = 1462;
    const close = 1470;
    const changeAmount = roundMarketValue(close - previousClose);
    const changePercent = Number((((close - previousClose) / previousClose) * 100).toFixed(2));
    return { close, previousClose, changeAmount, changePercent };
  }

  if (asset.kind === 'dollar-index') {
    const previousClose = 98.3;
    const close = 98.1;
    const changeAmount = roundMarketValue(close - previousClose);
    const changePercent = Number((((close - previousClose) / previousClose) * 100).toFixed(2));
    return { close, previousClose, changeAmount, changePercent };
  }

  const close = Number((100 + index * 12.34).toFixed(2));
  const previousClose = Number((99 + index * 12.1).toFixed(2));
  const changePercent = Number((baseRate + index * stepRate).toFixed(2));
  const changeAmount = Number((1 + index * 0.3).toFixed(2));
  return { close, previousClose, changeAmount, changePercent };
}

function isFallbackPayload(payload) {
  const firstHeadline = payload?.headlines?.[0] ?? '';
  const firstSource = payload?.articles?.[0]?.source ?? '';

  return firstHeadline.includes('Fallback:') || firstSource === 'Local fallback';
}

function buildFallbackArticles(context = {}) {
  const reason = [context.newsApiError, context.finnhubNewsError]
    .filter(Boolean)
    .join(' | ');

  return [
    {
      title: 'Fallback: market news is using local sample data',
      description: 'News API 호출 실패 또는 키 미설정으로 샘플 뉴스를 사용합니다.',
      content: reason
        ? `현재는 뉴스 API 호출 실패로 샘플 뉴스 데이터가 표시됩니다. 원인: ${reason}`
        : '현재는 뉴스 API 호출 실패 또는 키 미설정으로 샘플 뉴스 데이터가 표시됩니다.',
      source: 'Local fallback',
      publishedAt: new Date().toISOString(),
      url: 'https://finnhub.io/',
      koreanSummary: '한줄요약: 뉴스 API 폴백으로 샘플 뉴스 데이터가 표시됩니다.',
    },
  ];
}

function buildFallbackPayload(targetDate, error) {
  const assets = trackedAssets.map((asset, index) => {
    const fallback = buildAssetFallbackQuote(asset, index, 0.4, 0.35);
    return {
      symbol: asset.symbol,
      name: asset.name,
      kind: asset.kind,
      close: fallback.close,
      previousClose: fallback.previousClose,
      changePercent: fallback.changePercent,
      changeAmount: fallback.changeAmount,
      dailySeries: buildFallbackDailySeries(fallback.close, fallback.changePercent),
      strategyHint: buildStrategyHint(fallback.changePercent),
    };
  });

  const articles = buildFallbackArticles();

  return {
    date: targetDate,
    updatedAt: new Date().toISOString(),
    summary: `실시간 데이터 연동에 실패해 샘플 데이터로 표시 중입니다. 원인: ${error instanceof Error ? error.message : 'unknown error'}`,
    nasdaqAnalysis: '',
    headlines: articles.map((article) => article.title),
    articles,
    trackedAssets: assets,
    offlineSupported: true,
    isCached: false,
  };
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      'User-Agent': 'BATA-StockApp/1.0',
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}
