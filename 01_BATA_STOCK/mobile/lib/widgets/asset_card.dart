import 'package:flutter/material.dart';

import '../models/market_snapshot.dart';
import 'mini_sparkline.dart';

class AssetCard extends StatelessWidget {
  const AssetCard({super.key, required this.asset});

  final TrackedAsset asset;

  @override
  Widget build(BuildContext context) {
    final isPositive = asset.isPositive;
    final changeColor = isPositive
        ? const Color(0xFF0ECB81) // 초록
        : const Color(0xFFF6465D); // 빨강
    final changePrefix = isPositive ? '+' : '';
    final arrowIcon = isPositive ? Icons.arrow_drop_up : Icons.arrow_drop_down;

    return SizedBox(
      height: 56,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // ① 심볼 + 이름
            SizedBox(
              width: 110,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    asset.symbol.replaceAll('^', ''),
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    asset.name,
                    style: TextStyle(
                      fontSize: 11,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            // ② 스파크라인
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: MiniSparkline(
                  series: asset.dailySeries,
                  strokeColor: changeColor,
                  height: 34,
                ),
              ),
            ),
            // ③ 가격 + 변화율 뱃지
            Row(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      _formatPrice(asset.close),
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
                    ),
                    const SizedBox(height: 3),
                    // 변화율 뱃지
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                      decoration: BoxDecoration(
                        color: changeColor.withValues(alpha: 0.13),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(arrowIcon, size: 13, color: changeColor),
                          Text(
                            '$changePrefix${asset.changePercent.toStringAsFixed(2)}%',
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              color: changeColor,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _formatPrice(double value) {
    if (value >= 10000) {
      return value.toStringAsFixed(0);
    }
    if (value >= 1000) {
      return value.toStringAsFixed(2);
    }
    if (value >= 1) {
      return value.toStringAsFixed(2);
    }
    if (value >= 0.01) {
      return value.toStringAsFixed(4);
    }
    if (value > 0) {
      return value.toStringAsFixed(6);
    }
    return value.toStringAsFixed(2);
  }
}
