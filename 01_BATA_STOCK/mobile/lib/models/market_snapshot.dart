class MarketSnapshot {
  const MarketSnapshot({
    required this.summary,
    required this.indices,
    required this.headlines,
    required this.articles,
    required this.updatedAt,
    required this.isOffline,
    required this.isCached,
    required this.date,
  });

  final String summary;
  final List<TrackedAsset> indices;
  final List<String> headlines;
  final List<NewsArticle> articles;
  final DateTime updatedAt;
  final bool isOffline;
  final bool isCached;
  final DateTime date;

  MarketSnapshot copyWith({
    String? summary,
    List<TrackedAsset>? indices,
    List<String>? headlines,
    List<NewsArticle>? articles,
    DateTime? updatedAt,
    bool? isOffline,
    bool? isCached,
    DateTime? date,
  }) {
    return MarketSnapshot(
      summary: summary ?? this.summary,
      indices: indices ?? this.indices,
      headlines: headlines ?? this.headlines,
      articles: articles ?? this.articles,
      updatedAt: updatedAt ?? this.updatedAt,
      isOffline: isOffline ?? this.isOffline,
      isCached: isCached ?? this.isCached,
      date: date ?? this.date,
    );
  }

  factory MarketSnapshot.fromJson(Map<String, dynamic> json) {
    final trackedAssets = (json['trackedAssets'] as List<dynamic>? ?? <dynamic>[])
        .whereType<Map<String, dynamic>>()
        .map(TrackedAsset.fromJson)
        .toList();

    final headlines = (json['headlines'] as List<dynamic>? ?? <dynamic>[])
        .map((item) => item.toString())
        .toList();

    final articles = (json['articles'] as List<dynamic>? ?? <dynamic>[])
        .whereType<Map<String, dynamic>>()
        .map(NewsArticle.fromJson)
        .toList();

    final dateText = json['date']?.toString();
    final parsedDate = dateText == null ? DateTime.now() : DateTime.tryParse(dateText) ?? DateTime.now();
    final updatedAtText = json['updatedAt']?.toString();

    return MarketSnapshot(
      summary: json['summary']?.toString() ?? '',
      indices: trackedAssets,
      headlines: headlines,
      articles: articles,
      updatedAt: updatedAtText == null ? parsedDate : DateTime.tryParse(updatedAtText) ?? parsedDate,
      isOffline: json['offlineSupported'] == true,
      isCached: json['isCached'] == true,
      date: parsedDate,
    );
  }
}

class TrackedAsset {
  const TrackedAsset({
    required this.symbol,
    required this.name,
    required this.close,
    required this.changePercent,
    required this.changeAmount,
    required this.previousClose,
    required this.kind,
    required this.dailySeries,
    required this.strategyHint,
  });

  final String symbol;
  final String name;
  final double close;
  final double changePercent;
  final double changeAmount;
  final double previousClose;
  final String kind;
  final List<double> dailySeries;
  final String strategyHint;

  bool get isPositive => changePercent >= 0;

  factory TrackedAsset.fromJson(Map<String, dynamic> json) {
    return TrackedAsset(
      symbol: json['symbol']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      close: (json['close'] as num?)?.toDouble() ?? 0,
      changePercent: (json['changePercent'] as num?)?.toDouble() ?? 0,
      changeAmount: (json['changeAmount'] as num?)?.toDouble() ?? 0,
      previousClose: (json['previousClose'] as num?)?.toDouble() ?? 0,
      kind: json['kind']?.toString() ?? 'asset',
      dailySeries: (json['dailySeries'] as List<dynamic>? ?? const <dynamic>[])
          .map((item) => (item as num).toDouble())
          .toList(),
      strategyHint: json['strategyHint']?.toString() ?? '',
    );
  }
}

class NewsArticle {
  const NewsArticle({
    required this.title,
    required this.description,
    required this.content,
    required this.source,
    required this.publishedAt,
    required this.url,
    required this.koreanSummary,
  });

  final String title;
  final String description;
  final String content;
  final String source;
  final DateTime publishedAt;
  final String url;
  final String koreanSummary;

  factory NewsArticle.fromJson(Map<String, dynamic> json) {
    final publishedAtText = json['publishedAt']?.toString();

    return NewsArticle(
      title: json['title']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
      content: json['content']?.toString() ?? '',
      source: json['source']?.toString() ?? '',
      publishedAt: publishedAtText == null
          ? DateTime.now()
          : DateTime.tryParse(publishedAtText) ?? DateTime.now(),
      url: json['url']?.toString() ?? '',
      koreanSummary: json['koreanSummary']?.toString() ?? '',
    );
  }
}
