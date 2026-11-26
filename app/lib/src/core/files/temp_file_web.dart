import 'dart:typed_data';

/// Not used on the web (files are shared from memory there).
Future<String> writeTempFile(String filename, Uint8List bytes) async => throw UnsupportedError('web');
