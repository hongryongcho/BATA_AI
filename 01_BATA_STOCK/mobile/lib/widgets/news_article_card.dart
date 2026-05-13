import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/market_snapshot.dart';

class NewsArticleCard extends StatelessWidget {
  const NewsArticleCard({
    super.key,
    required this.article,
    required this.index,
    required this.onTap,
  });

  final NewsArticle article;
  final int index;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 이슈 번호 + 제목
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CircleAvatar(
                  radius: 13,
                  backgroundColor: colorScheme.primary,
                  child: Text(
                    '${index + 1}',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      color: colorScheme.onPrimary,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    article.title,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            // 이슈 요약 본문 (multi-line)
            Text(
              article.content.isNotEmpty ? article.content : article.description,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                    height: 1.6,
                  ),
            ),
            // 관련 기사 버튼
            if (article.url.isNotEmpty) ...[
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: () => _openUrl(context),
                  icon: const Icon(Icons.open_in_new, size: 14),
                  label: const Text('관련 기사 보기'),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    textStyle: const TextStyle(fontSize: 12),
                  ),
                ),
              ),
            ],
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
