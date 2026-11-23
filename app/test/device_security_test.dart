import 'package:aionex/src/core/security/device_security.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('net.vipe.aionex/security');
  final calls = <MethodCall>[];

  void answer(Object? Function(MethodCall call) handler) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return handler(call);
    });
  }

  setUp(calls.clear);
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, null);
  });

  test('nested sensitive screens switch protection on once and off once', () async {
    answer((_) => null);
    final security = DeviceSecurity();

    await security.enterSecureScreen();
    await security.enterSecureScreen();
    await security.leaveSecureScreen();
    expect(security.hasSecureScreen, isTrue);
    await security.leaveSecureScreen();
    await security.leaveSecureScreen(); // extra leave is harmless

    expect(calls.map((c) => '${c.method}:${c.arguments}'), ['setSecure:true', 'setSecure:false']);
  });

  test('integrity signals are read from the platform', () async {
    answer((_) => {
          'platform': 'android',
          'compromised': true,
          'emulator': false,
          'debugBuild': false,
          'signals': ['su_binary', 'hooking_framework'],
        });

    final integrity = await DeviceSecurity().integrity();

    expect(integrity.compromised, isTrue);
    expect(integrity.signals, ['su_binary', 'hooking_framework']);
  });

  test('a platform without the channel reports unknown, never a crash', () async {
    final integrity = await DeviceSecurity().integrity();
    expect(integrity.compromised, isFalse);
    expect(integrity.signals, isEmpty);
  });
}
