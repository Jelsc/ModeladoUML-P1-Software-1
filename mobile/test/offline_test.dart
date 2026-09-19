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
              recordId: item.recordId,
              data: item.payload,
              serverVersion: 1,
              updatedAt: DateTime.now(),
            ),
          ),
        )
        .toList();
  }
}
