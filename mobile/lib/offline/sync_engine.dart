import 'dart:convert';
import 'package:http/http.dart' as http;
import 'models.dart';
import 'repository.dart';

abstract class SyncTransport {
  Future<Map<String, dynamic>> pull(String cursor);
  Future<List<PushResult>> push(List<OutboxOperation> operations);
}

class SyncEngine {
  SyncEngine(this.repository, this.transport);
  final OfflineRepository repository;
  final SyncTransport transport;

  Future<void> sync() async {
    final operations = await repository.pendingOperations();
    if (operations.isNotEmpty) {
      for (final operation in operations) {
        final result = (await transport.push([operation])).single;
        await repository.markOperation(
          operation.operationId,
          result.status,
          error: result.error,
        );
        await repository.setState(
          operation.entity,
          operation.recordId,
          result.status,
          version: result.record?.serverVersion,
        );
      }
    }
    final response = await transport.pull(await repository.cursor());
    final changes = (response['changes'] as List? ?? const [])
        .whereType<Map>()
        .map(_change);
    for (final change in changes) {
      await repository.upsert(
        entity: change.entity,
        recordId: change.recordId,
        data: change.payload,
        serverVersion: change.version,
        state: SyncState.synced,
        deletedAt: change.operation == 'delete' ? DateTime.now() : null,
      );
    }
    if (response['cursor'] != null)
      await repository.saveCursor(response['cursor'].toString());
  }

  SyncChange _change(Map raw) => SyncChange(
    entity: raw['entity'].toString(),
    recordId: raw['recordId'].toString(),
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
                'recordId': operation.recordId,
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
    return values
        .whereType<Map>()
        .map(
          (value) => PushResult(
            operationId: value['operationId'].toString(),
            status: SyncState.values.byName(value['status'].toString()),
            error: value['error']?.toString(),
          ),
        )
        .toList();
  }
}
