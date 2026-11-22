import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'models.dart';

sealed class SessionState {
  const SessionState();
}

final class SignedOut extends SessionState {
  const SignedOut({this.expired = false});

  /// True when the server ended the session (show "sign in again").
  final bool expired;
}

final class SignedIn extends SessionState {
  const SignedIn(this.user);
  final AppUser user;
}

final sessionProvider = AsyncNotifierProvider<SessionController, SessionState>(SessionController.new);

class SessionController extends AsyncNotifier<SessionState> {
  @override
  Future<SessionState> build() async {
    ref.watch(apiClientProvider).onSessionLost = () {
      state = const AsyncData(SignedOut(expired: true));
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

  Future<void> verifyMfa(MfaChallenge challenge, String code) async {
    final user = await ref.read(authRepositoryProvider).completeMfa(challenge, code);
    state = AsyncData(SignedIn(user));
  }

  Future<void> reloadUser() async {
    final user = await ref.read(authRepositoryProvider).currentUser();
    state = AsyncData(SignedIn(user));
  }

  Future<void> signOut() async {
    await ref.read(authRepositoryProvider).logout();
    state = const AsyncData(SignedOut());
  }

  void retry() => ref.invalidateSelf();
}
