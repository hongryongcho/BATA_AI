import 'package:flutter/material.dart';

class MiniSparkline extends StatelessWidget {
  const MiniSparkline({
    super.key,
    required this.series,
    required this.strokeColor,
    this.height = 36,
    this.filled = true,
  });

  final List<double> series;
  final Color strokeColor;
  final double height;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    if (series.length < 2) {
      return SizedBox(height: height);
    }

    return SizedBox(
      height: height,
      child: CustomPaint(
        painter: _SparklinePainter(
          values: series,
          color: strokeColor,
          filled: filled,
        ),
        size: Size(double.infinity, height),
      ),
    );
  }
}

class _SparklinePainter extends CustomPainter {
  _SparklinePainter({required this.values, required this.color, required this.filled});

  final List<double> values;
  final Color color;
  final bool filled;

  @override
  void paint(Canvas canvas, Size size) {
    final minValue = values.reduce((a, b) => a < b ? a : b);
    final maxValue = values.reduce((a, b) => a > b ? a : b);
    final span = (maxValue - minValue).abs() < 0.0001 ? 1.0 : (maxValue - minValue);

    final points = <Offset>[];
    for (var i = 0; i < values.length; i++) {
      final x = (i / (values.length - 1)) * size.width;
      final y = size.height - ((values[i] - minValue) / span) * size.height;
      points.add(Offset(x, y));
    }

    // 그라데이션 fill
    if (filled) {
      final fillPath = Path();
      fillPath.moveTo(points.first.dx, size.height);
      for (final pt in points) {
        fillPath.lineTo(pt.dx, pt.dy);
      }
      fillPath.lineTo(points.last.dx, size.height);
      fillPath.close();

      final fillPaint = Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            color.withValues(alpha: 0.22),
            color.withValues(alpha: 0.0),
          ],
        ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

      canvas.drawPath(fillPath, fillPaint);
    }

    // 꺾은선
    final linePath = Path();
    linePath.moveTo(points.first.dx, points.first.dy);
    for (var i = 1; i < points.length; i++) {
      linePath.lineTo(points[i].dx, points[i].dy);
    }

    final linePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..color = color;

    canvas.drawPath(linePath, linePaint);
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter oldDelegate) {
    return oldDelegate.values != values || oldDelegate.color != color || oldDelegate.filled != filled;
  }
}
