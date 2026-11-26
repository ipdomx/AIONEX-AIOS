import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';

/// Writes into the app's private cache (removed by the OS when space is needed).
Future<String> writeTempFile(String filename, Uint8List bytes) async {
  final directory = Directory('${(await getTemporaryDirectory()).path}/shared');
  await directory.create(recursive: true);
  final safe = filename.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
  final file = File('${directory.path}/${safe.isEmpty ? 'download' : safe}');
  await file.writeAsBytes(bytes, flush: true);
  return file.path;
}
