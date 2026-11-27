import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/academy/academy_page.dart';
import '../../features/ads/ads_page.dart';
import '../../features/auth/login_page.dart';
import '../../features/auth/mfa_page.dart';
import '../../features/auth/password_recovery_pages.dart';
import '../../features/auth/register_page.dart';
import '../../features/auth/splash_page.dart';
import '../../features/billing/billing_page.dart';
import '../../features/conversations/conversation_page.dart';
import '../../features/conversations/conversations_page.dart';
import '../../features/home/dashboard_page.dart';
import '../../features/home/home_shell.dart';
import '../../features/notifications/notification_settings_page.dart';
import '../../features/notifications/notifications.dart';
import '../../features/profile/account_security_page.dart';
import '../../features/profile/profile_page.dart';
import '../../features/projects/project_execution.dart';
import '../../features/projects/projects_page.dart';
import '../../features/realtime/realtime_page.dart';
import '../../features/security_lab/security_lab_page.dart';
import '../../features/social/social_inbox.dart';
import '../../features/social/social_page.dart';
import '../../features/studio/studio_page.dart';
import '../../features/support/support_pages.dart';
import '../../features/three_d/three_d_page.dart';
import '../auth/models.dart';
import '../auth/session_controller.dart';
import '../security/device_security.dart';

/// Where a user may be, given the session. Pure, so it is unit-tested directly.
///
/// A deep link opened before the session is known (or while signed out) is kept
/// in `?from=` and honoured once the user is signed in.
String? redirectFor(AsyncValue<SessionState> session, Uri uri) {
  final location = uri.path;
  // The emailed recovery link works whether or not someone is signed in.
  if (location == '/reset-password') return null;
  final onAuth = location == '/login' || location.startsWith('/login/');
  final from = _safeFrom(uri.queryParameters['from']);
  String withFrom(String target) {
    if (location == '/splash' || onAuth || location == '/') return from == null ? target : '$target?from=${Uri.encodeComponent(from)}';
    return '$target?from=${Uri.encodeComponent(uri.toString())}';
  }

  if (session.isLoading && !session.hasValue || session.hasError) {
    return location == '/splash' ? null : withFrom('/splash');
  }
  return switch (session.value) {
    SignedIn() => onAuth || location == '/splash' ? (from ?? '/') : null,
    _ => onAuth ? null : withFrom('/login'),
  };
}

/// Only in-app paths may be followed after sign-in (never another site).
String? _safeFrom(String? value) {
  if (value == null || !value.startsWith('/') || value.startsWith('//')) return null;
  final path = Uri.tryParse(value)?.path ?? '';
  if (path == '/splash' || path == '/login' || path.startsWith('/login/')) return null;
  return value;
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  final router = GoRouter(
    initialLocation: '/splash',
    refreshListenable: refresh,
    debugLogDiagnostics: kDebugMode,
    redirect: (context, state) => redirectFor(ref.read(sessionProvider), state.uri),
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const SplashPage()),
      GoRoute(
        path: '/login',
        builder: (context, state) => const SecureScreen(child: LoginPage()),
        routes: [
          GoRoute(path: 'forgot', builder: (context, state) => const ForgotPasswordPage()),
          GoRoute(
            path: 'register',
            builder: (context, state) => SecureScreen(
              child: RegisterPage(social: state.extra is SocialRegistration ? state.extra! as SocialRegistration : null),
            ),
          ),
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
                    path: 'notifications',
                    builder: (context, state) => const NotificationsPage(),
                    routes: [
                      GoRoute(path: 'settings', builder: (context, state) => const NotificationSettingsPage()),
                    ],
                  ),
                  GoRoute(path: 'studio', builder: (context, state) => const StudioPage()),
                  GoRoute(path: 'academy', builder: (context, state) => const AcademyPage()),
                  GoRoute(path: 'ads', builder: (context, state) => const AdsPage()),
                  GoRoute(path: 'billing', builder: (context, state) => const BillingPage()),
                  GoRoute(path: 'realtime', builder: (context, state) => const RealtimePage()),
                  GoRoute(
                    path: 'security-lab',
                    builder: (context, state) => const SecurityLabPage(),
                    routes: [
                      GoRoute(
                        path: 'scans/:scanId',
                        builder: (context, state) => SecurityScanPage(
                          scanId: state.pathParameters['scanId']!,
                          origin: state.uri.queryParameters['origin'] ?? '',
                        ),
                      ),
                    ],
                  ),
                  GoRoute(
                    path: 'social',
                    builder: (context, state) => const SocialPage(),
                    routes: [
                      GoRoute(
                        path: 'inbox/:conversationId',
                        builder: (context, state) => InboxThreadPage(conversationId: state.pathParameters['conversationId']!),
                      ),
                    ],
                  ),
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
            routes: [
              GoRoute(
                path: '/projects',
                builder: (context, state) => const ProjectsPage(),
                routes: [
                  GoRoute(
                    path: ':projectId',
                    builder: (context, state) => ProjectDetailPage(projectId: state.pathParameters['projectId']!),
                  ),
                  GoRoute(
                    path: ':projectId/3d',
                    builder: (context, state) => ThreeDPage(projectId: state.pathParameters['projectId']!),
                  ),
                ],
              ),
            ],
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
