import 'package:flutter/material.dart';

import 'screens/home_screen.dart';

void main() {
  runApp(const BataStockApp());
}

class BataStockApp extends StatelessWidget {
  const BataStockApp({super.key});

  @override
  Widget build(BuildContext context) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF1D4ED8),
      brightness: Brightness.dark,
    );

    return MaterialApp(
      title: 'BATA Stock Daily',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: colorScheme,
        fontFamily: 'Malgun Gothic',
        scaffoldBackgroundColor: const Color(0xFF081120),
        cardTheme: CardThemeData(
          color: const Color(0xFF111C2D),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
        ),
      ),
      home: const HomeScreen(),
    );
  }
}
