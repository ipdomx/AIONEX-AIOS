import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../auth/session_store.dart';
import '../config/app_config.dart';
import 'api_exception.dart';
import 'http_adapter_io.dart' if (dart.library.js_interop) 'http_adapter_web.dart';

/// The one HTTP client for the AIONEX API.
///
/// * Adds the bearer token on Android / iOS; on the web the browser sends the
///   httpOnly cookies instead.
/// * On a 401 it refreshes the session once and replays the request once.
///   Concurrent 401s share a single refresh, and a failed refresh ends the
///   session instead of looping (the same rules as vip-frontend's refresh gate).
/// * Every failure surfaces as an [ApiException].
class ApiClient {
  ApiClient({
    required AppConfig config,
    required this.store,
    HttpClientAdapter? adapter,
    List<int>? trustedRoots,
  })  : _dio = Dio(
          BaseOptions(
            baseUrl: config.apiBaseUrl.toString(),
            connectTimeout: const Duration(seconds: 15),
            sendTimeout: const Duration(seconds: 30),
            receiveTimeout: const Duration(seconds: 60),
            responseType: ResponseType.json,
            followRedirects: false,
            headers: {
              'Accept': 'application/json',
              // Phones send no Origin, so name the public channel (never the owner
              // console) explicitly. The browser's Origin already says it on the web,
              // and extra headers there would fail the backend's CORS allow-list.
              if (!kIsWeb) ...{
                'X-AIOS-Auth-Channel': 'public',
                'X-AIOS-Client': 'aionex-app/${config.appVersion}',
              },
            },
          ),
        ) {
    final platformAdapter = adapter ?? createPlatformAdapter(trustedRoots: trustedRoots);
    if (platformAdapter != null) {
      _dio.httpClientAdapter = platformAdapter;
    } else if (kReleaseMode && !kIsWeb) {
      // A release build must never talk to the API without pinning.
      throw StateError('ApiClient needs the pinned root certificates');
    }
  }

  final Dio _dio;

  /// Where the session lives (Keychain / Keystore, or browser cookies).
  final SessionStore store;
  Future<bool>? _refreshing;

  /// Called once when the session can no longer be refreshed.
  void Function()? onSessionLost;

  Future<Map<String, Object?>> getJson(String path, {Map<String, Object?>? query, bool auth = true}) {
    return _json(_Call(path, 'GET', query: query), auth: auth);
  }

  Future<Map<String, Object?>> postJson(String path, {Object? body, bool auth = true, bool retry = true}) {
    return _json(
      _Call(path, 'POST', data: body ?? const <String, Object?>{}, contentType: Headers.jsonContentType),
      auth: auth,
      retry: retry,
    );
  }

  Future<Map<String, Object?>> postForm(String path, Map<String, String> fields, {bool auth = false}) {
    return _json(
      _Call(path, 'POST', data: fields, contentType: Headers.formUrlEncodedContentType),
      auth: auth,
      retry: false,
    );
  }

  Future<Map<String, Object?>> _json(
    _Call call, {
    required bool auth,
    bool retry = true,
  }) async {
    final response = await _send(call, auth: auth, retry: retry);
    final data = response.data;
    if (data == null || data == '') return const {};
    if (data is Map<String, Object?>) return data;
    if (data is Map) return data.cast<String, Object?>();
    throw ApiException(
      failure: ApiFailure.unknown,
      message: 'Unexpected response body',
      statusCode: response.statusCode,
    );
  }

  Future<Response<Object?>> _send(
    _Call call, {
    required bool auth,
    required bool retry,
  }) async {
    final token = auth ? store.accessToken : null;
    try {
      return await _dio.request<Object?>(
        call.path,
        data: call.data,
        queryParameters: call.query,
        options: Options(
          method: call.method,
          contentType: call.contentType,
          headers: token == null ? null : {'Authorization': 'Bearer $token'},
        ),
      );
    } on DioException catch (error) {
      if (auth && retry && error.response?.statusCode == 401 && await refreshSession()) {
        return _send(call, auth: auth, retry: false);
      }
      throw ApiException.fromDio(error);
    }
  }

  /// Refresh the session. Returns true when a fresh session is in place.
  Future<bool> refreshSession() {
    return _refreshing ??= _performRefresh().whenComplete(() => _refreshing = null);
  }

  Future<bool> _performRefresh() async {
    final refreshToken = await store.readRefreshToken();
    if (!store.usesCookies && refreshToken == null) return false;
    try {
      final response = await _dio.post<Object?>(
        '/auth/refresh',
        data: store.usesCookies ? const <String, Object?>{} : {'refresh_token': refreshToken},
        options: Options(contentType: Headers.jsonContentType),
      );
      final data = response.data;
      final access = data is Map ? data['access_token'] : null;
      final refresh = data is Map ? data['refresh_token'] : null;
      if (access is! String || refresh is! String) return false;
      await store.save(accessToken: access, refreshToken: refresh);
      return true;
    } on DioException catch (error) {
      final status = error.response?.statusCode;
      // Only a definite rejection ends the session. A dropped connection or a
      // server error keeps it, and the caller sees that failure instead.
      if (status == 401 || status == 403) {
        await store.clear();
        onSessionLost?.call();
        return false;
      }
      if (status == null || status >= 500 || status == 429) throw ApiException.fromDio(error);
      return false;
    }
  }
}

class _Call {
  const _Call(this.path, this.method, {this.data, this.query, this.contentType});

  final String path;
  final String method;
  final Object? data;
  final Map<String, Object?>? query;
  final String? contentType;
}
