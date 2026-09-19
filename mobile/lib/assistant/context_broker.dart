import 'dart:convert';
import '../offline/models.dart';
import '../uap/models.dart';

class AssistantContext {
  const AssistantContext({
    required this.service,
    required this.entities,
    required this.tools,
    required this.records,
    required this.status,
  });
  final String service;
  final List<String> entities;
  final List<String> tools;
  final List<String> records;
  final String status;
}

class ContextBroker {
  const ContextBroker({this.maxCharacters = 4200});
  final int maxCharacters;

  AssistantContext select({
    required UapSnapshot snapshot,
    required List<LocalRecord> localRecords,
    required String request,
    required String status,
  }) {
    final terms = _terms(request);
    final entities = _entitySummaries(snapshot.schema).toList()
      ..sort((a, b) => _score(b, terms).compareTo(_score(a, terms)));
    final tools = snapshot.toolList.map(_toolSummary).toList()
      ..sort((a, b) => _score(b, terms).compareTo(_score(a, terms)));
    final records = localRecords.map((record) => _safeRecord(record)).toList()
      ..sort((a, b) => _score(b, terms).compareTo(_score(a, terms)));
    var remaining = maxCharacters - status.length - 120;
    final selectedEntities = <String>[];
    final selectedTools = <String>[];
    final selectedRecords = <String>[];
    for (final value in [...tools, ...entities, ...records]) {
      if (value.length > remaining) continue;
      remaining -= value.length + 1;
      if (tools.contains(value))
        selectedTools.add(value);
      else if (entities.contains(value))
        selectedEntities.add(value);
      else
        selectedRecords.add(value);
    }
    return AssistantContext(
      service: _service(snapshot),
      entities: selectedEntities,
      tools: selectedTools,
      records: selectedRecords,
      status: status,
    );
  }

  String _service(UapSnapshot snapshot) => _clip(
    _safeToken(
      (snapshot.manifest['name'] ??
              snapshot.manifest['serviceName'] ??
              'UAP service')
          .toString(),
    ),
    100,
  );
  Iterable<String> _entitySummaries(Map<String, dynamic> schema) sync* {
    final raw = schema['entities'] ?? schema['models'] ?? schema['tables'];
    final Iterable<Map> items = raw is List
        ? raw.whereType<Map>()
        : raw is Map
        ? raw.entries.map((entry) => {'name': entry.key, 'fields': entry.value})
        : const <Map>[];
    for (final item in items.take(40)) {
      final fields = item['fields'] ?? item['properties'] ?? item['attributes'];
      final Iterable<String> names = fields is Map
          ? fields.keys.map((key) => key.toString())
          : fields is List
          ? fields.whereType<Map>().map(
              (field) => (field['name'] ?? field['id'] ?? '').toString(),
            )
          : const <String>[];
      yield '${_safeToken((item['name'] ?? item['id'] ?? 'entity').toString())}(${names.take(16).map(_safeToken).join(', ')})';
    }
  }

  String _toolSummary(UapTool tool) {
    final properties =
        (tool.inputSchema['properties'] as Map?)?.keys
            .map((value) => value.toString())
            .take(20)
            .map(_safeToken)
            .join(', ') ??
        '';
    return '${tool.id} | ${_safeToken(tool.name)} | ${tool.operation} | input: ${properties.isEmpty ? 'none' : properties}';
  }

  String _safeRecord(LocalRecord record) =>
      '${_safeToken(record.entity)}/${_safeToken(record.recordId)} ${_clip(_redact(jsonEncode(record.data)), 260)} [${record.syncState.name}]';
  String _safeToken(String value) =>
      _clip(value.replaceAll(RegExp(r'[^A-Za-z0-9_.:/ -]'), ''), 80);
  String _clip(String value, int max) =>
      value.length <= max ? value : '${value.substring(0, max - 3)}...';
  String _redact(String value) => value
      .replaceAll(
        RegExp(r'https?://[^\s"]+', caseSensitive: false),
        '[URL omitted]',
      )
      .replaceAll(
        RegExp(
          r'\b(select|insert|update|delete|drop|union)\s+[^\n]+',
          caseSensitive: false,
        ),
        '[query omitted]',
      )
      .replaceAll(
        RegExp(
          r'\b(shell|bash|powershell|reflection|execute code|run command)\b[^\n]*',
          caseSensitive: false,
        ),
        '[unsafe content omitted]',
      );
  Set<String> _terms(String value) => value
      .toLowerCase()
      .split(RegExp(r'\W+'))
      .where((term) => term.length > 2)
      .toSet();
  int _score(String value, Set<String> terms) =>
      terms.where((term) => value.toLowerCase().contains(term)).length;
}
