import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/login_page.dart';
import '../../features/auth/mfa_page.dart';
import '../../features/auth/splash_page.dart';
import '../../features/home/dashboard_page.dart';
import '../../features/home/home_shell.dart';
import '../../features/profile/profile_page.dart';
import '../auth/models.dart';
import '../auth/session_controller.dart';
import '../security/device_security.dart';

/// Where a user may be, given the session. Pure, so it is unit-tested directly.
String? redirectFor(AsyncValue<SessionState> session, String location) {
  final onAuth = location == '/login' || location.startsWith('/login/');
  if (session.isLoading && !session.hasValue || session.hasError) {
    return location == '/splash' ? null : '/splash';
  }
  return switch (session.value) {
    SignedIn() => onAuth || location == '/splash' ? '/' : null,
    _ => onAuth ? null : '/login',
  };
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  final router = GoRouter(
    initialLocation: '/splash',
    refreshListenable: refresh,
    debugLogDiagnostics: kDebugMode,
    redirect: (context, state) => redirectFor(ref.read(sessionProvider), state.matchedLocation),
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const SplashPage()),
      GoRoute(
        path: '/login',
        builder: (context, state) => const SecureScreen(child: LoginPage()),
        routes: [
          GoRoute(
            path: 'mfa',
            redirect: (context, state) => state.extra is MfaChallenge ? null : '/login',
            builder: (context, state) => SecureScreen(child: MfaPage(challenge: state.extra! as MfaChallenge)),
          ),
        ],
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => HomeShell(navigationShell: shell),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/', builder: (context, state) => const DashboardPage())]),
          StatefulShellBranch(
            routes: [GoRoute(path: '/profile', builder: (context, state) => const ProfilePage())],
          ),
        ],
      ),
    ],
  );
  ref.onDispose(router.dispose);
  return router;
});
