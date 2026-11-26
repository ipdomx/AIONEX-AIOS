import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'models.dart';

sealed class SessionState {
  const SessionState();
}

/// Why the user is looking at the sign-in screen, when it is worth saying.
enum SignOutNotice { expired, passwordChanged, mfaDisabled, accountDeleted }

final class SignedOut extends SessionState {
  const SignedOut({this.notice});

  final SignOutNotice? notice;

  /// True when the server ended the session (show "sign in again").
  bool get expired => notice == SignOutNotice.expired;
}

final class SignedIn extends SessionState {
  const SignedIn(this.user);
  final AppUser user;
}

final sessionProvider = AsyncNotifierProvider<SessionController, SessionState>(SessionController.new);

class SessionController extends AsyncNotifier<SessionState> {
  /// Set by the push controller (kept as a hook so the two providers do not
  /// depend on each other).
  static Future<void> Function()? beforeSignOut;

  @override
  Future<SessionState> build() async {
    ref.watch(apiClientProvider).onSessionLost = () {
      state = const AsyncData(SignedOut(notice: SignOutNotice.expired));
    };
    final user = await ref.read(authRepositoryProvider).restore();
    return user == null ? const SignedOut() : SignedIn(user);
  }

  /// Email and password. Returns the outcome so the screen can ask for MFA.
  Future<LoginOutcome> signIn(String email, String password) async {
    final outcome = await ref.read(authRepositoryProvider).login(email, password);
    if (outcome is LoginSucceeded) state = AsyncData(SignedIn(outcome.user));
    return outcome;
  }

  Future<void> register(RegistrationForm form) async {
    final user = await ref.read(authRepositoryProvider).register(form);
    state = AsyncData(SignedIn(user));
  }

  Future<void> verifyMfa(MfaChallenge challenge, String code) async {
    final user = await ref.read(authRepositoryProvider).completeMfa(challenge, code);
    state = AsyncData(SignedIn(user));
  }

  Future<void> reloadUser() async {
    final user = await ref.read(authRepositoryProvider).currentUser();
    state = AsyncData(SignedIn(user));
  }

  Future<void> signOut({SignOutNotice? notice}) async {
    // Remove this phone's push endpoint while the session can still do it.
    // After a password change the server already revoked it; that is fine.
    if (notice == null) await beforeSignOut?.call();
    await ref.read(authRepositoryProvider).logout();
    state = AsyncData(SignedOut(notice: notice));
  }

  void retry() => ref.invalidateSelf();
}
