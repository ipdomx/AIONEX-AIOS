import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'src/app.dart';
import 'src/core/providers.dart';

Future<void> main() async {
  // Real paths on the web (…/reset-password?token=…), not #/ fragments, so the
  // links in emails and the browser history work. No-op on Android / iOS.
  usePathUrlStrategy();
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
