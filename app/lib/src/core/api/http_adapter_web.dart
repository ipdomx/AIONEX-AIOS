import 'package:dio/dio.dart';
import 'package:dio_web_adapter/dio_web_adapter.dart';

/// Web: send the backend's httpOnly session cookies with every request.
HttpClientAdapter? createPlatformAdapter() => BrowserHttpClientAdapter(withCredentials: true);
