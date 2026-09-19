import 'dart:convert';

import '../uap/models.dart';
import '../offline/models.dart';
import 'context_broker.dart';

class AssistantIntent {
  const AssistantIntent.answer(this.text)
    : toolId = null,
      input = const {},
      isToolCall = false;
  const AssistantIntent.tool(this.toolId, this.input)
    : text = null,
      isToolCall = true;
  final String? text;
  final String? toolId;
  final Map<String, dynamic> input;
  final bool isToolCall;
}

class PromptBuilder {
  static const maxPromptCharacters = 6000;

  static String build(
    UapSnapshot snapshot,
    String request, {
    List<LocalRecord> localRecords = const [],
    String syncStatus = 'local-only',
  }) {
    final context =
        const ContextBroker(maxCharacters: maxPromptCharacters - 800).select(
          snapshot: snapshot,
          localRecords: localRecords,
          request: request,
          status: syncStatus,
        );
    final entities = context.entities.join('; ');
    final tools = context.tools.join('\n');
    final records = context.records.join('; ');
    final prompt =
        '''
You are a cautious offline assistant for this UAP service.
Return exactly one JSON object, with either {"answer":"..."} or {"tool":"TOOL_ID","input":{...}}.
Never invent tools or fields. Never output URLs, SQL, shell commands, reflection, or executable code.
Service: ${_clip(context.service, 100)}
Sync state: ${_clip(context.status, 120)}
Entities and fields: ${entities.isEmpty ? 'none discovered' : entities}
Tools (id is exact): ${tools.isEmpty ? 'none discovered' : tools}
Local record summaries: ${records.isEmpty ? 'none selected' : records}
User request: ${jsonEncode(_safeRequest(request))}
If a request does not match an allowed tool, return an answer explaining that it cannot be performed.
''';
    return _clipPrompt(prompt);
  }

  static String _clipPrompt(String value) {
    if (value.length <= maxPromptCharacters) return value;
    return '${value.substring(0, maxPromptCharacters - 80)}\n[low-priority descriptions omitted]\nReturn JSON only.';
  }

  static String _safeRequest(String request) {
    var value = request.replaceAll(
      RegExp(r'https?://[^\s]+', caseSensitive: false),
      '[URL omitted]',
    );
    value = value.replaceAll(
      RegExp(
        r'\b(select|insert|update|delete|drop|union)\s+[^\n]+',
        caseSensitive: false,
      ),
      '[query instruction omitted]',
    );
    value = value.replaceAll(
      RegExp(
        r'\b(shell|bash|powershell|reflection|execute code|run command)\b[^\n]*',
        caseSensitive: false,
      ),
      '[unsafe instruction omitted]',
    );
    return _clip(value.trim(), 700);
  }

  static String _clip(String value, int max) =>
      value.length <= max ? value : '${value.substring(0, max - 3)}...';
}

class IntentValidator {
  static AssistantIntent parse(
    String raw,
    List<UapTool> tools, {
    String? request,
    Map<String, dynamic>? schema,
  }) {
    dynamic decoded;
    try {
      var normalized = raw.trim();
      if (normalized.startsWith('```')) {
        normalized = normalized.replaceFirst(
          RegExp(r'^```(?:json)?\s*', caseSensitive: false),
          '',
        );
        normalized = normalized.replaceFirst(RegExp(r'\s*```$'), '');
      }
      final start = normalized.indexOf('{');
      final end = normalized.lastIndexOf('}');
      if (start >= 0 && end > start)
        normalized = normalized.substring(start, end + 1);
      decoded = jsonDecode(normalized);
    } catch (_) {
      if (request != null) return _fallback(request, tools, schema ?? {});
      throw const FormatException(
        'El modelo local devolvió una respuesta no válida.',
      );
    }
    if (decoded is! Map) {
      throw const FormatException(
        'La respuesta del modelo local debe ser un objeto JSON.',
      );
    }
    final value = decoded.cast<String, dynamic>();
    if (value['answer'] is String && value.length == 1) {
      return AssistantIntent.answer(value['answer'] as String);
    }
    final id = value['tool'];
    final input = value['input'];
    final tool = tools.where((item) => item.id == id).firstOrNull;
    if (tool == null ||
        input is! Map ||
        value.keys.any((key) => key != 'tool' && key != 'input')) {
      throw const FormatException(
        'La herramienta solicitada no está en la lista permitida descubierta.',
      );
    }
    final fields = input.cast<String, dynamic>();
    final properties = (tool.inputSchema['properties'] as Map?)?.keys
        .map((key) => key.toString())
        .toSet();
    if (fields.keys.any(
      (key) => properties == null || !properties.contains(key),
    )) {
      throw const FormatException('La entrada contiene un campo desconocido.');
    }
    return AssistantIntent.tool(tool.id, fields);
  }

  static AssistantIntent _fallback(
    String request,
    List<UapTool> tools,
    Map<String, dynamic> schema,
  ) {
    final normalized = _normalize(request);
    final operations = <String>{};
    for (final entry in _operationWords.entries) {
      if (entry.value.any((word) => _hasWord(normalized, _normalize(word)))) {
        operations.add(entry.key);
      }
    }
    if (operations.length != 1) return _clarification();
    final operation = operations.single;
    final operationTools = tools
        .where((tool) => _toolOperation(tool) == operation)
        .toList();
    if (operationTools.isEmpty) return _clarification();

    final entityTerms = <String>{
      ..._schemaEntityNames(schema),
      ...operationTools.map(_toolEntity),
    }..removeWhere((value) => value.isEmpty);
    final mentionedEntities = entityTerms
        .where((entity) => _hasWord(normalized, _normalize(entity)))
        .toList();
    final candidates = mentionedEntities.isEmpty
        ? operationTools
        : operationTools
              .where(
                (tool) => mentionedEntities.any(
                  (entity) =>
                      _normalize(_toolEntity(tool)) == _normalize(entity),
                ),
              )
              .toList();
    if (candidates.length != 1) return _clarification();

    final tool = candidates.single;
    final properties =
        ((tool.inputSchema['properties'] as Map?)?.keys ?? const [])
            .map((key) => key.toString())
            .toList();
    final input = _explicitFields(request, properties);
    if ((operation == 'get' || operation == 'delete') && input.isEmpty) {
      return _clarification();
    }
    if ((operation == 'create' || operation == 'update') &&
        properties.isNotEmpty &&
        input.isEmpty) {
      return _clarification();
    }
    return AssistantIntent.tool(tool.id, input);
  }

  static AssistantIntent _clarification() => const AssistantIntent.answer(
    'No pude determinar una única acción con los datos disponibles. Indicá la operación, la entidad y, si corresponde, cada campo con su valor.',
  );

  static String _toolOperation(UapTool tool) {
    final value = tool.operation.trim().toLowerCase();
    if (_operationWords.containsKey(value)) return value;
    final id = tool.id.toLowerCase();
    return _operationWords.keys.firstWhere(
      (operation) => id.endsWith('.$operation'),
      orElse: () => '',
    );
  }

  static String _toolEntity(UapTool tool) =>
      tool.raw['entity']?.toString() ?? tool.id.split('.').first;

  static Set<String> _schemaEntityNames(Map<String, dynamic> schema) {
    final raw = schema['entities'] ?? schema['models'] ?? schema['tables'];
    if (raw is List) {
      return raw
          .whereType<Map>()
          .map((item) => (item['name'] ?? item['id'] ?? '').toString())
          .toSet();
    }
    if (raw is Map) return raw.keys.map((key) => key.toString()).toSet();
    return {};
  }

  static Map<String, dynamic> _explicitFields(
    String request,
    List<String> properties,
  ) {
    final matches = <({String field, int start, String value})>[];
    for (final field in properties) {
      final normalizedField = _normalize(field);
      if (normalizedField.isEmpty) continue;
      final match = RegExp(
        r'(^|\s)' +
            RegExp.escape(normalizedField) +
            r'(?:\s*[:=]\s*|\s+)([^,;]+)',
        caseSensitive: false,
      ).firstMatch(request);
      if (match != null) {
        matches.add((
          field: field,
          start: match.start,
          value: match.group(2)!.trim(),
        ));
      }
    }
    matches.sort((a, b) => a.start.compareTo(b.start));
    final result = <String, dynamic>{};
    for (var index = 0; index < matches.length; index++) {
      final current = matches[index];
      var value = current.value;
      if (index + 1 < matches.length) {
        final next = matches[index + 1];
        final boundary = request.substring(current.start, next.start);
        final fieldStart = boundary.toLowerCase().lastIndexOf(
          current.field.toLowerCase(),
        );
        if (fieldStart >= 0)
          value = boundary.substring(fieldStart + current.field.length).trim();
      }
      value = value.replaceFirst(RegExp(r'^[=: ]+'), '').trim();
      if (value.isNotEmpty) result[current.field] = value;
    }
    return result;
  }

  static bool _hasWord(String value, String word) =>
      RegExp(r'(^|\s)' + RegExp.escape(word) + r'($|\s)').hasMatch(value);

  static String _normalize(String value) => value
      .toLowerCase()
      .replaceAll('á', 'a')
      .replaceAll('é', 'e')
      .replaceAll('í', 'i')
      .replaceAll('ó', 'o')
      .replaceAll('ú', 'u')
      .replaceAll('ü', 'u')
      .replaceAll(RegExp(r'[^a-z0-9_.:=-]+'), ' ')
      .trim();

  static const _operationWords = <String, List<String>>{
    'create': ['crear', 'crea', 'agregar', 'agrega', 'registrar', 'registra'],
    'list': [
      'listar',
      'lista',
      'mostrar',
      'muestra',
      'consultar',
      'consulta',
      'ver',
    ],
    'get': ['obtener', 'obtén', 'obten', 'detalle', 'dame'],
    'update': [
      'actualizar',
      'actualiza',
      'modificar',
      'modifica',
      'editar',
      'edita',
    ],
    'delete': ['eliminar', 'elimina', 'borrar', 'borra'],
  };
}

class AssistantResultFormatter {
  static String read(UapTool tool, dynamic result) {
    final detail = _detail(result);
    return detail.isEmpty
        ? 'Encontré resultados para ${tool.name}.'
        : 'Encontré resultados para ${tool.name}: $detail';
  }

  static String mutation(UapTool tool, dynamic result) =>
      'Realicé ${tool.name}${_detail(result).isEmpty ? '.' : ': ${_detail(result)}'}';

  static String cancelled(UapTool tool) =>
      'No se realizó la acción para ${tool.name} porque se canceló la confirmación.';

  static String failure(UapTool tool, Object error) =>
      'No pude realizar la acción para ${tool.name}. ${error.toString().replaceFirst('Exception: ', '')}';

  static String _detail(dynamic result) {
    if (result is Map && result['message'] is String)
      return result['message'] as String;
    if (result is Map && result['data'] != null)
      return jsonEncode(result['data']);
    if (result is List) return '${result.length} item(s)';
    return result == null ? '' : _clip(jsonEncode(result), 500);
  }

  static String _clip(String value, int max) =>
      value.length <= max ? value : '${value.substring(0, max - 3)}...';
}

extension<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null