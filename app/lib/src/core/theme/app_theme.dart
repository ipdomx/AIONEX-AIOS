import 'package:flutter/material.dart';

/// AIONEX visual identity v3, "Obsidian & Crimson" (vip-frontend/tailwind.config.ts).
abstract final class AionexColors {
  static const obsidian950 = Color(0xFF050505);
  static const obsidian900 = Color(0xFF0B0B0D);
  static const obsidian800 = Color(0xFF111114);
  static const obsidian700 = Color(0xFF18181C);
  static const obsidian600 = Color(0xFF222227);
  static const crimson200 = Color(0xFFFF4D5A);
  static const crimson400 = Color(0xFFFF2D3F);
  static const crimson500 = Color(0xFFE11D2E);
  static const crimson600 = Color(0xFF9B0F1C);
  static const crimson800 = Color(0xFF3D060B);
  static const text = Color(0xFFF4F4F5);
  static const textMuted = Color(0xFFA1A1AA);
}

abstract final class AppTheme {
  static const fontFamily = 'IBMPlexSansArabic';

  static ThemeData dark() {
    const scheme = ColorScheme(
      brightness: Brightness.dark,
      primary: AionexColors.crimson500,
      onPrimary: Colors.white,
      primaryContainer: AionexColors.crimson800,
      onPrimaryContainer: AionexColors.crimson200,
      secondary: AionexColors.crimson200,
      onSecondary: AionexColors.obsidian950,
      error: AionexColors.crimson400,
      onError: Colors.white,
      surface: AionexColors.obsidian900,
      onSurface: AionexColors.text,
      onSurfaceVariant: AionexColors.textMuted,
      surfaceContainerLowest: AionexColors.obsidian950,
      surfaceContainerLow: AionexColors.obsidian800,
      surfaceContainer: AionexColors.obsidian800,
      surfaceContainerHigh: AionexColors.obsidian700,
      surfaceContainerHighest: AionexColors.obsidian600,
      outline: AionexColors.obsidian600,
      outlineVariant: AionexColors.obsidian700,
    );
    final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: fontFamily);
    final radius = BorderRadius.circular(14);
    return base.copyWith(
      scaffoldBackgroundColor: AionexColors.obsidian950,
      appBarTheme: const AppBarTheme(
        backgroundColor: AionexColors.obsidian950,
        foregroundColor: AionexColors.text,
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: AionexColors.obsidian800,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: radius,
          side: const BorderSide(color: AionexColors.obsidian600),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AionexColors.obsidian800,
        border: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: AionexColors.obsidian600)),
        enabledBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: const BorderSide(color: AionexColors.obsidian600),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: const BorderSide(color: AionexColors.crimson500, width: 1.5),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(borderRadius: radius),
          textStyle: const TextStyle(fontFamily: fontFamily, fontWeight: FontWeight.w600, fontSize: 16),
        ),
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: AionexColors.obsidian900,
        indicatorColor: AionexColors.crimson800,
      ),
    );
  }
}
