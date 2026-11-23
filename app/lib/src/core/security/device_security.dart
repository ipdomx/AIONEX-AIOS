import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Local signals about the device. They inform the user and gate risky actions
/// (payments in N-07); the server remains the authority on every request.
@immutable
class DeviceIntegrity {
  const DeviceIntegrity({
    required this.compromised,
    required this.emulator,
    required this.debugBuild,
    required this.signals,
  });

  /// Nothing could be checked (web, or the platform did not answer).
  static const unknown = DeviceIntegrity(compromised: false, emulator: false, debugBuild: false, signals: []);

  final bool compromised;
  final bool emulator;
  final bool debugBuild;
  final List<String> signals;

  factory DeviceIntegrity.fromMap(Map<Object?, Object?> map) {
    final signals = map['signals'];
    return DeviceIntegrity(
      compromised: map['compromised'] == true,
      emulator: map['emulator'] == true,
      debugBuild: map['debugBuild'] == true,
      signals: signals is List ? signals.whereType<String>().toList(growable: false) : const [],
    );
  }
}

/// The native side lives in MainActivity.kt (Android) and AppDelegate.swift (iOS).
class DeviceSecurity {
  DeviceSecurity({MethodChannel? channel}) : _channel = channel ?? const MethodChannel('net.vipe.aionex/security');

  final MethodChannel _channel;
  int _secureScreens = 0;

  /// Mark a screen as sensitive (sign-in, codes, payment). Nested screens are
  /// counted, so leaving one sensitive screen never unprotects another.
  Future<void> enterSecureScreen() async {
    _secureScreens++;
    if (_secureScreens == 1) await _invoke<void>('setSecure', true);
  }

  Future<void> leaveSecureScreen() async {
    if (_secureScreens == 0) return;
    _secureScreens--;
    if (_secureScreens == 0) await _invoke<void>('setSecure', false);
  }

  bool get hasSecureScreen => _secureScreens > 0;

  Future<DeviceIntegrity> integrity() async {
    final result = await _invoke<Map<Object?, Object?>>('integrity');
    return result == null ? DeviceIntegrity.unknown : DeviceIntegrity.fromMap(result);
  }

  Future<T?> _invoke<T>(String method, [Object? argument]) async {
    if (kIsWeb) return null;
    try {
      return await _channel.invokeMethod<T>(method, argument);
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }
}

final deviceSecurityProvider = Provider<DeviceSecurity>((ref) => DeviceSecurity());

final deviceIntegrityProvider = FutureProvider<DeviceIntegrity>((ref) {
  return ref.watch(deviceSecurityProvider).integrity();
});

/// Wrap a sensitive screen: Android keeps it out of screenshots, recordings and
/// the recent-apps preview (FLAG_SECURE) while it is shown.
class SecureScreen extends ConsumerStatefulWidget {
  const SecureScreen({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<SecureScreen> createState() => _SecureScreenState();
}

class _SecureScreenState extends ConsumerState<SecureScreen> {
  late final DeviceSecurity _security;

  @override
  void initState() {
    super.initState();
    _security = ref.read(deviceSecurityProvider);
    _security.enterSecureScreen();
  }

  @override
  void dispose() {
    _security.leaveSecureScreen();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// Covers the whole app while it is not in the foreground, so the app-switcher
/// snapshot (iOS and Android) never shows account data (MASVS-PLATFORM-3).
class PrivacyShield extends StatefulWidget {
  const PrivacyShield({super.key, required this.child, required this.cover});

  final Widget child;
  final Widget cover;

  @override
  State<PrivacyShield> createState() => _PrivacyShieldState();
}

class _PrivacyShieldState extends State<PrivacyShield> {
  late final AppLifecycleListener _listener;
  bool _hidden = false;

  @override
  void initState() {
    super.initState();
    _listener = AppLifecycleListener(onStateChange: _onState);
  }

  void _onState(AppLifecycleState state) {
    final hidden = state != AppLifecycleState.resumed;
    if (hidden != _hidden && mounted) setState(() => _hidden = hidden);
  }

  @override
  void dispose() {
    _listener.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // The web has no app switcher snapshot, and hiding on blur would be noise.
    if (kIsWeb) return widget.child;
    return Stack(
      fit: StackFit.expand,
      children: [
        widget.child,
        if (_hidden) Positioned.fill(child: widget.cover),
      ],
    );
  }
}
