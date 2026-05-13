import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:screenshot/screenshot.dart';

import '../models/market_snapshot.dart';
import '../services/api_market_service.dart';
import '../services/report_export_service.dart';
import '../services/report_service.dart';
import '../widgets/news_article_card.dart';
import '../widgets/asset_card.dart';
import 'news_detail_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<MarketSnapshot> _snapshotFuture;
  late DateTime _selectedDate;
  MarketSnapshot? _latestSnapshot;

  final ApiMarketService _service = ApiMarketService();
  final ReportService _reportService = ReportService();
  final ReportExportService _exportService = ReportExportService();
  final ScreenshotController _screenshotController = ScreenshotController();

  @override
  void initState() {
    super.initState();
    _selectedDate = DateTime.now();
    _snapshotFuture = _service.loadSnapshot(date: _selectedDate);
  }

  Future<void> _reload() async {
    setState(() {
      _snapshotFuture = _service.loadSnapshot(date: _selectedDate);
    });
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _selectedDate,
      firstDate: DateTime.now().subtract(const Duration(days: 30)),
      lastDate: DateTime.now(),
    );

    if (picked == null) {
      return;
    }

    setState(() {
      _selectedDate = picked;
      _snapshotFuture = _service.loadSnapshot(date: _selectedDate);
    });
  }

  Future<void> _openReportDialog() async {
    final messenger = ScaffoldMessenger.of(context);
    List<String> recipients;

    try {
      recipients = await _reportService.loadRecipients();
    } catch (error) {
      if (!mounted) {
        return;
      }

      messenger.showSnackBar(
        SnackBar(content: Text('수신 이메일 목록을 불러오지 못했습니다: $error')),
      );
      return;
    }

    if (!mounted) {
      return;
    }

    await showGeneralDialog<void>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'email-panel',
      barrierColor: Colors.black54,
      pageBuilder: (dialogContext, animation, secondaryAnimation) {
        var localRecipients = recipients;

        return Align(
          alignment: Alignment.centerRight,
          child: Material(
            color: const Color(0xFF111C2D),
            borderRadius: const BorderRadius.horizontal(left: Radius.circular(20)),
            child: SizedBox(
              width: 420,
              height: double.infinity,
              child: StatefulBuilder(
                builder: (context, setDialogState) {
            Future<void> addRecipient() async {
              final controller = TextEditingController();

              final input = await showDialog<String>(
                context: dialogContext,
                builder: (context) => AlertDialog(
                  title: const Text('수신 이메일 추가'),
                  content: TextField(
                    controller: controller,
                    keyboardType: TextInputType.emailAddress,
                    autofocus: true,
                    decoration: const InputDecoration(
                      hintText: 'example@email.com',
                    ),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Text('취소'),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.of(context).pop(controller.text.trim()),
                      child: const Text('추가'),
                    ),
                  ],
                ),
              );

              if (input == null || input.isEmpty) {
                return;
              }

              try {
                final updated = await _reportService.addRecipient(input);
                setDialogState(() {
                  localRecipients = updated;
                });
              } catch (error) {
                if (!mounted) {
                  return;
                }

                messenger.showSnackBar(
                  SnackBar(content: Text('이메일 추가 실패: $error')),
                );
              }
            }

            return AlertDialog(
              backgroundColor: Colors.transparent,
              elevation: 0,
              insetPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 24),
              title: const Text('이메일 리포트 패널'),
              content: SizedBox(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('선택 날짜: ${DateFormat('yyyy-MM-dd').format(_selectedDate)}'),
                    const SizedBox(height: 12),
                    const Text('수신 이메일 목록'),
                    const SizedBox(height: 8),
                    if (localRecipients.isEmpty)
                      const Text('등록된 이메일이 없습니다.')
                    else
                      ...localRecipients.map(
                        (email) => Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Text('- $email'),
                        ),
                      ),
                    const SizedBox(height: 12),
                    const Text(
                      '개발 완료 전까지 실제 이메일 발송은 비활성화됩니다.',
                      style: TextStyle(color: Colors.orangeAccent),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: addRecipient,
                  child: const Text('이메일 추가'),
                ),
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('닫기'),
                ),
                FilledButton.icon(
                  onPressed: null,
                  icon: const Icon(Icons.picture_as_pdf),
                  label: const Text('전송 비활성화'),
                ),
              ],
            );
                },
              ),
            ),
          ),
        );
      },
    );
  }

  Future<void> _openShareDialog() async {
    final messenger = ScaffoldMessenger.of(context);
    final snapshot = _latestSnapshot;
    if (snapshot == null) {
      messenger.showSnackBar(const SnackBar(content: Text('데이터 로딩 후 다시 시도해 주세요.')));
      return;
    }

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('리포트 저장 및 공유'),
        content: const Text('PDF 또는 이미지 파일로 저장한 뒤 메신저로 공유할 수 있습니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('닫기'),
          ),
          FilledButton.tonalIcon(
            onPressed: () async {
              Navigator.of(dialogContext).pop();
              await _saveAndSharePdf(snapshot);
            },
            icon: const Icon(Icons.picture_as_pdf),
            label: const Text('PDF 저장+공유'),
          ),
          FilledButton.icon(
            onPressed: () async {
              Navigator.of(dialogContext).pop();
              await _saveAndShareImage(snapshot);
            },
            icon: const Icon(Icons.image),
            label: const Text('이미지 저장+공유'),
          ),
        ],
      ),
    );
  }

  Future<void> _saveAndSharePdf(MarketSnapshot snapshot) async {
    final messenger = ScaffoldMessenger.of(context);

    try {
      final file = await _exportService.exportPdf(snapshot);
      await _exportService.shareFile(
        file,
        text: 'BATA 리포트 PDF (${DateFormat('yyyy-MM-dd').format(snapshot.date)})',
      );
      if (!mounted) {
        return;
      }

      messenger.showSnackBar(SnackBar(content: Text('PDF 저장 완료: ${file.path}')));
    } catch (error) {
      if (!mounted) {
        return;
      }

      messenger.showSnackBar(SnackBar(content: Text('PDF 저장/공유 실패: $error')));
    }
  }

  Future<void> _saveAndShareImage(MarketSnapshot snapshot) async {
    final messenger = ScaffoldMessenger.of(context);

    try {
      final pngBytes = await _screenshotController.capture(pixelRatio: 2.0);
      if (pngBytes == null) {
        throw Exception('이미지 캡처 결과가 비어 있습니다.');
      }

      final file = await _exportService.exportImage(pngBytes, snapshot.date);
      await _exportService.shareFile(
        file,
        text: 'BATA 리포트 이미지 (${DateFormat('yyyy-MM-dd').format(snapshot.date)})',
      );

      if (!mounted) {
        return;
      }

      messenger.showSnackBar(SnackBar(content: Text('이미지 저장 완료: ${file.path}')));
    } catch (error) {
      if (!mounted) {
        return;
      }

      messenger.showSnackBar(SnackBar(content: Text('이미지 저장/공유 실패: $error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BATA Stock Daily'),
        centerTitle: false,
        actions: [
          IconButton(
            onPressed: _openShareDialog,
            icon: const Icon(Icons.share),
          ),
          IconButton(
            onPressed: _openReportDialog,
            icon: const Icon(Icons.forward_to_inbox),
          ),
          IconButton(
            onPressed: _reload,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: FutureBuilder<MarketSnapshot>(
        future: _snapshotFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }

          if (snapshot.hasError || !snapshot.hasData) {
            return const Center(child: Text('데이터를 불러오지 못했습니다.'));
          }

          final data = snapshot.data!;
          _latestSnapshot = data;
          final formattedDate = DateFormat('yyyy-MM-dd HH:mm').format(data.updatedAt);
          final selectedDateText = DateFormat('yyyy-MM-dd').format(_selectedDate);

          return Screenshot(
            controller: _screenshotController,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.tonalIcon(
                        onPressed: _pickDate,
                        icon: const Icon(Icons.calendar_month),
                        label: Text(selectedDateText),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Text(
                  '마감 요약',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('업데이트: $formattedDate'),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            if (data.isOffline)
                              const Chip(label: Text('오프라인 캐시')),
                            if (data.isCached)
                              const Chip(label: Text('저장본 사용')),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          data.summary,
                          style: Theme.of(context).textTheme.bodyLarge,
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                Text(
                  '주요 지수 및 ETF',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                Card(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  child: Column(
                    children: data.indices.asMap().entries.map((entry) {
                      final isLast = entry.key == data.indices.length - 1;
                      return Column(
                        children: [
                          AssetCard(asset: entry.value),
                          if (!isLast)
                            Divider(
                              height: 1,
                              indent: 12,
                              endIndent: 12,
                              color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.4),
                            ),
                        ],
                      );
                    }).toList(),
                  ),
                ),
                const SizedBox(height: 20),
                Text(
                  '주간 핵심 이슈',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                ...data.articles.asMap().entries.map(
                      (entry) => Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: NewsArticleCard(
                          article: entry.value,
                          index: entry.key,
                          onTap: () {
                            Navigator.of(context).push(
                              MaterialPageRoute(
                                builder: (_) => NewsDetailScreen(article: entry.value),
                              ),
                            );
                          },
                        ),
                      ),
                    ),
              ],
            ),
          );
        },
      ),
    );
  }
}
