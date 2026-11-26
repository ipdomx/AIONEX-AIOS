import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../core/auth/session_controller.dart';
import '../../widgets/async_view.dart';
import '../../widgets/notice.dart';
import '../auth/password_recovery_pages.dart';
import 'live_call.dart';
import 'realtime_repository.dart';

/// Voice and video rooms (LiveKit), recordings with every participant's consent.
class RealtimePage extends ConsumerStatefulWidget {
  const RealtimePage({super.key, this.pollInterval = const Duration(seconds: 4)});

  final Duration pollInterval;

  @override
  ConsumerState<RealtimePage> createState() => _RealtimePageState();
}

class _RealtimePageState extends ConsumerState<RealtimePage> {
  final _roomKey = TextEditingController();
  LiveCall? _call;
  RealtimeRoom? _active;
  String? _busy;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Recording consent changes while people are in the room.
    _timer = Timer.periodic(widget.pollInterval, (_) {
      final room = _active;
      if (room == null) return;
      final rows = ref.read(realtimeRecordingsProvider(room.id)).value;
      if (rows != null && rows.any((r) => r.isActive)) ref.invalidate(realtimeRecordingsProvider(room.id));
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _roomKey.dispose();
    final call = _call;
    final room = _active;
    _call = null;
    if (call != null) {
      unawaited(call.disconnect());
      if (room != null) unawaited(ref.read(realtimeRepositoryProvider).leave(room.id).catchError((Object _) {}));
    }
    super.dispose();
  }

  RealtimeRepository get _repo => ref.read(realtimeRepositoryProvider);

  Future<void> _run(String key, Future<void> Function() action, {String? done, String? failed}) async {
    final l = AppLocalizations.of(context);
    setState(() {
      _busy = key;
      _error = null;
    });
    try {
      await action();
      if (done != null && mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      if (mounted) setState(() => _error = describeAccountError(l, error, failed ?? l.realtime_actionError));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _create() async {
    final l = AppLocalizations.of(context);
    if (_roomKey.text.trim().length < 2) return;
    await _run('create', () async {
      await _repo.create(_roomKey.text);
      _roomKey.clear();
      ref.invalidate(realtimeRoomsProvider);
    }, done: l.realtime_roomCreated);
  }

  Future<void> _join(RealtimeRoom room) async {
    final l = AppLocalizations.of(context);
    if (_call != null) await _leave();
    await _run('join:${room.id}', () async {
      final session = await _repo.join(room);
      final call = ref.read(liveCallFactoryProvider)();
      call.addListener(_onCall);
      try {
        await call.connect(session, video: room.mediaMode != 'audio');
      } on Object {
        call.removeListener(_onCall);
        await _repo.leave(room.id).catchError((Object _) {});
        rethrow;
      }
      setState(() {
        _call = call;
        _active = room;
      });
      ref.invalidate(realtimeRoomsProvider);
    }, done: l.realtime_joined, failed: l.realtime_joinError);
  }

  void _onCall() {
    if (mounted) setState(() {});
  }

  Future<void> _leave() async {
    final call = _call;
    final room = _active;
    setState(() {
      _call = null;
      _active = null;
    });
    call?.removeListener(_onCall);
    await call?.disconnect();
    if (room != null) {
      await _run('leave', () async {
        await _repo.leave(room.id);
        ref.invalidate(realtimeRoomsProvider);
      });
    }
  }

  Future<void> _close(RealtimeRoom room) async {
    final l = AppLocalizations.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(l.realtime_closeConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(l.projects_cancel)),
          FilledButton(key: const Key('close-confirm'), onPressed: () => Navigator.pop(context, true), child: Text(l.realtime_close)),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    if (_active?.id == room.id) await _leave();
    await _run('close:${room.id}', () async {
      await _repo.close(room.id);
      ref.invalidate(realtimeRoomsProvider);
    }, done: l.realtime_roomClosed);
  }

  Future<void> _toggle(Future<void> Function(LiveCall call) action) async {
    final call = _call;
    if (call == null) return;
    await _run('media', () => action(call));
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider).value;
    final user = session is SignedIn ? session.user : null;
    final paid = user != null && user.role != 'Free User' && user.organizationPlan.toLowerCase() != 'free';
    return Scaffold(
      appBar: AppBar(
        title: Text(l.realtime_title, overflow: TextOverflow.ellipsis),
        actions: [
          if (paid)
            IconButton(
              tooltip: l.realtime_refresh,
              icon: const Icon(Icons.refresh),
              onPressed: () {
                ref.invalidate(realtimeReadinessProvider);
                ref.invalidate(realtimeRoomsProvider);
              },
            ),
        ],
      ),
      body: user == null
          ? const Center(child: CircularProgressIndicator())
          : !paid
              ? ListView(children: [
                  EmptyState(icon: Icons.videocam_off_outlined, title: l.app_realtimePlanTitle, message: l.realtime_description),
                ])
              : _body(l, user.id),
    );
  }

  Widget _body(AppLocalizations l, String userId) {
    final theme = Theme.of(context);
    final readiness = ref.watch(realtimeReadinessProvider);
    final call = _call;
    final active = _active;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 40),
      children: [
        Text(l.realtime_description, style: theme.textTheme.bodySmall),
        const SizedBox(height: 8),
        readiness.when(
          loading: () => const LinearProgressIndicator(),
          error: (error, _) => Notice(text: describeAccountError(l, error, l.realtime_loadError), tone: NoticeTone.error),
          data: (r) => Notice(
            key: const Key('realtime-readiness'),
            text: r.enabled ? l.realtime_runtimeReady : l.realtime_runtimeOffline,
            tone: r.enabled ? NoticeTone.success : NoticeTone.info,
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Notice(key: const Key('realtime-error'), text: _error!, tone: NoticeTone.error),
        ],
        if (call != null && active != null) ...[
          const SizedBox(height: 12),
          Text(active.roomKey, style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          call.view(context),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.center, children: [
            IconButton.filledTonal(
              key: const Key('toggle-mic'),
              tooltip: call.micEnabled ? l.realtime_mute : l.realtime_unmute,
              onPressed: _busy == null ? () => _toggle((c) => c.setMic(!c.micEnabled)) : null,
              icon: Icon(call.micEnabled ? Icons.mic : Icons.mic_off),
            ),
            if (active.mediaMode != 'audio')
              IconButton.filledTonal(
                key: const Key('toggle-camera'),
                tooltip: call.cameraEnabled ? l.realtime_cameraOff : l.realtime_cameraOn,
                onPressed: _busy == null ? () => _toggle((c) => c.setCamera(!c.cameraEnabled)) : null,
                icon: Icon(call.cameraEnabled ? Icons.videocam : Icons.videocam_off),
              ),
            if (active.allowScreenShare)
              IconButton.filledTonal(
                key: const Key('toggle-screen'),
                tooltip: call.screenEnabled ? l.realtime_stopShare : l.realtime_shareScreen,
                onPressed: _busy == null ? () => _toggle((c) => c.setScreen(!c.screenEnabled)) : null,
                icon: Icon(call.screenEnabled ? Icons.stop_screen_share : Icons.screen_share),
              ),
            FilledButton.icon(
              key: const Key('leave-room'),
              style: FilledButton.styleFrom(backgroundColor: theme.colorScheme.error),
              onPressed: _leave,
              icon: const Icon(Icons.call_end),
              label: Text(l.realtime_leave),
            ),
          ]),
          const SizedBox(height: 12),
          _Recordings(room: active),
        ],
        const SizedBox(height: 16),
        Text(l.realtime_createRoom, style: theme.textTheme.titleMedium),
        Row(children: [
          Expanded(
            child: TextField(
              key: const Key('room-key'),
              controller: _roomKey,
              maxLength: 120,
              decoration: InputDecoration(labelText: l.realtime_roomNamePlaceholder),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton(key: const Key('create-room'), onPressed: _busy == null ? _create : null, child: Text(l.realtime_create)),
        ]),
        const SizedBox(height: 8),
        Text(l.realtime_rooms, style: theme.textTheme.titleMedium),
        AsyncView(
          value: ref.watch(realtimeRoomsProvider),
          onRetry: () => ref.invalidate(realtimeRoomsProvider),
          builder: (rooms) {
            final open = rooms.where((r) => r.isOpen).toList();
            if (open.isEmpty) return Text(l.realtime_noRooms, style: theme.textTheme.bodySmall);
            return Column(children: [
              for (final room in open)
                Card(
                  key: Key('room-${room.id}'),
                  child: ListTile(
                    title: Text(room.roomKey),
                    subtitle: Text('${l.realtime_participants(room.participantCount, room.maxParticipants)} · ${room.mediaMode}'),
                    trailing: Wrap(spacing: 4, children: [
                      if (active?.id != room.id)
                        TextButton(
                          key: Key('join-${room.id}'),
                          onPressed: _busy == null ? () => _join(room) : null,
                          child: Text(l.realtime_join),
                        ),
                      if (room.createdById == userId)
                        IconButton(
                          key: Key('close-${room.id}'),
                          tooltip: l.realtime_close,
                          onPressed: _busy == null ? () => _close(room) : null,
                          icon: const Icon(Icons.stop_circle_outlined),
                        ),
                    ]),
                  ),
                ),
            ]);
          },
        ),
      ],
    );
  }
}

class _Recordings extends ConsumerWidget {
  const _Recordings({required this.room});

  final RealtimeRoom room;

  Future<void> _act(BuildContext context, WidgetRef ref, Future<void> Function() action, String done) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await action();
      messenger.showSnackBar(SnackBar(content: Text(done)));
    } on Object catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeAccountError(l, error, l.realtime_actionError))));
    }
    ref.invalidate(realtimeRecordingsProvider(room.id));
  }

  Future<void> _request(BuildContext context, WidgetRef ref) async {
    final l = AppLocalizations.of(context);
    final title = await showDialog<String>(context: context, builder: (_) => _TitleDialog(initial: '${room.roomKey} recording'));
    if (title == null || title.trim().isEmpty || !context.mounted) return;
    await _act(context, ref, () => ref.read(realtimeRepositoryProvider).requestRecording(room.id, title), l.realtime_recordingRequested);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final repo = ref.read(realtimeRepositoryProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(children: [
              Expanded(child: Text(l.realtime_recordings, style: theme.textTheme.titleSmall)),
              TextButton.icon(
                key: const Key('request-recording'),
                onPressed: () => _request(context, ref),
                icon: const Icon(Icons.fiber_manual_record, color: Colors.red),
                label: Text(l.realtime_requestRecording),
              ),
            ]),
            Text(l.realtime_recordingConsentNotice, style: theme.textTheme.bodySmall),
            AsyncView(
              value: ref.watch(realtimeRecordingsProvider(room.id)),
              onRetry: () => ref.invalidate(realtimeRecordingsProvider(room.id)),
              builder: (rows) => rows.isEmpty
                  ? Text(l.realtime_noRecordings, style: theme.textTheme.bodySmall)
                  : Column(children: [
                      for (final r in rows)
                        ListTile(
                          key: Key('recording-${r.id}'),
                          contentPadding: EdgeInsets.zero,
                          title: Text(r.title),
                          subtitle: Text([
                            r.status,
                            l.realtime_consentProgress(r.consented, r.requiredConsents),
                            if (r.studioAssetId != null) l.realtime_savedToStudio,
                          ].join(' · ')),
                          trailing: Wrap(children: [
                            if (r.status == 'awaiting_consent') ...[
                              TextButton(
                                key: Key('agree-${r.id}'),
                                onPressed: () => _act(context, ref, () => repo.consent(r.id, true), l.realtime_consentRecorded),
                                child: Text(l.realtime_agree),
                              ),
                              TextButton(
                                onPressed: () => _act(context, ref, () => repo.consent(r.id, false), l.realtime_consentDeclined),
                                child: Text(l.realtime_decline),
                              ),
                            ],
                            if (r.status == 'active')
                              TextButton(
                                key: Key('stop-${r.id}'),
                                onPressed: () => _act(context, ref, () => repo.stopRecording(r.id), l.realtime_stopRecording),
                                child: Text(l.realtime_stopRecording),
                              ),
                          ]),
                        ),
                    ]),
            ),
          ],
        ),
      ),
    );
  }
}

class _TitleDialog extends StatefulWidget {
  const _TitleDialog({required this.initial});

  final String initial;

  @override
  State<_TitleDialog> createState() => _TitleDialogState();
}

class _TitleDialogState extends State<_TitleDialog> {
  late final _title = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l.realtime_recordingTitlePrompt),
      content: TextField(key: const Key('recording-title'), controller: _title, maxLength: 160),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(l.projects_cancel)),
        FilledButton(key: const Key('recording-confirm'), onPressed: () => Navigator.pop(context, _title.text), child: Text(l.realtime_requestRecording)),
      ],
    );
  }
}
