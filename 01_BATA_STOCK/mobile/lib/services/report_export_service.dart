import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:share_plus/share_plus.dart';

import '../models/market_snapshot.dart';

class ReportExportService {
  Future<File> exportPdf(MarketSnapshot snapshot) async {
    final directory = await getApplicationDocumentsDirectory();
    final filePath = '${directory.path}/bata-report-${_dateText(snapshot.date)}.pdf';

    final document = pw.Document();
    document.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        build: (context) => [
          pw.Text('BATA US Market Daily Report', style: pw.TextStyle(fontSize: 20, fontWeight: pw.FontWeight.bold)),
          pw.SizedBox(height: 8),
          pw.Text('Date: ${_dateText(snapshot.date)}'),
          pw.Text('Updated: ${snapshot.updatedAt.toIso8601String()}'),
          pw.SizedBox(height: 14),
          pw.Text('Summary', style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold)),
          pw.SizedBox(height: 6),
          pw.Text(snapshot.summary),
          pw.SizedBox(height: 14),
          pw.Text('Tracked Assets', style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold)),
          pw.SizedBox(height: 6),
          ...snapshot.indices.map(
            (asset) {
              final prefix = asset.changePercent >= 0 ? '+' : '';
              return pw.Padding(
                padding: const pw.EdgeInsets.only(bottom: 4),
                child: pw.Text('${asset.name} (${asset.symbol})  ${asset.close.toStringAsFixed(2)}  $prefix${asset.changePercent.toStringAsFixed(2)}%'),
              );
            },
          ),
          pw.SizedBox(height: 14),
          pw.Text('Top News', style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold)),
          pw.SizedBox(height: 6),
          ...snapshot.articles.asMap().entries.map(
            (entry) => pw.Padding(
              padding: const pw.EdgeInsets.only(bottom: 6),
              child: pw.Text('${entry.key + 1}. ${entry.value.title} (${entry.value.source})'),
            ),
          ),
        ],
      ),
    );

    final bytes = await document.save();
    final file = File(filePath);
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }

  Future<File> exportImage(Uint8List pngBytes, DateTime date) async {
    final directory = await getApplicationDocumentsDirectory();
    final filePath = '${directory.path}/bata-report-${_dateText(date)}.png';
    final file = File(filePath);
    await file.writeAsBytes(pngBytes, flush: true);
    return file;
  }

  Future<void> shareFile(File file, {String? text}) async {
    await Share.shareXFiles([XFile(file.path)], text: text);
  }

  String _dateText(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '$year-$month-$day';
  }
}
