import 'dart:convert';
import 'dart:typed_data';

import 'package:aionex/src/core/api/api_client.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:aionex/src/core/config/app_config.dart';
import 'package:dio/dio.dart';

typedef Handler = Future<ResponseBody> Function(RequestOptions request);

/// An in-memory backend: every request is recorded and answered by [handler].
class FakeAdapter implements HttpClientAdapter {
  FakeAdapter(this.handler);

  Handler handler;
  final List<RequestOptions> requests = [];

  List<String> get paths => [for (final r in requests) r.uri.path];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    requests.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody jsonBody(int status, Object body, {Map<String, List<String>> headers = const {}}) {
  return ResponseBody.fromString(
    jsonEncode(body),
    status,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      ...headers,
    },
  );
}

Map<String, Object?> userJson({String role = 'Free User', String name = 'Ahmed'}) => {
      'id': 'u1',
      'email': 'user@example.com',
      'name': name,
      'role': role,
      'status': 'active',
      'permissions': <String>[],
      'organization': {'id': 'o1', 'name': 'Personal', 'plan': 'Free'},
    };

Map<String, Object?> grantJson({String access = 'access-1', String refresh = 'refresh-1', String role = 'Free User'}) => {
      'access_token': access,
      'refresh_token': refresh,
      'token_type': 'bearer',
      'expires_in': 900,
      'user': userJson(role: role),
    };

final testConfig = AppConfig(apiBaseUrl: Uri.parse('https://api.example.test/api/v1'), appVersion: 'test');

ApiClient fakeClient(FakeAdapter adapter, SessionStore store) {
  return ApiClient(config: testConfig, store: store, adapter: adapter);
}
