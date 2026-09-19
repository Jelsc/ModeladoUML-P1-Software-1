import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'models.dart';

class OfflineRepository {
  OfflineRepository(this.db);
  final Database db;

  Future<LocalRecord?> read(String entity, String recordId) async {
    final rows = await db.query(
      'local_records',
      where: 'entity = ? AND record_id = ?',
      whereArgs: [entity, recordId],
    );
    return rows.isEmpty ? null : _record(rows.single);
  }

  Future<List<LocalRecord>> summaries({String? entity}) async {
    final rows = await db.query(
      'local_records',
      where: entity == null ? null : 'entity = ?',
      whereArgs: entity == null ? null : [entity],
      orderBy: 'updated_at DESC',
    );
    return rows.map(_record).toList();
  }

  Future<void> upsert({
    required String entity,
    required String recordId,
    required Map<String, dynamic> data,
    int? serverVersion,
    SyncState state = SyncState.synced,
    DateTime? deletedAt,
  }) async {
    await db.insert('local_records', {
      'entity': entity,
      'record_id': recordId,
      'data_json': jsonEncode(data),
      'server_version': serverVersion,
      'updated_at': DateTime.now().toUtc().toIso8601String(),
      'deleted_at': deletedAt?.toUtc().toIso8601String(),
      'sync_state': state.name,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<String> enqueue({
    required String entity,
    required String recordId,
    required String operation,
    required Map<String, dynamic> payload,
    int? baseVersion,
    String? operationId,
  }) async {
    final id = operationId ?? _uuid();
    await db.insert('sync_outbox', {
      'operation_id': id,
      'entity': entity,
      'record_id': recordId,
      'operation': operation,
      'payload_json': jsonEncode(payload),
      'base_version': baseVersion,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'status': SyncState.pending.name,
      'attempts': 0,
    }, conflictAlgorithm: ConflictAlgorithm.ignore);
    return id;
  }

  Future<void> delete({
    required String entity,
    required String recordId,
    int? baseVersion,
  }) async {
    await upsert(
      entity: entity,
      recordId: recordId,
      data: const {},
      serverVersion: baseVersion,
      state: SyncState.pending,
      deletedAt: DateTime.now(),
    );
    await enqueue(
      entity: entity,
      recordId: recordId,
      operation: 'delete',
      payload: const {},
      baseVersion: baseVersion,
    );
  }

  Future<List<OutboxOperation>> pendingOperations() async {
    final rows = await db.query(
      'sync_outbox',
      where: 'status IN (?, ?)',
      whereArgs: [SyncState.pending.name, SyncState.failed.name],
      orderBy: 'created_at ASC, operation_id ASC',
    );
    return rows.map(_operation).toList();
  }

  Future<void> markOperation(
    String id,
    SyncState status, {
    String? error,
  }) async => db.update(
    'sync_outbox',
    {
      'status': status.name,
      'last_error': error,
      'attempts':
          Sqflite.firstIntValue(
            await db.rawQuery(
              'SELECT attempts + 1 FROM sync_outbox WHERE operation_id = ?',
              [id],
            ),
          ) ??
          1,
    },
    where: 'operation_id = ?',
    whereArgs: [id],
  );
  Future<void> setState(
    String entity,
    String id,
    SyncState state, {
    int? version,
  }) async => db.update(
    'local_records',
    {'sync_state': state.name, if (version != null) 'server_version': version},
    where: 'entity = ? AND record_id = ?',
    whereArgs: [entity, id],
  );
  Future<String> cursor() async =>
      (await db.query(
        'sync_metadata',
        where: 'key = ?',
        whereArgs: ['cursor'],
      )).singleOrNull?['value']?.toString() ??
      '0';
  Future<void> saveCursor(String value) async => db.insert('sync_metadata', {
    'key': 'cursor',
    'value': value,
  }, conflictAlgorithm: ConflictAlgorithm.replace);

  LocalRecord _record(Map<String, Object?> row) => LocalRecord(
    entity: row['entity']! as String,
    recordId: row['record_id']! as String,
    data: (jsonDecode(row['data_json']! as String) as Map)
        .cast<String, dynamic>(),
    serverVersion: row['server_version'] as int?,
    updatedAt: DateTime.parse(row['updated_at']! as String),
    deletedAt: row['deleted_at'] == null
        ? null
        : DateTime.parse(row['deleted_at']! as String),
    syncState: SyncState.values.byName(row['sync_state']! as String),
  );
  OutboxOperation _operation(Map<String, Object?> row) => OutboxOperation(
    operationId: row['operation_id']! as String,
    entity: row['entity']! as String,
    recordId: row['record_id']! as String,
    operation: row['operation']! as String,
    payload: (jsonDecode(row['payload_json']! as String) as Map)
        .cast<String, dynamic>(),
    baseVersion: row['base_version'] as int?,
    createdAt: DateTime.parse(row['created_at']! as String),
    status: SyncState.values.byName(row['status']! as String),
    lastError: row['last_error'] as String?,
    attempts: row['attempts']! as int,
  );
  String _uuid() =>
      '${DateTime.now().microsecondsSinceEpoch}-${Object().hashCode}';
}

extension on List<Map<String, Object?>> {
  Map<String, Object?>? get singleOrNull => isEmpty ? null : single;
}
