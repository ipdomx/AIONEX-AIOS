import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';

/// Android / iOS: certificate pinning (MASVS-NETWORK-2).
///
/// The HTTP client trusts ONLY the root CAs in assets/security/api_roots.crt,
/// not the phone's certificate store, so a certificate from a user-installed or
/// rogue CA (a proxy, malware, a hostile network) is refused. Rejected
/// certificates are never overridden.
HttpClientAdapter? createPlatformAdapter({List<int>? trustedRoots}) {
  if (trustedRoots == null) return null;
  return IOHttpClientAdapter(
    createHttpClient: () {
      final context = SecurityContext(withTrustedRoots: false)..setTrustedCertificatesBytes(trustedRoots);
      return HttpClient(context: context)
        ..connectionTimeout = const Duration(seconds: 15)
        ..badCertificateCallback = ((certificate, host, port) => false);
    },
  );
}
