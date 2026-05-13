import '../models/market_snapshot.dart';

class MockMarketService {
  Future<MarketSnapshot> loadSnapshot() async {
    await Future<void>.delayed(const Duration(milliseconds: 400));

    return MarketSnapshot(
      date: DateTime.now(),
      summary: '미국장은 기술주 반등과 금리 완화 기대 속에 강세로 마감했습니다. 반도체와 대형 기술주가 지수 상승을 주도했고, 시장은 다음 거래일에도 성장주 흐름 지속 여부를 주목하고 있습니다.',
      updatedAt: DateTime.now(),
      isOffline: false,
      isCached: false,
      indices: const [
        TrackedAsset(symbol: 'IXIC', name: 'NASDAQ', close: 18125.42, changePercent: 1.24, changeAmount: 222.40, previousClose: 17903.02, kind: 'index', dailySeries: [17903.0, 17950.0, 17980.0, 18010.0, 18055.0, 18090.0, 18125.42], strategyHint: '상승 흐름 유지 여부를 보며 눌림목 대응이 적합합니다.'),
        TrackedAsset(symbol: 'GSPC', name: 'S&P 500', close: 5231.18, changePercent: 0.81, changeAmount: 41.91, previousClose: 5189.27, kind: 'index', dailySeries: [5189.0, 5200.0, 5210.0, 5215.0, 5220.0, 5226.0, 5231.18], strategyHint: '상승 흐름 유지 여부를 보며 눌림목 대응이 적합합니다.'),
        TrackedAsset(symbol: 'DJI', name: 'Dow Jones', close: 39104.77, changePercent: 0.42, changeAmount: 162.87, previousClose: 38941.90, kind: 'index', dailySeries: [38941.0, 38970.0, 38998.0, 39020.0, 39050.0, 39080.0, 39104.77], strategyHint: '방향성이 약해 분할 대응과 보수적 관찰이 적합합니다.'),
        TrackedAsset(symbol: 'TQQQ', name: 'ProShares UltraPro QQQ', close: 61.22, changePercent: 2.83, changeAmount: 1.68, previousClose: 59.54, kind: 'etf', dailySeries: [59.54, 59.8, 60.1, 60.4, 60.7, 60.95, 61.22], strategyHint: '강한 추세 구간이라 단기 과열 여부를 확인하는 접근이 유리합니다.'),
        TrackedAsset(symbol: 'SOXL', name: 'Direxion Daily Semiconductor Bull 3X', close: 46.11, changePercent: 3.61, changeAmount: 1.61, previousClose: 44.50, kind: 'etf', dailySeries: [44.50, 44.8, 45.1, 45.4, 45.7, 45.9, 46.11], strategyHint: '강한 추세 구간이라 단기 과열 여부를 확인하는 접근이 유리합니다.'),
      ],
      headlines: const [
        'Apple suppliers signal steadier iPhone demand into next quarter',
        'NVIDIA-led semiconductor rally lifts growth-focused ETFs',
        'Fed rate-cut expectations improve sentiment across major indices',
        'Treasury yields ease as investors rotate back into large-cap tech',
        'Oil holds firm while equities absorb mixed macroeconomic signals',
      ],
      articles: [
        NewsArticle(
          title: '연준 · 금리 · 인플레이션',
          description: '연준의 통화정책 기조와 물가 동향이 이번 주 시장 방향성을 결정짓는 핵심 변수로 부상했습니다. 물가 지표 발표 결과가 채권 수익률과 위험자산 선호도에 직접적인 영향을 미쳤습니다.',
          content: '연준의 통화정책 기조와 물가 동향이 이번 주 시장 방향성을 결정짓는 핵심 변수로 부상했습니다. 물가 지표 발표 결과가 채권 수익률과 위험자산 선호도에 직접적인 영향을 미쳤습니다.',
          source: '주간 이슈 요약',
          publishedAt: DateTime.utc(2026, 5, 8, 9, 30),
          url: 'https://www.reuters.com/markets/',
          koreanSummary: '연준의 통화정책 기조와 물가 동향이 이번 주 시장 방향성을 결정짓는 핵심 변수로 부상했습니다.',
        ),
        NewsArticle(
          title: '기술주 · AI · 반도체',
          description: 'AI·반도체 관련 수급 동향이 나스닥 및 기술주 ETF(QQQ, SOXL)의 방향성을 주도한 한 주였습니다. 엔비디아를 중심으로 강한 수요 모멘텀이 확인되며 기술주 전반의 상승을 견인했습니다.',
          content: 'AI·반도체 관련 수급 동향이 나스닥 및 기술주 ETF(QQQ, SOXL)의 방향성을 주도한 한 주였습니다. 엔비디아를 중심으로 강한 수요 모멘텀이 확인되며 기술주 전반의 상승을 견인했습니다.',
          source: '주간 이슈 요약',
          publishedAt: DateTime.utc(2026, 5, 8, 9, 30),
          url: 'https://www.cnbc.com/technology/',
          koreanSummary: 'AI·반도체 관련 수급 동향이 나스닥 및 기술주 ETF(QQQ, SOXL)의 방향성을 주도했습니다.',
        ),
      ],
    );
  }
}
