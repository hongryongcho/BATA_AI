import 'package:flutter_test/flutter_test.dart';

import 'package:bata_stock_mobile/main.dart';

void main() {
  testWidgets('app boots', (WidgetTester tester) async {
    await tester.pumpWidget(const BataStockApp());
    expect(find.text('BATA Stock Daily'), findsOneWidget);
  });
}
