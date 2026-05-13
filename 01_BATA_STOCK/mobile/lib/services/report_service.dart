import 'dart:convert';

import 'package:http/http.dart' as http;

class ReportService {
  ReportService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  static const String _baseUrl = 'http://localhost:4000';

  Future<List<String>> loadRecipients() async {
    final response = await _client.get(Uri.parse('$_baseUrl/api/report/recipients'));
    if (response.statusCode != 200) {
      throw Exception('수신 이메일 목록 조회 실패: ${response.statusCode}');
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final recipients = (json['recipients'] as List<dynamic>? ?? <dynamic>[])
        .map((item) => item.toString())
        .toList();
    return recipients;
  }

  Future<List<String>> addRecipient(String email) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/api/report/recipients'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email}),
    );

    if (response.statusCode != 201) {
      throw Exception('수신 이메일 추가 실패: ${response.statusCode}');
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    return (json['recipients'] as List<dynamic>? ?? <dynamic>[])
        .map((item) => item.toString())
        .toList();
  }

  Future<SendReportResult> sendDailyReport(DateTime date) async {
    final dateText = _formatDate(date);
    final response = await _client.post(
      Uri.parse('$_baseUrl/api/report/send-daily'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'date': dateText}),
    );

    if (response.statusCode != 200) {
      final bodyText = response.body;
      throw Exception('리포트 이메일 전송 실패: ${response.statusCode} $bodyText');
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    return SendReportResult(
      sentTo: (json['sentTo'] as List<dynamic>? ?? <dynamic>[])
          .map((item) => item.toString())
          .toList(),
      subject: json['subject']?.toString() ?? '',
      date: json['date']?.toString() ?? dateText,
    );
  }

  String _formatDate(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '$year-$month-$day';
  }
}

class SendReportResult {
  const SendReportResult({
    required this.sentTo,
    required this.subject,
    required this.date,
  });

  final List<String> sentTo;
  final String subject;
  final String date;
}
