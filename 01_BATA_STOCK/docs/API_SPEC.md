# API 명세서 (API Specification)

**작성일:** 2026-05-08  
**상태:** 준비 완료  
**목표:** Finnhub + NewsAPI 연동 명세

---

## 1. Finnhub API (주식 데이터)

### 1.1 회원가입 & API 키 발급
**링크:** https://finnhub.io/register  
**무료 tier:** ✅ 있음 (실시간 데이터 + 60회/분)

### 1.2 엔드포인트: 주식 종가 조회
```
GET https://finnhub.io/api/v1/quote?symbol=AAPL&token={YOUR_API_KEY}
```

**응답 예시:**
```json
{
  "c": 150.25,        // 현재 종가 (Current price)
  "h": 150.50,        // 하루 최고가 (High)
  "l": 149.00,        // 하루 최저가 (Low)
  "o": 149.50,        // 시가 (Open)
  "pc": 149.80,       // 이전 종가 (Previous close)
  "t": 1715030800     // Unix 타임스탬프
}
```

**분석:**
```
변화율 계산 = ((c - pc) / pc) × 100
예: ((150.25 - 149.80) / 149.80) × 100 = 0.30%

→ "↑ +$0.45 (+0.30%)"
```

**코드 예시 (Dart/Flutter):**
```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

Future<Map<String, dynamic>> getStockQuote(String symbol) async {
  final apiKey = '${FINNHUB_API_KEY}';
  final url = 'https://finnhub.io/api/v1/quote?symbol=$symbol&token=$apiKey';
  
  final response = await http.get(Uri.parse(url));
  
  if (response.statusCode == 200) {
    return jsonDecode(response.body);
  } else {
    throw Exception('API 호출 실패: ${response.statusCode}');
  }
}
```

---

## 2. Finnhub API (시장 지표)

### 2.1 엔드포인트: 지표 조회
```
GET https://finnhub.io/api/v1/quote?symbol=^GSPC&token={YOUR_API_KEY}
```

**포함할 지표:**
| 심볼 | 이름 | 설명 |
|------|------|------|
| ^GSPC | S&P 500 | 미국 주요 500개 기업 |
| ^IXIC | NASDAQ-100 | 미국 기술주 지수 |
| ^DJI | Dow Jones | 미국 우량주 30개 |

**응답 예시:**
```json
{
  "c": 5320.15,       // 현재 지수
  "pc": 5274.85,      // 이전 종가
  // 변화율 = ((5320.15 - 5274.85) / 5274.85) × 100 = 0.86%
}
```

**Dart 구현:**
```dart
Future<List<MarketIndicator>> getMarketIndicators() async {
  final indicators = ['^GSPC', '^IXIC', '^DJI'];
  final results = <MarketIndicator>[];
  
  for (String symbol in indicators) {
    final data = await getStockQuote(symbol);
    results.add(MarketIndicator(
      symbol: symbol,
      currentPrice: data['c'],
      changePercent: ((data['c'] - data['pc']) / data['pc']) * 100,
    ));
  }
  
  return results;
}
```

---

## 3. NewsAPI (뉴스 데이터)

### 3.1 회원가입 & API 키 발급
**링크:** https://newsapi.org/  
**무료 tier:** ✅ 100회/일  

### 3.2 엔드포인트: 뉴스 검색
```
GET https://newsapi.org/v2/everything
```

**쿼리 파라미터:**
```
q=AAPL&sortBy=publishedAt&language=en&pageSize=5&apiKey={YOUR_API_KEY}
```

| 파라미터 | 값 | 설명 |
|---------|-----|------|
| q | "stock market" 또는 심볼 | 검색 키워드 |
| sortBy | publishedAt | 최신순 정렬 |
| language | en | 영어만 |
| pageSize | 5 | 5개 결과만 |
| apiKey | {YOUR_KEY} | API 키 |

**응답 예시:**
```json
{
  "status": "ok",
  "totalResults": 38000,
  "articles": [
    {
      "source": {
        "id": "cnbc",
        "name": "CNBC"
      },
      "author": "John Doe",
      "title": "Apple stock surges on strong earnings",
      "description": "Apple Inc. shares jumped...",
      "url": "https://cnbc.com/article/...",
      "urlToImage": "https://image.url/...",
      "publishedAt": "2026-05-07T13:45:00Z",
      "content": "Full article content..."
    },
    // ... 4개 더
  ]
}
```

**Dart 구현:**
```dart
Future<List<NewsArticle>> getNews(String keyword, int pageSize) async {
  final apiKey = '${NEWSAPI_KEY}';
  final url = 'https://newsapi.org/v2/everything'
      '?q=$keyword'
      '&sortBy=publishedAt'
      '&language=en'
      '&pageSize=$pageSize'
      '&apiKey=$apiKey';
  
  final response = await http.get(Uri.parse(url));
  
  if (response.statusCode == 200) {
    final json = jsonDecode(response.body);
    final articles = json['articles'] as List;
    
    return articles
        .map((a) => NewsArticle(
          title: a['title'],
          description: a['description'],
          url: a['url'],
          publishedAt: DateTime.parse(a['publishedAt']),
          imageUrl: a['urlToImage'],
        ))
        .toList();
  } else {
    throw Exception('뉴스 API 호출 실패');
  }
}
```

---

## 4. 통합 데이터 모델 (Dart Classes)

### 4.1 주식 모델
```dart
class Stock {
  final String symbol;
  final String name;
  final double currentPrice;
  final double previousPrice;
  
  double get changeAmount => currentPrice - previousPrice;
  double get changePercent => (changeAmount / previousPrice) * 100;
  bool get isUp => changeAmount >= 0;
  
  String get formattedChange => 
      '${isUp ? "↑" : "↓"} ${changeAmount.toStringAsFixed(2)} '
      '(${changePercent.toStringAsFixed(2)}%)';
  
  Stock({
    required this.symbol,
    required this.name,
    required this.currentPrice,
    required this.previousPrice,
  });
}
```

### 4.2 뉴스 모델
```dart
class NewsArticle {
  final String title;
  final String description;
  final String url;
  final DateTime publishedAt;
  final String? imageUrl;
  
  String get timeAgo {
    final now = DateTime.now();
    final diff = now.difference(publishedAt);
    
    if (diff.inMinutes < 60) return '${diff.inMinutes}분 전';
    if (diff.inHours < 24) return '${diff.inHours}시간 전';
    return '${diff.inDays}일 전';
  }
  
  NewsArticle({
    required this.title,
    required this.description,
    required this.url,
    required this.publishedAt,
    this.imageUrl,
  });
}
```

### 4.3 시장 지표 모델
```dart
class MarketIndicator {
  final String symbol;
  final String name;
  final double currentValue;
  final double previousValue;
  
  double get changePercent => 
      ((currentValue - previousValue) / previousValue) * 100;
  bool get isUp => changePercent >= 0;
  
  MarketIndicator({
    required this.symbol,
    required this.name,
    required this.currentValue,
    required this.previousValue,
  });
}
```

---

## 5. API 호출 전략

### 5.1 병렬 호출 (동시성 최적화)
```dart
Future<AppData> loadDailyData() async {
  try {
    // 3개 API를 동시에 호출
    final results = await Future.wait([
      getStockQuotes(['AAPL', 'MSFT', 'GOOGL']),
      getMarketIndicators(),
      getNews('stock market', 5),
    ]);
    
    return AppData(
      stocks: results[0] as List<Stock>,
      indicators: results[1] as List<MarketIndicator>,
      news: results[2] as List<NewsArticle>,
    );
  } catch (e) {
    print('데이터 로드 실패: $e');
    rethrow;
  }
}
```

### 5.2 레이트 제한 처리
| API | 제한 | 대응 |
|-----|------|------|
| Finnhub | 60회/분 | 캐싱 (5분) |
| NewsAPI | 100회/일 | 하루 1회만 호출 |

**캐싱 전략:**
```dart
class ApiCache {
  final Map<String, CachedData> _cache = {};
  final Duration cacheDuration = Duration(minutes: 5);
  
  bool isCached(String key) {
    if (!_cache.containsKey(key)) return false;
    return DateTime.now()
        .difference(_cache[key]!.timestamp) < cacheDuration;
  }
  
  T? get<T>(String key) => isCached(key) ? _cache[key]!.data : null;
  
  void set<T>(String key, T data) {
    _cache[key] = CachedData(data, DateTime.now());
  }
}
```

---

## 6. 에러 처리

### 6.1 일반적인 에러 케이스
```dart
try {
  final data = await getStockQuote('AAPL');
} on SocketException catch (e) {
  // 네트워크 에러
  showOfflineMode();
} on TimeoutException catch (e) {
  // API 응답 시간 초과 (> 10초)
  useCachedData();
} on FormatException catch (e) {
  // JSON 파싱 에러
  logError('Invalid response format');
} catch (e) {
  // 기타 에러
  showErrorDialog('오류 발생: $e');
}
```

---

## 7. API 키 관리 (.env 파일)

**.env 파일 생성:**
```env
FINNHUB_API_KEY=your_finnhub_api_key_here
NEWSAPI_KEY=your_newsapi_key_here
```

**pubspec.yaml:**
```yaml
dev_dependencies:
  flutter_dotenv: ^5.0.0
```

**main.dart:**
```dart
import 'package:flutter_dotenv/flutter_dotenv.dart';

void main() async {
  await dotenv.load(fileName: ".env");
  runApp(const MyApp());
}

// 사용 방법:
final apiKey = dotenv.env['FINNHUB_API_KEY'];
```

---

## 8. 테스트 데이터

### 8.1 Mock 데이터 (offline 테스트용)
```dart
final mockStock = Stock(
  symbol: 'AAPL',
  name: 'Apple Inc.',
  currentPrice: 150.25,
  previousPrice: 149.80,
);

final mockNews = NewsArticle(
  title: 'Apple announces new iPhone',
  description: 'The company unveiled...',
  url: 'https://example.com',
  publishedAt: DateTime(2026, 5, 7),
);
```

---

## 9. 다음 단계

✅ **API 키 발급:**
- [ ] Finnhub 회원가입 → API 키 복사
- [ ] NewsAPI 회원가입 → API 키 복사

✅ **코드 준비:**
- [ ] Dart 데이터 모델 구현
- [ ] API 서비스 클래스 작성
- [ ] 캐싱 로직 구현

---

**참고:** Phase 3 구현 단계에서 이 명세를 바탕으로 실제 코드를 작성합니다.
