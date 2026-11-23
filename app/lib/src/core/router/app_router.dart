import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/login_page.dart';
import '../../features/auth/mfa_page.dart';
import '../../features/auth/password_recovery_pages.dart';
import '../../features/auth/splash_page.dart';
import '../../features/conversations/conversation_page.dart';
import '../../features/conversations/conversations_page.dart';
import '../../features/home/dashboard_page.dart';
import '../../features/home/home_shell.dart';
import '../../features/profile/account_security_page.dart';
import '../../features/profile/profile_page.dart';
import '../../features/projects/projects_page.dart';
import '../../features/support/support_pages.dart';
import '../auth/models.dart';
import '../auth/session_controller.dart';
import '../security/device_security.dart';

/// Where a user may be, given the session. Pure, so it is unit-tested directly.
String? redirectFor(AsyncValue<SessionState> session, String location) {
  // The emailed recovery link works whether or not someone is signed in.
  if (location == '/reset-password') return null;
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
          GoRoute(path: 'forgot', builder: (context, state) => const ForgotPasswordPage()),
          GoRoute(
            path: 'mfa',
            redirect: (context, state) => state.extra is MfaChallenge ? null : '/login',
            builder: (context, state) => SecureScreen(child: MfaPage(challenge: state.extra! as MfaChallenge)),
          ),
        ],
      ),
      GoRoute(
        path: '/reset-password',
        builder: (context, state) =>
            SecureScreen(child: ResetPasswordPage(token: state.uri.queryParameters['token'] ?? '')),
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => HomeShell(navigationShell: shell),
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/',
                builder: (context, state) => const DashboardPage(),
                routes: [
                  GoRoute(
                    path: 'support',
                    builder: (context, state) => const SupportPage(),
                    routes: [
                      GoRoute(
                        path: ':ticketId',
                        builder: (context, state) => SupportTicketPage(ticketId: state.pathParameters['ticketId']!),
                      ),
                    ],
                  ),
                ],
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [GoRoute(path: '/projects', builder: (context, state) => const ProjectsPage())],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/conversations',
                builder: (context, state) => ConversationsPage(projectId: state.uri.queryParameters['project']),
                routes: [
                  GoRoute(
                    path: ':conversationId',
                    builder: (context, state) =>
                        ConversationPage(conversationId: state.pathParameters['conversationId']!),
                  ),
                ],
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/profile',
                builder: (context, state) => const ProfilePage(),
                routes: [
                  GoRoute(
                    path: 'security',
                    builder: (context, state) => const SecureScreen(child: AccountSecurityPage()),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    ],
  );
  ref.onDispose(router.dispose);
  return router;
});
