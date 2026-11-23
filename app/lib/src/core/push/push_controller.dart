import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/notifications/notifications.dart';
import '../auth/session_controller.dart';
import '../firebase/firebase_setup.dart';
import '../providers.dart';
import '../router/app_router.dart';

/// Lets the push controller show a banner for messages that arrive while the
/// app is open (the system shows them when it is in the background).
final scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

enum PushStatus { unavailable, denied, enabled }

/// Real push on Android / iOS through Firebase Cloud Messaging. The device
/// token is registered with the backend as this user's "push" endpoint (stored
/// encrypted there) and removed again before sign-out, so a shared phone never
/// receives the previous user's notifications.
class PushController {
  PushController(this._ref);

  final Ref _ref;
  static const _tokenKey = 'aionex.push.token';
  static const _endpointKey = 'aionex.push.endpoint';
  final _subscriptions = <StreamSubscription<Object?>>[];
  PushStatus status = PushStatus.unavailable;

  Future<void> start() async {
    if (kIsWeb || !await ensureFirebase()) return;
    final messaging = FirebaseMessaging.instance;
    final settings = await messaging.requestPermission();
    if (settings.authorizationStatus == AuthorizationStatus.denied) {
      status = PushStatus.denied;
      return;
    }
    final token = await messaging.getToken();
    if (token != null) await _register(token);
    _cancel();
    _subscriptions
      ..add(messaging.onTokenRefresh.listen(_register))
      ..add(FirebaseMessaging.onMessage.listen(_showInApp))
      ..add(FirebaseMessaging.onMessageOpenedApp.listen((_) => _openInbox()));
    final initial = await messaging.getInitialMessage();
    if (initial != null) _openInbox();
    status = PushStatus.enabled;
  }

  Future<void> _register(String token) async {
    final prefs = _ref.read(sharedPreferencesProvider);
    if (prefs.getString(_tokenKey) == token && prefs.getString(_endpointKey) != null) return;
    try {
      final repo = _ref.read(notificationsRepositoryProvider);
      final previous = prefs.getString(_endpointKey);
      if (previous != null) await repo.removePushEndpoint(previous).catchError((Object _) {});
      final label = '${defaultTargetPlatform.name} app';
      final endpointId = await repo.registerPushToken(token, label);
      await prefs.setString(_tokenKey, token);
      if (endpointId != null) await prefs.setString(_endpointKey, endpointId);
    } on Object catch (error) {
      debugPrint('push registration failed: ${error.runtimeType}');
    }
  }

  void _showInApp(RemoteMessage message) {
    _ref.invalidate(notificationsProvider);
    final title = message.notification?.title;
    if (title == null) return;
    scaffoldMessengerKey.currentState?.showSnackBar(
      SnackBar(
        content: Text(title),
        action: SnackBarAction(label: '›', onPressed: _openInbox),
      ),
    );
  }

  void _openInbox() => _ref.read(routerProvider).go('/notifications');

  /// Called before sign-out while the session can still delete the endpoint.
  Future<void> stop() async {
    _cancel();
    final prefs = _ref.read(sharedPreferencesProvider);
    final endpointId = prefs.getString(_endpointKey);
    if (endpointId != null) {
      try {
        await _ref.read(notificationsRepositoryProvider).removePushEndpoint(endpointId);
      } on Object {
        // Already gone or offline: the server drops dead tokens on delivery.
      }
    }
    await prefs.remove(_endpointKey);
    await prefs.remove(_tokenKey);
    if (!kIsWeb && status == PushStatus.enabled) {
      try {
        await FirebaseMessaging.instance.deleteToken();
      } on Object {
        // Nothing else to clean up.
      }
    }
    status = PushStatus.unavailable;
  }

  void _cancel() {
    for (final subscription in _subscriptions) {
      unawaited(subscription.cancel());
    }
    _subscriptions.clear();
  }
}

final pushControllerProvider = Provider<PushController>((ref) {
  final controller = PushController(ref);
  ref.listen(sessionProvider, (previous, next) {
    final was = previous?.value is SignedIn;
    if (next.value is SignedIn && !was) unawaited(controller.start());
  }, fireImmediately: true);
  ref.onDispose(controller._cancel);
  return controller;
});
