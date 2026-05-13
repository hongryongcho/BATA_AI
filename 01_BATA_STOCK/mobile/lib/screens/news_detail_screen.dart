import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/market_snapshot.dart';

class NewsDetailScreen extends StatelessWidget {
  const NewsDetailScreen({super.key, required this.article});

  final NewsArticle article;

  @override
  Widget build(BuildContext context) {
    final summaryText = article.content.isNotEmpty ? article.content : article.description;

    return Scaffold(
      appBar: AppBar(
        title: const Text('이슈 상세'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 이슈 제목
            Text(
              article.title,
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 20),
            // 이슈 요약 본문
            Expanded(
              child: SingleChildScrollView(
                child: Text(
                  summaryText.isNotEmpty ? summaryText : '이슈 요약 정보가 없습니다.',
                  style: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.7),
                ),
              ),
            ),
            const SizedBox(height: 16),
            // 관련 기사 링크
            if (article.url.isNotEmpty)
              FilledButton.tonalIcon(
                onPressed: () => _openUrl(context),
                icon: const Icon(Icons.open_in_new),
                label: const Text('관련 기사 원문 열기'),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openUrl(BuildContext context) async {
    final uri = Uri.tryParse(article.url);
    if (uri == null) return;

    final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!launched && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('기사 링크를 열지 못했습니다.')),
      );
    }
  }
}
