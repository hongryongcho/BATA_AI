import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/market_snapshot.dart';

class ApiMarketService {
  ApiMarketService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  static const String _baseUrl = 'http://localhost:4000';

  Future<MarketSnapshot> loadSnapshot({DateTime? date}) async {
    final targetDate = date ?? DateTime.now();
    final dateText = _formatDate(targetDate);
    final cacheKey = 'market_snapshot_$dateText';
    final prefs = await SharedPreferences.getInstance();

    try {
      final response = await _client.get(
        Uri.parse('$_baseUrl/api/market/daily-summary?date=$dateText'),
      );

      if (response.statusCode != 200) {
        throw Exception('백엔드 호출 실패: ${response.statusCode}');
      }

      await prefs.setString(cacheKey, response.body);
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return MarketSnapshot.fromJson(json);
    } catch (_) {
      final cached = prefs.getString(cacheKey);
      if (cached == null) {
        rethrow;
      }

      final json = jsonDecode(cached) as Map<String, dynamic>;
      return MarketSnapshot.fromJson(json).copyWith(
        isOffline: true,
        isCached: true,
      );
    }
  }

  String _formatDate(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '$year-$month-$day';
  }
}
