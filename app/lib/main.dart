import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'src/app.dart';
import 'src/core/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final preferences = await SharedPreferences.getInstance();
  final pinnedRoots = kIsWeb ? null : (await rootBundle.load('assets/security/api_roots.crt')).buffer.asUint8List();
  runApp(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(preferences),
        pinnedRootsProvider.overrideWithValue(pinnedRoots),
      ],
      child: const AionexApp(),
    ),
  );
}
