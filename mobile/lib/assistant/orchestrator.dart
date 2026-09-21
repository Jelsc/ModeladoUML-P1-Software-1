import 'dart:convert';

import '../uap/models.dart';
import '../offline/models.dart';
import 'context_broker.dart';

import 'pipeline.dart';

export 'pipeline.dart';

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
    try {
      final decoded = const IntentInterpreter().decode(raw);
      final intent = const UapCommandParser().parseModel(decoded, tools);
      final validated = const UapValidator().validate(intent, tools);
      if (validated.isToolCall || request == null) return validated;
      final deterministic = const UapCommandParser().fromSpanish(
        request,
        tools,
        schema ?? const {},
      );
      return const UapValidator().validate(deterministic, tools);
    } catch (_) {
      if (request != null) return _fallback(request, tools, schema ?? {});
      throw const FormatException(
        'El modelo local devolvió una respuesta no válida.',
      );
    }
  }

  static AssistantIntent _fallback(
    String request,
    List<UapTool> tools,
    Map<String, dynamic> schema,
  ) {
    return const UapValidator().validate(
      const UapCommandParser().fromSpanish(request, tools, schema),
      tools,
    );
  }
}

class AssistantResultFormatter {
  static String read(UapTool tool, dynamic result) {
    final data = result is Map ? result['data'] : result;
    if (data is List) {
      final entity = _entityLabel(tool);
      if (data.isEmpty) return 'No hay ${entity} para mostrar.';
      final records = data.whereType<Map>().map(_record).join(' · ');
      return 'Encontré ${data.length} ${entity}: $records';
    }
    final detail = _detail(data);
    return detail.isEmpty
        ? 'No encontré datos para ${_entityLabel(tool)}.'
        : 'Encontré ${_entityLabel(tool, definite: true)}: $detail.';
  }

  static String mutation(
    UapTool tool,
    dynamic result, {
    Map<String, dynamic> input = const {},
  }) {
    final operation = UapValidator.operation(tool);
    final verb =
        const {
          'create': 'Registré',
          'update': 'Actualicé',
          'delete': 'Eliminé',
        }[operation] ??
        'Realicé';
    final data = result is Map ? result['data'] : null;
    if (result is Map && result.containsKey('data') && data == null) {
      return 'No confirmé la operación sobre ${_entityLabel(tool, definite: false)}: el backend no devolvió los valores actualizados.';
    }
    if (data is Map) {
      final record = data.cast<String, dynamic>();
      final missing = input.keys
          .where((key) => input[key] != null && record[key] == null)
          .toList();
      final different = input.keys.where((key) {
        final expected = input[key];
        final actual = record[key];
        return expected != null &&
            actual != null &&
            expected.toString() != actual.toString();
      }).toList();
      var text =
          '$verb ${_entityLabel(tool, definite: true)}: ${_record(record)}.';
      if (missing.isNotEmpty || different.isNotEmpty) {
        final fields = {...missing, ...different}.map(_fieldLabel).join(', ');
        return 'No confirmé la actualización del ${_entityLabel(tool, definite: false)}: el backend devolvió valores ausentes o diferentes para $fields. Resultado real: ${_record(record)}.';
      }
      return text;
    }
    final message = result is Map && result['message'] is String
        ? result['message'] as String
        : null;
    return '$verb ${_entityLabel(tool, definite: true)}${message == null ? '.' : '. El backend confirmó la operación.'}';
  }

  static String cancelled(UapTool tool) =>
      'No se realizó la acción sobre ${_entityLabel(tool, definite: true)} porque se canceló la confirmación.';

  static String failure(UapTool tool, Object error) =>
      'No pude realizar la acción sobre ${_entityLabel(tool, definite: true)}. El backend rechazó la solicitud.';

  static String _detail(dynamic result) {
    if (result is Map && result['data'] != null) return _detail(result['data']);
    if (result is Map && result['message'] is String) return '';
    if (result is List) return '${result.length} elementos';
    if (result is Map) return _record(result);
    return result == null ? '' : _clip(jsonEncode(result), 500);
  }

  static String _entityLabel(UapTool tool, {bool definite = false}) {
    final entity = (tool.raw['entity'] ?? tool.id.split('.').first).toString();
    final singular = entity.endsWith('s') && !entity.endsWith('ss')
        ? entity.substring(0, entity.length - 1)
        : entity;
    const labels = {
      'user': 'usuarios',
      'product': 'productos',
      'order': 'pedidos',
    };
    final label = labels[singular] ?? entity;
    return definite
        ? 'el ${label.substring(0, label.length - (label.endsWith('s') ? 1 : 0))}'
        : label;
  }

  static String _record(Map record) => record.entries
      .map((entry) => '${_fieldLabel(entry.key)}: ${_value(entry.value)}')
      .join(', ');

  static String _fieldLabel(String field) =>
      const {
        'name': 'nombre',
        'apellido': 'apellido',
        'email': 'correo',
        'active': 'activo',
        'price': 'precio',
        'stock': 'stock',
        'lastName': 'apellido',
      }[field] ??
      field;

  static String _value(dynamic value) {
    if (value is bool) return value ? 'sí' : 'no';
    return value?.toString() ?? 'sin dato';
  }

  static String _clip(String value, int max) =>
      value.length <= max ? value : '${value.substring(0, max - 3)}...';
}
