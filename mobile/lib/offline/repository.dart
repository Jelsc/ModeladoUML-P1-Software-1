import 'dart:convert';
import 'dart:math';

import 'package:sqflite/sqflite.dart';

import 'models.dart';
import '../uap/models.dart';

class OfflineRepository {
  OfflineRepository(this.db);
  final Database db;

  Future<LocalRecord?> read(String entity, String identity) async {
    final rows = await db.query(
      'local_records',
      where: 'entity = ? AND (local_id = ? OR server_id = ?)',
      whereArgs: [entity, identity, identity],
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

  Future<UapSnapshot?> cachedSnapshot() async {
    final value = await metadata('uap_snapshot');
    if (value == null) return null;
    try {
      return UapSnapshot.fromJson(
        (jsonDecode(value) as Map).cast<String, dynamic>(),
      );
    } catch (_) {
      return null;
    }
  }

  Future<void> saveSnapshot(UapSnapshot snapshot) =>
      saveMetadata('uap_snapshot', jsonEncode(snapshot.toJson()));
  Future<String?> backendGeneration() => metadata('backend_generation');
  Future<void> saveBackendGeneration(String value) => saveMetadata('backend_generation', value);
  Future<bool> hasRemoteCache() async => (await db.query(
    'local_records',
    columns: ['local_id'],
    where: 'server_id IS NOT NULL OR sync_state = ?',
    whereArgs: [SyncState.synced.name],
    limit: 1,
  )).isNotEmpty;

  Future<void> resetRemoteCache(String generation) async {
    await db.transaction((txn) async {
      final pending = await txn.query('sync_outbox', columns: ['local_id'], where: 'status IN (?, ?, ?)', whereArgs: [SyncState.pending.name, SyncState.failed.name, SyncState.conflict.name]);
      final localIds = pending.map((row) => row['local_id'].toString()).toSet();
      if (pending.isNotEmpty) {
        await txn.update('sync_outbox', {'status': SyncState.conflict.name, 'last_error': 'El backend cambió de generación; requiere rebase manual.'}, where: 'status IN (?, ?)', whereArgs: [SyncState.pending.name, SyncState.failed.name]);
        final placeholders = List.filled(localIds.length, '?').join(',');
        await txn.update('local_records', {'sync_state': SyncState.conflict.name}, where: 'local_id IN ($placeholders)', whereArgs: localIds.toList());
      }
      if (localIds.isEmpty) {
        await txn.delete('local_records', where: 'sync_state = ?', whereArgs: [SyncState.synced.name]);
      } else {
        final placeholders = List.filled(localIds.length, '?').join(',');
        await txn.delete('local_records', where: 'local_id NOT IN ($placeholders)', whereArgs: localIds.toList());
      }
      await txn.delete('identity_map');
      await txn.delete('sync_metadata', where: 'key = ?', whereArgs: ['cursor']);
      await txn.insert('sync_metadata', {'key': 'backend_generation', 'value': generation}, conflictAlgorithm: ConflictAlgorithm.replace);
    });
  }
  Future<String?> metadata(String key) async => (await db.query(
    'sync_metadata',
    where: 'key = ?',
    whereArgs: [key],
  )).singleOrNull?['value']?.toString();
  Future<void> saveMetadata(String key, String value) => db.insert(
    'sync_metadata',
    {'key': key, 'value': value},
    conflictAlgorithm: ConflictAlgorithm.replace,
  );
  Future<void> saveBackendStatus(String status) =>
      saveMetadata('backend_status', status);
  Future<String> backendStatus() async =>
      await metadata('backend_status') ?? 'offline';
  Future<DateTime?> lastSyncAt() async =>
      DateTime.tryParse(await metadata('last_sync_at') ?? '');

  Future<void> applyLocalMutation({
    required String entity,
    required String recordId,
    required String operation,
    required Map<String, dynamic> payload,
    int? baseVersion,
    String? operationId,
    String? localId,
  }) async {
    await db.transaction((txn) async {
      final existing = await _find(txn, entity, localId ?? recordId);
      final resolvedLocalId =
          existing?['local_id']?.toString() ?? localId ?? recordId;
      final serverId = existing?['server_id']?.toString();
      final current = existing == null
          ? <String, dynamic>{}
          : _decode(existing['data_json']!);
      final data = operation == 'update'
          ? {...current, ...payload}
          : operation == 'delete'
          ? <String, dynamic>{}
          : payload;
      final now = DateTime.now().toUtc().toIso8601String();
      await txn.insert('local_records', {
        'local_id': resolvedLocalId,
        'entity': entity,
        'server_id': serverId,
        'data_json': jsonEncode(data),
        'server_version': baseVersion ?? existing?['server_version'],
        'updated_at': now,
        'deleted_at': operation == 'delete' ? now : null,
        'sync_state': SyncState.pending.name,
      }, conflictAlgorithm: ConflictAlgorithm.replace);

      final pendingCreate = await txn.query(
        'sync_outbox',
        where:
            'entity = ? AND local_id = ? AND operation = ? AND status IN (?, ?)',
        whereArgs: [
          entity,
          resolvedLocalId,
          'create',
          SyncState.pending.name,
          SyncState.failed.name,
        ],
        orderBy: 'created_at ASC',
        limit: 1,
      );
      if (pendingCreate.isNotEmpty && operation == 'update') {
        final create = pendingCreate.single;
        final createPayload = {..._decode(create['payload_json']!), ...payload};
        await txn.update(
          'sync_outbox',
          {
            'payload_json': jsonEncode(createPayload),
            'server_id': serverId,
            'client_record_id': resolvedLocalId,
            'status': SyncState.pending.name,
            'last_error': null,
          },
          where: 'operation_id = ?',
          whereArgs: [create['operation_id']],
        );
        return;
      }
      if (pendingCreate.isNotEmpty && operation == 'delete') {
        await txn.delete(
          'sync_outbox',
          where: 'operation_id = ?',
          whereArgs: [pendingCreate.single['operation_id']],
        );
        return;
      }
      final id = operationId ?? _uuid();
      await txn.insert('sync_outbox', {
        'operation_id': id,
        'entity': entity,
        'record_id': serverId ?? resolvedLocalId,
        'local_id': resolvedLocalId,
        'server_id': serverId,
        'client_record_id': resolvedLocalId,
        'operation': operation,
        'payload_json': jsonEncode(payload),
        'base_version': baseVersion ?? existing?['server_version'],
        'created_at': now,
        'status': SyncState.pending.name,
        'attempts': 0,
      }, conflictAlgorithm: ConflictAlgorithm.ignore);
    });
  }

  Future<void> upsert({
    required String entity,
    String? recordId,
    String? localId,
    String? serverId,
    required Map<String, dynamic> data,
    int? serverVersion,
    SyncState state = SyncState.synced,
    DateTime? deletedAt,
  }) async {
    await db.transaction((txn) async {
      final identity = serverId ?? recordId;
      final existing = localId == null && identity != null
          ? await _find(txn, entity, identity)
          : null;
      final resolvedLocalId =
          localId ??
          existing?['local_id']?.toString() ??
          (serverId ?? recordId ?? _uuid());
      await txn.insert('local_records', {
        'local_id': resolvedLocalId,
        'entity': entity,
        'server_id': serverId ?? recordId,
        'data_json': jsonEncode(data),
        'server_version': serverVersion,
        'updated_at': DateTime.now().toUtc().toIso8601String(),
        'deleted_at': deletedAt?.toUtc().toIso8601String(),
        'sync_state': state.name,
      }, conflictAlgorithm: ConflictAlgorithm.replace);
      if ((serverId ?? recordId) != null) {
        await txn.insert('identity_map', {
          'entity': entity,
          'local_id': resolvedLocalId,
          'server_id': serverId ?? recordId,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
    });
  }

  Future<String> enqueue({
    required String entity,
    String? recordId,
    String? localId,
    String? serverId,
    required String operation,
    required Map<String, dynamic> payload,
    int? baseVersion,
    String? operationId,
    String? clientRecordId,
  }) async {
    final resolvedLocalId = localId ?? recordId ?? _uuid();
    if (await read(entity, resolvedLocalId) == null)
      await upsert(
        entity: entity,
        localId: resolvedLocalId,
        serverId: serverId,
        data: payload,
        serverVersion: baseVersion,
        state: SyncState.pending,
      );
    final id = operationId ?? _uuid();
    await db.insert('sync_outbox', {
      'operation_id': id,
      'entity': entity,
      'record_id': serverId ?? resolvedLocalId,
      'local_id': resolvedLocalId,
      'server_id': serverId,
      'client_record_id': clientRecordId ?? resolvedLocalId,
      'operation': operation,
      'payload_json': jsonEncode(payload),
      'base_version': baseVersion,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'status': SyncState.pending.name,
      'attempts': 0,
    }, conflictAlgorithm: ConflictAlgorithm.ignore);
    return id;
  }

  Future<List<OutboxOperation>> pendingOperations() async {
    final rows = await db.query(
      'sync_outbox',
      where: 'status = ? OR (status = ? AND attempts < ?)',
      whereArgs: [SyncState.pending.name, SyncState.failed.name, 5],
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

  Future<void> reconcilePush(
    OutboxOperation operation,
    PushResult result,
  ) async {
    await db.transaction((txn) async {
      await txn.update(
        'sync_outbox',
        {
          'status': result.status.name,
          'last_error': result.error,
          'attempts':
              Sqflite.firstIntValue(
                await txn.rawQuery(
                  'SELECT attempts + 1 FROM sync_outbox WHERE operation_id = ?',
                  [operation.operationId],
                ),
              ) ??
              1,
        },
        where: 'operation_id = ?',
        whereArgs: [operation.operationId],
      );
      if (result.status != SyncState.synced || result.record == null) {
        await txn.update(
          'local_records',
          {'sync_state': result.status.name},
          where: 'local_id = ?',
          whereArgs: [operation.localId],
        );
        return;
      }
      final serverId =
          result.serverId ?? result.record!.serverId ?? result.record!.recordId;
      final record = result.record!;
      await txn.insert('local_records', {
        'local_id': operation.localId,
        'entity': operation.entity,
        'server_id': serverId,
        'data_json': jsonEncode(record.data),
        'server_version': result.serverVersion ?? record.serverVersion,
        'updated_at': DateTime.now().toUtc().toIso8601String(),
        'deleted_at': operation.operation == 'delete'
            ? DateTime.now().toUtc().toIso8601String()
            : null,
        'sync_state': SyncState.synced.name,
      }, conflictAlgorithm: ConflictAlgorithm.replace);
      await txn.insert('identity_map', {
        'entity': operation.entity,
        'local_id': operation.localId,
        'server_id': serverId,
      }, conflictAlgorithm: ConflictAlgorithm.replace);
      await txn.update(
        'sync_outbox',
        {
          'record_id': serverId,
          'server_id': serverId,
          'client_record_id': operation.localId,
        },
        where: 'entity = ? AND local_id = ?',
        whereArgs: [operation.entity, operation.localId],
      );
    });
  }

  Future<void> applyPull({
    required String entity,
    required String serverId,
    String? localId,
    String? clientRecordId,
    String? operationId,
    required String operation,
    required Map<String, dynamic> data,
    required int version,
  }) async {
    final operationRow = operationId == null
        ? const <String, Object?>{}
        : ((await db.query(
                'sync_outbox',
                where: 'operation_id = ?',
                whereArgs: [operationId],
                limit: 1,
              )).singleOrNull ??
              const <String, Object?>{});
    final mappedLocalId =
        localId ?? clientRecordId ?? operationRow['local_id']?.toString();
    final existing = await read(entity, mappedLocalId ?? serverId) ??
        await read(entity, serverId);
    await upsert(
      entity: entity,
      localId: existing?.localId ?? mappedLocalId,
      serverId: serverId,
      data: data,
      serverVersion: version,
      state: SyncState.synced,
      deletedAt: operation == 'delete' ? DateTime.now().toUtc() : null,
    );
  }

  Future<String> cursor() async => await metadata('cursor') ?? '0';
  Future<void> saveCursor(String value) => saveMetadata('cursor', value);

  Future<Map<String, Object?>?> _find(
    DatabaseExecutor executor,
    String entity,
    String identity,
  ) async {
    final rows = await executor.query(
      'local_records',
      where: 'entity = ? AND (local_id = ? OR server_id = ?)',
      whereArgs: [entity, identity, identity],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.single;
  }

  LocalRecord _record(Map<String, Object?> row) => LocalRecord(
    entity: row['entity']! as String,
    localId: row['local_id']! as String,
    serverId: row['server_id'] as String?,
    data: _decode(row['data_json']! as String),
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
    localId: row['local_id']! as String,
    serverId: row['server_id'] as String?,
    clientRecordId: row['client_record_id']! as String,
    operation: row['operation']! as String,
    payload: _decode(row['payload_json']! as String),
    baseVersion: row['base_version'] as int?,
    createdAt: DateTime.parse(row['created_at']! as String),
    status: SyncState.values.byName(row['status']! as String),
    lastError: row['last_error'] as String?,
    attempts: row['attempts']! as int,
  );
  Map<String, dynamic> _decode(Object value) =>
      (jsonDecode(value as String) as Map).cast<String, dynamic>();
  String _uuid() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return '${bytes.sublist(0, 4).map(_hex).join()}-${bytes.sublist(4, 6).map(_hex).join()}-${bytes.sublist(6, 8).map(_hex).join()}-${bytes.sublist(8, 10).map(_hex).join()}-${bytes.sublist(10).map(_hex).join()}';
  }

  String _hex(int value) => value.toRadixString(16).padLeft(2, '0');
}

extension on List<Map<String, Object?>> {
  Map<String, Object?>? get singleOrNull => isEmpty ? null : single;
}
