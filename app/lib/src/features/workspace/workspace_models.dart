import 'dart:math';

import 'package:flutter/foundation.dart';

String _s(Object? value, [String fallback = '']) => value is String ? value : fallback;
int _i(Object? value, [int fallback = 0]) => value is num ? value.toInt() : fallback;
DateTime? _d(Object? value) => value is String ? DateTime.tryParse(value) : null;
Map<String, Object?> _m(Object? value) => value is Map ? value.cast<String, Object?>() : const {};
List<Map<String, Object?>> _l(Object? value) =>
    value is List ? [for (final item in value) if (item is Map) item.cast<String, Object?>()] : const [];

/// A one-time key so a retried create/send is recognised by the server
/// (the same role as crypto.randomUUID() on the website).
String newRequestId() {
  final random = Random.secure();
  return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

@immutable
class Workspace {
  const Workspace({required this.id, required this.name});
  final String id;
  final String name;
  factory Workspace.fromJson(Map<String, Object?> json) => Workspace(id: _s(json['id']), name: _s(json['name']));
}

@immutable
class Project {
  const Project({
    required this.id,
    required this.name,
    required this.description,
    required this.status,
    required this.priority,
    required this.progress,
    required this.workspace,
    required this.taskCount,
    required this.tags,
    required this.updatedAt,
  });

  final String id;
  final String name;
  final String description;
  final String status;
  final String priority;
  final int progress;
  final String workspace;
  final int taskCount;
  final List<String> tags;
  final DateTime? updatedAt;

  bool get isActive => !const {'deleted', 'archived', 'cancelled'}.contains(status);

  factory Project.fromJson(Map<String, Object?> json) {
    final tags = json['tags'];
    return Project(
      id: _s(json['id']),
      name: _s(json['name']),
      description: _s(json['description']),
      status: _s(json['status']),
      priority: _s(json['priority'], 'medium'),
      progress: _i(json['progress']),
      workspace: _s(json['workspace']),
      taskCount: _i(json['task_count']),
      tags: tags is List ? tags.whereType<String>().toList(growable: false) : const [],
      updatedAt: _d(json['updated_at']),
    );
  }
}

/// GET /auth/free-tier: plan quotas. A null limit means unlimited.
@immutable
class PlanQuota {
  const PlanQuota({required this.planName, required this.limits, required this.usage, required this.remaining, this.periodEndsAt});

  final String planName;
  final Map<String, int?> limits;
  final Map<String, int> usage;
  final Map<String, int?> remaining;
  final DateTime? periodEndsAt;

  bool isUnlimited(String key) => limits.containsKey(key) && limits[key] == null;

  factory PlanQuota.fromJson(Map<String, Object?> json) {
    Map<String, int?> nullable(Object? value) => {
          for (final entry in _m(value).entries) entry.key: entry.value is num ? (entry.value! as num).toInt() : null,
        };
    return PlanQuota(
      planName: _s(json['plan_name'], _s(json['plan'])),
      limits: nullable(json['limits']),
      usage: {for (final entry in _m(json['usage']).entries) entry.key: _i(entry.value)},
      remaining: nullable(json['remaining']),
      periodEndsAt: _d(json['period_ends_at']),
    );
  }
}

@immutable
class SupportMessage {
  const SupportMessage({required this.id, required this.senderId, required this.message, required this.createdAt});
  final String id;
  final String? senderId;
  final String message;
  final DateTime? createdAt;

  factory SupportMessage.fromJson(Map<String, Object?> json) => SupportMessage(
        id: _s(json['id']),
        senderId: json['sender_id'] as String?,
        message: _s(json['message']),
        createdAt: _d(json['created_at']),
      );
}

@immutable
class SupportTicket {
  const SupportTicket({
    required this.id,
    required this.requesterId,
    required this.subject,
    required this.category,
    required this.priority,
    required this.status,
    required this.messageCount,
    required this.lastMessageAt,
    required this.messages,
  });

  final String id;
  final String requesterId;
  final String subject;
  final String category;
  final String priority;
  final String status;
  final int messageCount;
  final DateTime? lastMessageAt;
  final List<SupportMessage> messages;

  factory SupportTicket.fromJson(Map<String, Object?> json) => SupportTicket(
        id: _s(json['id']),
        requesterId: _s(json['requester_id']),
        subject: _s(json['subject']),
        category: _s(json['category'], 'general'),
        priority: _s(json['priority'], 'normal'),
        status: _s(json['status']),
        messageCount: _i(json['message_count']),
        lastMessageAt: _d(json['last_message_at']),
        messages: [for (final item in _l(json['messages'])) SupportMessage.fromJson(item)],
      );
}

@immutable
class Conversation {
  const Conversation({
    required this.id,
    required this.projectId,
    required this.title,
    required this.status,
    required this.messagesUsed,
    required this.messagesAllowed,
    required this.secondsRemaining,
  });

  final String id;
  final String projectId;
  final String title;

  /// effective_status: open, paused, closed or expired.
  final String status;
  final int messagesUsed;
  final int messagesAllowed;
  final int secondsRemaining;

  bool get isOpen => status == 'open';

  factory Conversation.fromJson(Map<String, Object?> json) => Conversation(
        id: _s(json['id']),
        projectId: _s(json['project_id']),
        title: _s(json['title']),
        status: _s(json['effective_status'], _s(json['status'])),
        messagesUsed: _i(json['messages_used']),
        messagesAllowed: _i(json['messages_allowed']),
        secondsRemaining: _i(json['seconds_remaining']),
      );
}

@immutable
class ConversationTurn {
  const ConversationTurn({
    required this.id,
    required this.ordinal,
    required this.userMessage,
    required this.assistantMessage,
    required this.status,
    required this.error,
  });

  final String id;
  final int ordinal;
  final String userMessage;
  final String? assistantMessage;

  /// queued, running, completed, failed, cancelled or needs_review.
  final String status;
  final String? error;

  bool get isPending => status == 'queued' || status == 'running';

  factory ConversationTurn.fromJson(Map<String, Object?> json) => ConversationTurn(
        id: _s(json['id']),
        ordinal: _i(json['ordinal']),
        userMessage: _s(json['user_message']),
        assistantMessage: json['assistant_message'] as String?,
        status: _s(json['status']),
        error: json['error'] as String?,
      );
}

@immutable
class ConversationHistory {
  const ConversationHistory({required this.conversation, required this.turns});
  final Conversation conversation;
  final List<ConversationTurn> turns;

  bool get waiting => turns.any((turn) => turn.isPending);

  factory ConversationHistory.fromJson(Map<String, Object?> json) => ConversationHistory(
        conversation: Conversation.fromJson(_m(json['conversation'])),
        turns: [for (final item in _l(json['messages'])) ConversationTurn.fromJson(item)]
          ..sort((a, b) => a.ordinal.compareTo(b.ordinal)),
      );
}

@immutable
class ConversationAgent {
  const ConversationAgent({required this.id, required this.name, required this.externalProcessing});
  final String id;
  final String name;
  final bool externalProcessing;

  factory ConversationAgent.fromJson(Map<String, Object?> json) => ConversationAgent(
        id: _s(json['id']),
        name: _s(json['name']),
        externalProcessing: json['external_processing'] == true,
      );
}

@immutable
class ConversationPolicy {
  const ConversationPolicy({
    required this.enabled,
    required this.maxMessageCharacters,
    required this.messagesPerDay,
    required this.dayMessages,
    required this.lifetimeCredits,
    required this.usedCredits,
  });

  final bool enabled;
  final int maxMessageCharacters;
  final int messagesPerDay;
  final int dayMessages;

  /// 0 or less means unlimited.
  final int lifetimeCredits;
  final int usedCredits;

  factory ConversationPolicy.fromJson(Map<String, Object?> json) {
    final values = _m(json['values']);
    final usage = _m(json['usage']);
    return ConversationPolicy(
      enabled: values['enabled'] != false,
      maxMessageCharacters: _i(values['max_message_characters'], 4000),
      messagesPerDay: _i(values['messages_per_day']),
      dayMessages: _i(usage['day_messages']),
      lifetimeCredits: _i(values['lifetime_message_credits']),
      usedCredits: _i(usage['total_message_credits']),
    );
  }
}
