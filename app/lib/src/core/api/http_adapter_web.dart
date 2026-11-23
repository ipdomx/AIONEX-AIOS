import 'package:dio/dio.dart';
import 'package:dio_web_adapter/dio_web_adapter.dart';

/// Web: send the backend's httpOnly session cookies with every request.
/// Certificate checks stay with the browser (pinning is not possible there).
HttpClientAdapter? createPlatformAdapter({List<int>? trustedRoots}) => BrowserHttpClientAdapter(withCredentials: true);
