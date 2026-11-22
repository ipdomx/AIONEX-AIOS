import 'package:aionex/src/core/api/api_exception.dart';
import 'package:aionex/src/core/auth/session_store.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_api.dart';

void main() {
  test('sends the bearer token and the public channel header to the configured base', () async {
    final adapter = FakeAdapter((request) async => jsonBody(200, userJson()));
    final client = fakeClient(adapter, MemorySessionStore(accessToken: 'a1', refreshToken: 'r1'));

    await client.getJson('/auth/me');

    final request = adapter.requests.single;
    expect(request.uri.toString(), 'https://api.example.test/api/v1/auth/me');
    expect(request.headers['Authorization'], 'Bearer a1');
    expect(request.headers['X-AIOS-Auth-Channel'], 'public');
  });

  test('a 401 refreshes once and replays the request with the new token', () async {
    final store = MemorySessionStore(accessToken: 'old', refreshToken: 'r1');
    final adapter = FakeAdapter((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        expect(request.data, {'refresh_token': 'r1'});
        return jsonBody(200, grantJson(access: 'new', refresh: 'r2'));
      }
      return request.headers['Authorization'] == 'Bearer new'
          ? jsonBody(200, {'ok': true})
          : jsonBody(401, {'detail': 'expired'});
    });
    final client = fakeClient(adapter, store);

    final result = await client.getJson('/projects');

    expect(result, {'ok': true});
    expect(adapter.paths, ['/api/v1/projects', '/api/v1/auth/refresh', '/api/v1/projects']);
    expect(store.refreshToken, 'r2');
  });

  test('concurrent 401s share a single refresh', () async {
    final store = MemorySessionStore(accessToken: 'old', refreshToken: 'r1');
    final adapter = FakeAdapter((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
        return jsonBody(200, grantJson(access: 'new', refresh: 'r2'));
      }
      return request.headers['Authorization'] == 'Bearer new'
          ? jsonBody(200, {'ok': true})
          : jsonBody(401, {'detail': 'expired'});
    });
    final client = fakeClient(adapter, store);

    await Future.wait([client.getJson('/a'), client.getJson('/b'), client.getJson('/c')]);

    expect(adapter.paths.where((path) => path.endsWith('/auth/refresh')), hasLength(1));
  });

  test('a rejected refresh ends the session instead of looping', () async {
    final store = MemorySessionStore(accessToken: 'old', refreshToken: 'r1');
    var lost = 0;
    final adapter = FakeAdapter((request) async => jsonBody(401, {'detail': 'Invalid refresh token'}));
    final client = fakeClient(adapter, store)..onSessionLost = () => lost++;

    await expectLater(
      client.getJson('/projects'),
      throwsA(isA<ApiException>().having((e) => e.failure, 'failure', ApiFailure.unauthorized)),
    );
    expect(adapter.paths, ['/api/v1/projects', '/api/v1/auth/refresh']);
    expect(store.refreshToken, isNull);
    expect(lost, 1);
  });

  test('a dropped connection during refresh keeps the saved session', () async {
    final store = MemorySessionStore(accessToken: 'old', refreshToken: 'r1');
    final adapter = FakeAdapter((request) async {
      if (request.uri.path.endsWith('/auth/refresh')) {
        throw DioException.connectionError(requestOptions: request, reason: 'offline');
      }
      return jsonBody(401, {'detail': 'expired'});
    });
    final client = fakeClient(adapter, store);

    await expectLater(
      client.getJson('/projects'),
      throwsA(isA<ApiException>().having((e) => e.failure, 'failure', ApiFailure.network)),
    );
    expect(store.refreshToken, 'r1');
  });

  test('backend error shapes become readable messages', () {
    final validation = ApiException.fromResponse(
      statusCode: 422,
      payload: {
        'detail': [
          {'loc': ['body', 'email'], 'msg': 'value is not a valid email address'},
        ],
      },
    );
    expect(validation.failure, ApiFailure.validation);
    expect(validation.message, 'email: value is not a valid email address');

    final coded = ApiException.fromResponse(
      statusCode: 429,
      payload: {
        'detail': {'code': 'rate_limited', 'message': 'Slow down'},
      },
      retryAfterHeader: '30',
    );
    expect(coded.failure, ApiFailure.rateLimited);
    expect(coded.code, 'rate_limited');
    expect(coded.message, 'Slow down');
    expect(coded.retryAfter, const Duration(seconds: 30));
  });
}
