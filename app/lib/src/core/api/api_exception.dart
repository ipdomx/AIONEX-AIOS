import 'package:dio/dio.dart';

/// What went wrong, in the terms the screens need to pick a message.
enum ApiFailure {
  network,
  unauthorized,
  forbidden,
  notFound,
  conflict,
  validation,
  rateLimited,
  server,
  unknown,
}

/// A failed API call, with the backend's own message and code when it sent one.
/// Mirrors ApiError in vip-frontend/src/lib/api.ts so both clients read the
/// same FastAPI error shapes.
class ApiException implements Exception {
  const ApiException({
    required this.failure,
    required this.message,
    this.statusCode,
    this.code,
    this.retryAfter,
  });

  final ApiFailure failure;
  final String message;
  final int? statusCode;
  final String? code;
  final Duration? retryAfter;

  factory ApiException.fromDio(DioException error) {
    final response = error.response;
    if (response == null) {
      return ApiException(
        failure: ApiFailure.network,
        message: error.message ?? 'Network request failed',
      );
    }
    return ApiException.fromResponse(
      statusCode: response.statusCode ?? 0,
      payload: response.data,
      retryAfterHeader: response.headers.value('retry-after'),
    );
  }

  factory ApiException.fromResponse({
    required int statusCode,
    Object? payload,
    String? retryAfterHeader,
  }) {
    final object = payload is Map ? payload : null;
    final detail = object != null && object.containsKey('detail') ? object['detail'] : payload;
    final detailObject = detail is Map ? detail : null;
    final code = detailObject?['code'] ?? object?['code'];
    final message = (detail is List ? _validationMessage(detail) : null) ??
        _string(detailObject?['message']) ??
        _string(detail) ??
        _string(object?['message']) ??
        'Request failed with status $statusCode';
    return ApiException(
      failure: failureFor(statusCode),
      message: message,
      statusCode: statusCode,
      code: code is String ? code : null,
      retryAfter: _retryAfter(retryAfterHeader),
    );
  }

  static ApiFailure failureFor(int statusCode) {
    return switch (statusCode) {
      401 => ApiFailure.unauthorized,
      403 => ApiFailure.forbidden,
      404 => ApiFailure.notFound,
      409 => ApiFailure.conflict,
      400 || 422 => ApiFailure.validation,
      429 => ApiFailure.rateLimited,
      >= 500 => ApiFailure.server,
      _ => ApiFailure.unknown,
    };
  }

  static String? _string(Object? value) => value is String && value.isNotEmpty ? value : null;

  // FastAPI validation errors arrive as a list; name the field instead of a bare status.
  static String? _validationMessage(List<Object?> items) {
    final parts = <String>[];
    for (final item in items) {
      if (item is! Map) continue;
      final loc = item['loc'];
      final msg = item['msg'];
      final location = loc is List ? loc.where((part) => part != 'body').join('.') : '';
      if (msg is String && msg.isNotEmpty) {
        parts.add(location.isEmpty ? msg : '$location: $msg');
      }
    }
    return parts.isEmpty ? null : parts.take(3).join(' | ');
  }

  static Duration? _retryAfter(String? header) {
    if (header == null) return null;
    final seconds = int.tryParse(header.trim());
    if (seconds == null || seconds < 0) return null;
    return Duration(seconds: seconds.clamp(0, 3600));
  }

  @override
  String toString() => 'ApiException($failure, $statusCode, $code): $message';
}
