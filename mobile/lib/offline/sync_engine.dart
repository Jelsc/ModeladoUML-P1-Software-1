import 'dart:convert';
import 'package:http/http.dart' as http;
import 'models.dart';
import 'repository.dart';

abstract class SyncTransport {
  Future<Map<String, dynamic>> state();
  Future<Map<String, dynamic>> pull(String cursor);
  Future<List<PushResult>> push(List<OutboxOperation> operations);
}

class SyncEngine {
  SyncEngine(this.repository, this.transport);
  final OfflineRepository repository;
  final SyncTransport transport;
  Future<SyncState>? _running;

  Future<SyncState> sync() =>
      _running ??= _sync().whenComplete(() => _running = null);

  Future<SyncState> _sync() async {
    var finalState = SyncState.synced;
    final serverState = await transport.state();
    final generation = serverState['generation']?.toString();
    if (generation == null || generation.isEmpty)
      throw StateError('El backend no publicó una generación de dataset.');
    final localGeneration = await repository.backendGeneration();
    if (localGeneration != null && localGeneration != generation) {
      await repository.resetRemoteCache(generation);
    } else if (localGeneration == null && await repository.hasRemoteCache()) {
      await repository.resetRemoteCache(generation);
    } else if (localGeneration == null) {
      await repository.saveBackendGeneration(generation);
    }
    final operations = await repository.pendingOperations();
    if (operations.isNotEmpty) {
      for (final operation in operations) {
        final result = (await transport.push([operation])).single;
        await repository.reconcilePush(operation, result);
        if (result.status == SyncState.conflict)
          finalState = SyncState.conflict;
        if (result.status == SyncState.failed) finalState = SyncState.failed;
      }
    }
    final response = await transport.pull(await repository.cursor());
    final changes = (response['changes'] as List? ?? const [])
        .whereType<Map>()
        .map(_change);
    for (final change in changes) {
      await repository.applyPull(
        entity: change.entity,
        serverId: change.serverId,
        localId: change.localId,
        clientRecordId: change.clientRecordId,
        operationId: change.operationId,
        operation: change.operation,
        data: change.payload,
        version: change.version,
      );
    }
    if (response['cursor'] != null)
      await repository.saveCursor(response['cursor'].toString());
    await repository.saveMetadata(
      'last_sync_at',
      DateTime.now().toUtc().toIso8601String(),
    );
    return finalState;
  }

  SyncChange _change(Map raw) => SyncChange(
    entity: raw['entity'].toString(),
    serverId: (raw['serverId'] ?? raw['recordId'] ?? '').toString(),
    localId: raw['localId']?.toString(),
    clientRecordId: raw['clientRecordId']?.toString(),
    operationId: raw['operationId']?.toString(),
    operation: raw['operation'].toString(),
    payload: (raw['payload'] as Map? ?? const {}).cast<String, dynamic>(),
    version: (raw['version'] as num?)?.toInt() ?? 0,
  );
}

class HttpSyncTransport implements SyncTransport {
  HttpSyncTransport(
    this.baseUrl, {
    http.Client? client,
    Map<String, String> headers = const {},
  }) : _http = client ?? http.Client(),
       _headers = headers;
  final String baseUrl;
  final http.Client _http;
  final Map<String, String> _headers;
  @override
  Future<Map<String, dynamic>> state() async {
    final response = await _http.get(Uri.parse('$baseUrl/uap/v1/sync/state'), headers: _headers);
    if (response.statusCode == 404) throw StateError('Protocolo de sincronización no disponible');
    if (response.statusCode < 200 || response.statusCode >= 300)
      throw Exception('Falló la lectura del estado de sincronización (HTTP ${response.statusCode}).');
    return (jsonDecode(response.body) as Map).cast<String, dynamic>();
  }
  @override
  Future<Map<String, dynamic>> pull(String cursor) async {
    final response = await _http.get(
      Uri.parse(
        '$baseUrl/uap/v1/sync/changes?since=${Uri.encodeQueryComponent(cursor)}',
      ),
      headers: _headers,
    );
    if (response.statusCode == 404)
      throw StateError('Protocolo de sincronización no disponible');
    if (response.statusCode < 200 || response.statusCode >= 300)
      throw Exception(
        'Falló la descarga de sincronización (HTTP ${response.statusCode}).',
      );
    return (jsonDecode(response.body) as Map).cast<String, dynamic>();
  }

  @override
  Future<List<PushResult>> push(List<OutboxOperation> operations) async {
    final response = await _http.post(
      Uri.parse('$baseUrl/uap/v1/sync/push'),
      headers: {'content-type': 'application/json', ..._headers},
      body: jsonEncode({
        'operations': operations
            .map(
              (operation) => {
                'operationId': operation.operationId,
                'entity': operation.entity,
                'localId': operation.localId,
                'serverId': operation.serverId,
                'clientRecordId': operation.clientRecordId,
                'recordId': operation.serverId,
                'operation': operation.operation,
                'payload': operation.payload,
                'baseVersion': operation.baseVersion,
              },
            )
            .toList(),
      }),
    );
    if (response.statusCode == 404)
      throw StateError('Protocolo de sincronización no disponible');
    if (response.statusCode < 200 || response.statusCode >= 300)
      throw Exception(
        'Falló la carga de sincronización (HTTP ${response.statusCode}).',
      );
    final values =
        (jsonDecode(response.body) as Map)['results'] as List? ?? const [];
    return values.whereType<Map>().map((value) {
      final rawRecord = value['serverRecord'] ?? value['record'];
      final record = rawRecord is Map
          ? LocalRecord(
              entity:
                  rawRecord['entity']?.toString() ??
                  value['entity']?.toString() ??
                  '',
              localId:
                  value['clientRecordId']?.toString() ??
                  rawRecord['clientRecordId']?.toString() ??
                  value['localId']?.toString() ??
                  '',
              serverId:
                  rawRecord['serverId']?.toString() ??
                  rawRecord['recordId']?.toString() ??
                  rawRecord['id']?.toString() ??
                  value['serverId']?.toString() ??
                  value['recordId']?.toString(),
              data: ((rawRecord['data'] as Map?) ?? rawRecord)
                  .cast<String, dynamic>(),
              serverVersion: (rawRecord['serverVersion'] as num?)?.toInt(),
              updatedAt: DateTime.now().toUtc(),
              syncState: SyncState.synced,
            )
          : null;
      return PushResult(
        operationId: value['operationId'].toString(),
        status: SyncState.values.byName(value['status'].toString()),
        record: record,
        serverId:
            value['serverId']?.toString() ??
            (rawRecord is Map
                ? (rawRecord['serverId'] ??
                          rawRecord['recordId'] ??
                          rawRecord['id'])
                      ?.toString()
                : null),
        serverVersion:
            (value['serverVersion'] as num?)?.toInt() ??
            (rawRecord is Map
                ? (rawRecord['serverVersion'] as num?)?.toInt()
                : null),
        clientRecordId: value['clientRecordId']?.toString(),
        error: value['error']?.toString(),
      );
    }).toList();
  }
}
