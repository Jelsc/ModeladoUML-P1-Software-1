import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:universal_uap_client/assistant/context_broker.dart';
import 'package:universal_uap_client/offline/database.dart';
import 'package:universal_uap_client/offline/models.dart';
import 'package:universal_uap_client/offline/repository.dart';
import 'package:universal_uap_client/offline/sync_engine.dart';
import 'package:universal_uap_client/uap/models.dart';

void main() {
  late OfflineRepository repository;
  late dynamic database;
  setUp(() async {
    sqfliteFfiInit();
    database = await openOfflineDatabase(
      databasePath: inMemoryDatabasePath,
      factory: databaseFactoryFfi,
    );
    repository = OfflineRepository(database);
  });
  tearDown(() => database.close());

  test('stores generic records and deterministic outbox ids', () async {
    await repository.upsert(
      entity: 'Patient',
      recordId: 'p-1',
      data: {'name': 'Ana'},
      state: SyncState.pending,
    );
    final first = await repository.enqueue(
      entity: 'Patient',
      recordId: 'p-1',
      operation: 'create',
      payload: {'name': 'Ana'},
      operationId: 'op-1',
    );
    final second = await repository.enqueue(
      entity: 'Patient',
      recordId: 'p-1',
      operation: 'create',
      payload: {'name': 'Ana'},
      operationId: 'op-1',
    );
    expect(first, 'op-1');
    expect(second, 'op-1');
    expect(
      (await repository.pendingOperations()).map((item) => item.operationId),
      ['op-1'],
    );
  });

  test(
    'offline create receives a local identity before synchronization',
    () async {
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: 'local-user-1',
        operation: 'create',
        payload: {'name': 'Ana'},
      );
      final record = await repository.read('User', 'local-user-1');
      expect(record?.localId, 'local-user-1');
      expect(record?.serverId, isNull);
      expect(
        (await repository.pendingOperations()).single.clientRecordId,
        'local-user-1',
      );
    },
  );

  test(
    'update and delete before sync coalesce into the same pending create',
    () async {
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: 'local-user-2',
        operation: 'create',
        payload: {'name': 'Ana'},
      );
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: 'local-user-2',
        operation: 'update',
        payload: {'name': 'Alicia'},
      );
      expect(
        (await repository.pendingOperations()).single.payload['name'],
        'Alicia',
      );
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: 'local-user-2',
        operation: 'delete',
        payload: const {},
      );
      expect(await repository.pendingOperations(), isEmpty);
      expect(
        (await repository.read('User', 'local-user-2'))?.deletedAt,
        isNotNull,
      );
    },
  );

  test(
    'create response maps numeric server identity without duplicating the local row',
    () async {
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: 'local-user-3',
        operation: 'create',
        payload: {'name': 'Ana'},
      );
      await SyncEngine(repository, _MappingTransport('3')).sync();
      expect(
        (await repository.summaries(
          entity: 'User',
        )).where((item) => item.localId == 'local-user-3').length,
        1,
      );
      expect((await repository.read('User', 'local-user-3'))?.serverId, '3');
      expect((await repository.read('User', '3'))?.localId, 'local-user-3');
    },
  );

  test(
    'create response supports UUIDs, pull reconciliation and idempotent retry',
    () async {
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: 'local-user-4',
        operation: 'create',
        payload: {'name': 'Ana'},
      );
      final transport = _MappingTransport(
        '8f3c7b3e-9a2b-4b30-9e7d-1a2b3c4d5e6f',
      );
      final engine = SyncEngine(repository, transport);
      await engine.sync();
      await engine.sync();
      expect(transport.pushCount, 1);
      expect(
        (await repository.summaries(
          entity: 'User',
        )).where((item) => item.localId == 'local-user-4').length,
        1,
      );
    },
  );

  test('conflict preserves local data and marks explicit state', () async {
    await repository.applyLocalMutation(
      entity: 'User',
      recordId: 'local-user-5',
      operation: 'create',
      payload: {'name': 'Ana'},
    );
    final operation = (await repository.pendingOperations()).single;
    await repository.reconcilePush(
      operation,
      const PushResult(
        operationId: 'ignored',
        status: SyncState.conflict,
        error: 'Conflicto de versión',
      ),
    );
    final record = await repository.read('User', 'local-user-5');
    expect(record?.data['name'], 'Ana');
    expect(record?.syncState, SyncState.conflict);
  });

  test('restores the UAP snapshot and truthful offline state', () async {
    const snapshot = UapSnapshot(
      manifest: {'name': 'cached'},
      schema: {
        'entities': [
          {'name': 'User'},
        ],
      },
      tools: {'tools': []},
      permissions: {},
      businessRules: {},
    );
    await repository.saveSnapshot(snapshot);
    await repository.saveBackendStatus('offline');
    final restored = await repository.cachedSnapshot();
    expect(restored?.manifest['name'], 'cached');
    expect(await repository.backendStatus(), 'offline');
  });

  test(
    'applies offline update and delete as one durable outbox operation',
    () async {
      await repository.upsert(
        entity: 'User',
        recordId: '7',
        data: {'id': 7, 'name': 'Ana'},
      );
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: '7',
        operation: 'update',
        payload: {'name': 'Alicia'},
        operationId: 'op-update',
      );
      expect((await repository.read('User', '7'))?.data['name'], 'Alicia');
      expect(
        (await repository.pendingOperations()).single.operationId,
        'op-update',
      );
      await repository.applyLocalMutation(
        entity: 'User',
        recordId: '7',
        operation: 'delete',
        payload: const {},
        operationId: 'op-delete',
      );
      expect((await repository.read('User', '7'))?.deletedAt, isNotNull);
      expect(
        (await repository.pendingOperations()).map((item) => item.operationId),
        ['op-update', 'op-delete'],
      );
    },
  );

  test('preserves typed product price and stock in offline outbox', () async {
    await repository.upsert(
      entity: 'Product',
      recordId: '2',
      data: {'id': 2, 'price': 20000, 'stock': 4},
    );
    await repository.applyLocalMutation(
      entity: 'Product',
      recordId: '2',
      operation: 'update',
      payload: {'id': 2, 'price': 25000, 'stock': 10},
      operationId: 'product-2-update',
    );
    final record = await repository.read('Product', '2');
    final operation = (await repository.pendingOperations()).single;
    expect(record?.data['price'], 25000);
    expect(record?.data['stock'], 10);
    expect(operation.payload, {'id': 2, 'price': 25000, 'stock': 10});
  });

  test('preserves a string price type in offline serialization', () async {
    await repository.applyLocalMutation(
      entity: 'Product',
      recordId: '2',
      operation: 'update',
      payload: {'id': 2, 'price': '25000', 'stock': 10},
      operationId: 'product-2-string-update',
    );
    final operation = (await repository.pendingOperations()).single;
    expect(operation.payload, {'id': 2, 'price': '25000', 'stock': 10});
    expect(operation.payload['price'], isA<String>());
    await SyncEngine(repository, _FakeTransport()).sync();
    expect((await repository.read('Product', '2'))?.data['price'], '25000');
  });

  test('syncs in order and applies server changes', () async {
    final operation = await repository.enqueue(
      entity: 'User',
      recordId: 'u-1',
      operation: 'create',
      payload: {'name': 'A'},
      operationId: 'op-1',
    );
    final transport = _FakeTransport();
    await SyncEngine(repository, transport).sync();
    expect(transport.pushed, [operation]);
    expect((await repository.read('User', 'u-1'))?.syncState, SyncState.synced);
    expect(await repository.cursor(), '2');
  });

  test('coalesces concurrent sync calls into one flight', () async {
    await repository.enqueue(
      entity: 'User',
      recordId: 'u-1',
      operation: 'create',
      payload: {'name': 'A'},
      operationId: 'op-single-flight',
    );
    final transport = _FakeTransport();
    final engine = SyncEngine(repository, transport);
    await Future.wait([engine.sync(), engine.sync()]);
    expect(transport.pushed, ['op-single-flight']);
  });

  test('new backend generation clears remote cache but preserves pending data', () async {
    await repository.upsert(entity: 'User', recordId: 'old', data: {'name': 'Old'});
    await repository.applyLocalMutation(entity: 'User', recordId: 'pending', operation: 'create', payload: {'name': 'Keep'});
    await repository.saveBackendGeneration('old-generation');
    await SyncEngine(repository, _ResetTransport()).sync();
    expect(await repository.read('User', 'old'), isNull);
    expect((await repository.read('User', 'pending'))?.syncState, SyncState.conflict);
    expect(await repository.pendingOperations(), isEmpty);
    expect(await repository.cursor(), '0');
  });

  test('same backend generation keeps cache and cursor', () async {
    await repository.upsert(entity: 'User', recordId: 'same', data: {'name': 'Keep'});
    await repository.saveBackendGeneration('same-generation');
    await repository.saveCursor('7');
    await SyncEngine(repository, _SameTransport()).sync();
    expect(await repository.read('User', 'same'), isNotNull);
    expect(await repository.cursor(), '7');
  });

  test('broker retains relevant exact tool ids and bounds context', () {
    final snapshot = UapSnapshot(
      manifest: {'name': 'service'},
      schema: {
        'entities': List.generate(
          100,
          (i) => {
            'name': 'Noise$i',
            'fields': ['field$i'],
          },
        ),
      },
      tools: {
        'tools':
            List.generate(
              80,
              (i) => {
                'id': 'noise$i.list',
                'name': 'Noise $i',
                'operation': 'list',
                'inputSchema': {'properties': {}},
              },
            )..add({
              'id': 'patient.update',
              'name': 'Update patient',
              'operation': 'update',
              'inputSchema': {
                'properties': {'name': {}},
              },
            }),
      },
      permissions: {},
      businessRules: {},
    );
    final context = const ContextBroker(maxCharacters: 900).select(
      snapshot: snapshot,
      localRecords: const [],
      request: 'update patient name',
      status: 'pending',
    );
    expect(
      context.tools.any((tool) => tool.startsWith('patient.update |')),
      isTrue,
    );
    expect(
      context.tools.join().length + context.entities.join().length,
      lessThanOrEqualTo(900),
    );
  });
}

class _FakeTransport implements SyncTransport {
  final pushed = <String>[];
  @override
  Future<Map<String, dynamic>> state() async => {'generation': 'test-generation'};
  @override
  Future<Map<String, dynamic>> pull(String cursor) async => {
    'cursor': '2',
    'changes': [
      {
        'entity': 'User',
        'recordId': 'u-1',
        'operation': 'create',
        'payload': {'name': 'A'},
        'version': 2,
      },
    ],
  };
  @override
  Future<List<PushResult>> push(List<OutboxOperation> operations) async {
    pushed.addAll(operations.map((item) => item.operationId));
    return operations
        .map(
          (item) => PushResult(
            operationId: item.operationId,
            status: SyncState.synced,
            record: LocalRecord(
              entity: item.entity,
              localId: item.localId,
              serverId:
                  item.serverId ??
                  (item.operation == 'create'
                      ? 'server-${item.operationId}'
                      : item.localId),
              data: item.payload,
              serverVersion: 1,
              updatedAt: DateTime.now(),
            ),
          ),
        )
        .toList();
  }
}

class _MappingTransport implements SyncTransport {
  _MappingTransport(this.serverId);
  final String serverId;
  int pushCount = 0;
  @override
  Future<Map<String, dynamic>> state() async => {'generation': 'test-generation'};
  @override
  Future<Map<String, dynamic>> pull(String cursor) async => {
    'cursor': cursor,
    'changes': [
      {
        'entity': 'User',
        'serverId': serverId,
        'clientRecordId': 'local-user-3',
        'operation': 'create',
        'payload': {'id': serverId, 'name': 'Ana'},
        'version': 1,
      },
    ],
  };
  @override
  Future<List<PushResult>> push(List<OutboxOperation> operations) async {
    pushCount++;
    return operations
        .map(
          (item) => PushResult(
            operationId: item.operationId,
            status: SyncState.synced,
            serverId: serverId,
            serverVersion: 1,
            clientRecordId: item.clientRecordId,
            record: LocalRecord(
              entity: item.entity,
              localId: item.localId,
              serverId: serverId,
              data: {...item.payload, 'id': serverId},
              serverVersion: 1,
              updatedAt: DateTime.now(),
            ),
          ),
        )
        .toList();
  }
}

class _ResetTransport implements SyncTransport {
  @override
  Future<Map<String, dynamic>> state() async => {'generation': 'new-generation'};
  @override
  Future<Map<String, dynamic>> pull(String cursor) async => {'cursor': '0', 'changes': []};
  @override
  Future<List<PushResult>> push(List<OutboxOperation> operations) async => const [];
}

class _SameTransport implements SyncTransport {
  @override
  Future<Map<String, dynamic>> state() async => {'generation': 'same-generation'};
  @override
  Future<Map<String, dynamic>> pull(String cursor) async => {'cursor': cursor, 'changes': []};
  @override
  Future<List<PushResult>> push(List<OutboxOperation> operations) async => const [];
}
