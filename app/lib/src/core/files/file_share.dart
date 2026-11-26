import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../api/api_client.dart';
import 'temp_file_io.dart' if (dart.library.js_interop) 'temp_file_web.dart';

/// Hand a downloaded file to the user: the phone's share sheet (save to Files,
/// open in another app, send), or a browser download on the web.
Future<void> shareDownloadedFile(DownloadedFile file) async {
  final bytes = Uint8List.fromList(file.bytes);
  final XFile xfile = kIsWeb
      ? XFile.fromData(bytes, name: file.filename, mimeType: file.mediaType)
      : XFile(await writeTempFile(file.filename, bytes), name: file.filename, mimeType: file.mediaType);
  await SharePlus.instance.share(ShareParams(files: [xfile], fileNameOverrides: [file.filename]));
}

/// Overridable in tests (the share sheet and file system are platform plugins).
final fileSharerProvider = Provider<Future<void> Function(DownloadedFile file)>((ref) => shareDownloadedFile);
