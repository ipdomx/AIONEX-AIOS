import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/providers.dart';
import 'workspace_models.dart';

/// Projects, quotas, project conversations and support (same endpoints as the website).
class WorkspaceRepository {
  WorkspaceRepository(this._api);

  final ApiClient _api;

  List<Map<String, Object?>> _rows(List<Object?> list) =>
      [for (final item in list) if (item is Map) item.cast<String, Object?>()];

  Future<PlanQuota> quota() async => PlanQuota.fromJson(await _api.getJson('/auth/free-tier'));

  Future<List<Project>> projects() async =>
      [for (final row in _rows(await _api.getList('/projects'))) Project.fromJson(row)];

  Future<List<Workspace>> workspaces() async =>
      [for (final row in _rows(await _api.getList('/workspaces'))) Workspace.fromJson(row)];

  Future<Project> createProject({
    required String name,
    required String workspaceId,
    required String priority,
    String? description,
    List<String> tags = const [],
  }) async {
    final json = await _api.postJson(
      '/projects',
      body: {
        'name': name.trim(),
        'description': (description?.trim().isEmpty ?? true) ? null : description!.trim(),
        'priority': priority,
        'workspace_id': workspaceId,
        'tags': tags,
      },
      retry: false,
    );
    return Project.fromJson(json);
  }

  // Support ------------------------------------------------------------------

  Future<List<SupportTicket>> tickets() async =>
      [for (final row in _rows(await _api.getList('/support/requests'))) SupportTicket.fromJson(row)];

  Future<SupportTicket> ticket(String id) async =>
      SupportTicket.fromJson(await _api.getJson('/support/requests/${Uri.encodeComponent(id)}'));

  Future<SupportTicket> createTicket({
    required String subject,
    required String message,
    required String category,
    required String priority,
  }) async {
    final json = await _api.postJson(
      '/support/requests',
      body: {'subject': subject.trim(), 'message': message.trim(), 'category': category, 'priority': priority},
      retry: false,
    );
    return SupportTicket.fromJson(json);
  }

  Future<void> replyToTicket(String id, String message) async {
    await _api.postJson(
      '/support/requests/${Uri.encodeComponent(id)}/messages',
      body: {'message': message.trim(), 'visibility': 'requester'},
      retry: false,
    );
  }

  // Project conversations (durable jobs, polled like the website) -------------

  static const _conversations = '/project-conversations';

  Future<List<Conversation>> conversations() async =>
      [for (final row in _rows(await _api.getList(_conversations))) Conversation.fromJson(row)];

  Future<ConversationPolicy> conversationPolicy() async =>
      ConversationPolicy.fromJson(await _api.getJson('$_conversations/policy'));

  Future<List<ConversationAgent>> agents() async =>
      [for (final row in _rows(await _api.getList('$_conversations/agents'))) ConversationAgent.fromJson(row)];

  Future<ConversationHistory> history(String id) async =>
      ConversationHistory.fromJson(await _api.getJson('$_conversations/${Uri.encodeComponent(id)}/messages'));

  Future<Conversation> createConversation(String projectId, String title, String requestId) async {
    final json = await _api.postJson(
      _conversations,
      body: {'project_id': projectId, 'title': title.trim(), 'request_id': requestId},
      retry: false,
    );
    return Conversation.fromJson(json);
  }

  /// The request id makes a resend after a dropped connection a no-op on the server.
  Future<void> sendMessage(
    String id, {
    required String message,
    required String agentId,
    required String requestId,
    required bool confirmExternalProcessing,
  }) async {
    await _api.postJson(
      '$_conversations/${Uri.encodeComponent(id)}/messages',
      body: {
        'message': message.trim(),
        'agent_id': agentId,
        'request_id': requestId,
        'confirm_external_processing': confirmExternalProcessing,
      },
      retry: false,
    );
  }

  Future<void> closeConversation(String id) async {
    await _api.postJson('$_conversations/${Uri.encodeComponent(id)}/close', retry: false);
  }
}

final workspaceRepositoryProvider =
    Provider<WorkspaceRepository>((ref) => WorkspaceRepository(ref.watch(apiClientProvider)));

final quotaProvider = FutureProvider.autoDispose<PlanQuota>((ref) => ref.watch(workspaceRepositoryProvider).quota());

final projectsProvider =
    FutureProvider.autoDispose<List<Project>>((ref) => ref.watch(workspaceRepositoryProvider).projects());

final ticketsProvider =
    FutureProvider.autoDispose<List<SupportTicket>>((ref) => ref.watch(workspaceRepositoryProvider).tickets());

final conversationsProvider =
    FutureProvider.autoDispose<List<Conversation>>((ref) => ref.watch(workspaceRepositoryProvider).conversations());
