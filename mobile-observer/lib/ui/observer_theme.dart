import 'package:flutter/material.dart';

class ObserverTheme {
  static const ink = Color(0xFF183B56);
  static const paper = Color(0xFFF4F2EA);
  static const blue = Color(0xFF356A8A);
  static const green = Color(0xFF477D68);
  static const amber = Color(0xFFA86B23);

  static ThemeData get data {
    final scheme =
        ColorScheme.fromSeed(
          seedColor: blue,
          brightness: Brightness.light,
        ).copyWith(
          primary: ink,
          secondary: blue,
          surface: const Color(0xFFFFFEFA),
          tertiary: green,
          error: const Color(0xFFB4483D),
        );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: paper,
      appBarTheme: const AppBarTheme(
        backgroundColor: paper,
        foregroundColor: ink,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: scheme.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFFECEAE2),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: blue, width: 1.5),
        ),
      ),
      textTheme: const TextTheme().apply(bodyColor: ink, displayColor: ink),
    );
  }
}
