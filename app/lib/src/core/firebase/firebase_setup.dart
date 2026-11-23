import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Firebase client settings for the phone apps, injected at build time
/// (`--dart-define-from-file`), never committed. They identify the app to
/// Firebase and are public by design; the server-side admin credentials never
/// leave the backend. Without them, SMS sign-up and push are simply off.
@immutable
class NativeFirebaseConfig {
  const NativeFirebaseConfig({
    required this.apiKey,
    required this.appId,
    required this.senderId,
    required this.projectId,
    this.iosBundleId,
  });

  final String apiKey;
  final String appId;
  final String senderId;
  final String projectId;
  final String? iosBundleId;

  static NativeFirebaseConfig? fromEnvironment() {
    const apiKey = String.fromEnvironment('AIONEX_FB_API_KEY');
    const appId = String.fromEnvironment('AIONEX_FB_APP_ID');
    const senderId = String.fromEnvironment('AIONEX_FB_SENDER_ID');
    const projectId = String.fromEnvironment('AIONEX_FB_PROJECT_ID');
    const bundle = String.fromEnvironment('AIONEX_FB_IOS_BUNDLE_ID');
    if (apiKey.isEmpty || appId.isEmpty || senderId.isEmpty || projectId.isEmpty) return null;
    return const NativeFirebaseConfig(
      apiKey: apiKey,
      appId: appId,
      senderId: senderId,
      projectId: projectId,
      iosBundleId: bundle == '' ? null : bundle,
    );
  }

  FirebaseOptions get options => FirebaseOptions(
        apiKey: apiKey,
        appId: appId,
        messagingSenderId: senderId,
        projectId: projectId,
        iosBundleId: iosBundleId,
      );
}

Future<bool>? _initialising;

/// Start Firebase once on Android / iOS. Returns false on the web (the website
/// handles SMS sign-up there) or when the build carries no Firebase settings.
Future<bool> ensureFirebase() => _initialising ??= _initialise();

Future<bool> _initialise() async {
  if (kIsWeb) return false;
  final config = NativeFirebaseConfig.fromEnvironment();
  if (config == null) return false;
  try {
    if (Firebase.apps.isEmpty) await Firebase.initializeApp(options: config.options);
    return true;
  } on Object catch (error) {
    debugPrint('Firebase could not start: ${error.runtimeType}');
    return false;
  }
}

final firebaseReadyProvider = FutureProvider<bool>((ref) => ensureFirebase());

/// SMS verification of a phone number, ending in a Firebase ID token that the
/// backend verifies (exactly what the website sends as firebase_id_token).
abstract interface class PhoneVerifier {
  /// Sends the SMS. Completes with a token straight away when Android reads the
  /// SMS by itself, otherwise null and the user types the code.
  Future<String?> sendCode(String phoneNumber);

  Future<String> confirmCode(String code);
}

class FirebasePhoneVerifier implements PhoneVerifier {
  String? _verificationId;
  int? _resendToken;

  @override
  Future<String?> sendCode(String phoneNumber) async {
    if (!await ensureFirebase()) throw StateError('phone-verification-unavailable');
    final auth = FirebaseAuth.instance;
    final result = Completer<String?>();
    await auth.verifyPhoneNumber(
      phoneNumber: phoneNumber,
      forceResendingToken: _resendToken,
      timeout: const Duration(seconds: 60),
      verificationCompleted: (credential) async {
        if (result.isCompleted) return;
        try {
          result.complete(await _token(credential));
        } on Object catch (error, stack) {
          result.completeError(error, stack);
        }
      },
      verificationFailed: (error) {
        if (!result.isCompleted) result.completeError(error);
      },
      codeSent: (verificationId, resendToken) {
        _verificationId = verificationId;
        _resendToken = resendToken;
        if (!result.isCompleted) result.complete(null);
      },
      codeAutoRetrievalTimeout: (verificationId) => _verificationId = verificationId,
    );
    return result.future;
  }

  @override
  Future<String> confirmCode(String code) {
    final id = _verificationId;
    if (id == null) throw StateError('no-code-sent');
    return _token(PhoneAuthProvider.credential(verificationId: id, smsCode: code.trim()));
  }

  /// The Firebase session is only a vehicle for the ID token: it is signed out
  /// at once, and AIONEX issues its own session after registration.
  Future<String> _token(PhoneAuthCredential credential) async {
    final auth = FirebaseAuth.instance;
    final signedIn = await auth.signInWithCredential(credential);
    final token = await signedIn.user?.getIdToken(true);
    await auth.signOut();
    if (token == null || token.isEmpty) throw StateError('no-id-token');
    return token;
  }
}

final phoneVerifierProvider = Provider<PhoneVerifier>((ref) => FirebasePhoneVerifier());
