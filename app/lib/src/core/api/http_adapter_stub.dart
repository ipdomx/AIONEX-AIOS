import 'package:dio/dio.dart';

/// Android / iOS keep Dio's default adapter (certificate pinning hooks in here in N-02).
HttpClientAdapter? createPlatformAdapter() => null;
