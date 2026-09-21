import 'dart:convert';

enum SyncState { synced, pending, conflict, failed }

class LocalRecord {
  const LocalRecord({
    required this.entity,
    required this.localId,
    this.serverId,
    required this.data,
    this.serverVersion,
    required this.updatedAt,
    this.deletedAt,
    this.syncState = SyncState.synced,
  });
  final String entity;
  final String localId;
  final String? serverId;
  final Map<String, dynamic> data;
  final int? serverVersion;
  final DateTime updatedAt;
  final DateTime? deletedAt;
  final SyncState syncState;
  String get recordId => serverId ?? localId;
  bool get isPendingLocal => serverId == null;
  String get summary => '$entity/$recordId ${jsonEncode(data)}';
}

class OutboxOperation {
  const OutboxOperation({
    required this.operationId,
    required this.entity,
    required this.localId,
    this.serverId,
    required this.clientRecordId,
    required this.operation,
    required this.payload,
    this.baseVersion,
    required this.createdAt,
    required this.status,
    this.lastError,
    required this.attempts,
  });
  final String operationId;
  final String entity;
  final String localId;
  final String? serverId;
  final String clientRecordId;
  final String operation;
  final Map<String, dynamic> payload;
  final int? baseVersion;
  final DateTime createdAt;
  final SyncState status;
  final String? lastError;
  final int attempts;
}

class SyncChange {
  const SyncChange({
    required this.entity,
    required this.serverId,
    this.localId,
    this.clientRecordId,
    this.operationId,
    required this.operation,
    required this.payload,
    required this.version,
  });
  final String entity;
  final String serverId;
  final String? localId;
  final String? clientRecordId;
  final String? operationId;
  final String operation;
  final Map<String, dynamic> payload;
  final int version;
}

class PushResult {
  const PushResult({
    required this.operationId,
    required this.status,
    this.record,
    this.serverId,
    this.serverVersion,
    this.clientRecordId,
    this.error,
  });
  final String operationId;
  final SyncState status;
  final LocalRecord? record;
  final String? serverId;
  final int? serverVersion;
  final String? clientRecordId;
  final String? error;
}
