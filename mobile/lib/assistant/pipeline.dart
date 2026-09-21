import 'dart:convert';

import '../uap/models.dart';

dynamic coerceValue(dynamic value, Map? definition) {
  final type = _schemaType(definition);
  if (value == null) {
    if (_nullable(definition)) return null;
    throw const FormatException('El valor no puede quedar vacío.');
  }
  switch (type) {
    case 'integer':
      return _coerceNumber(value, integer: true);
    case 'number':
    case 'double':
      return _coerceNumber(value);
    case 'boolean':
      return _coerceBoolean(value);
    case 'string':
      return _coerceString(value);
    default:
      return value;
  }
}

String? _schemaType(Map? definition) {
  final type = definition?['type'];
  if (type is List) {
    return type.where((item) => item != 'null').firstOrNull?.toString();
  }
  return type?.toString().toLowerCase();
}

bool _nullable(Map? definition) =>
    definition?['nullable'] == true ||
    definition?['type'] is List && (definition!['type'] as List).contains('null');

String _coerceString(dynamic value) {
  final raw = value.toString().trim();
  if (raw.isEmpty) throw const FormatException('El texto no puede quedar vacío.');
  if (!RegExp(r'^[+-]?[0-9][0-9., ]*$').hasMatch(raw)) return raw;
  try {
    final parsed = _coerceNumber(raw);
    return parsed is double && parsed % 1 != 0
        ? parsed.toString()
        : parsed.toInt().toString();
  } on FormatException {
    return raw;
  }
}

dynamic _coerceNumber(dynamic value, {bool integer = false}) {
  if (value is num) {
    if (!value.isFinite || integer && value % 1 != 0)
      throw FormatException(integer ? 'El valor debe ser un número entero.' : 'El valor numérico no es válido.');
    return integer ? value.toInt() : value;
  }
  final raw = value.toString().trim().replaceAll(' ', '');
  if (raw.isEmpty) throw const FormatException('El valor numérico está vacío.');
  if (!RegExp(r'^[+-]?[0-9]+(?:[.,][0-9]+)*$').hasMatch(raw))
    throw const FormatException('El valor numérico no es válido.');
  final unsigned = raw.startsWith('-') || raw.startsWith('+') ? raw.substring(1) : raw;
  final sign = raw.startsWith('-') ? '-' : '';
  final comma = unsigned.contains(',');
  final dot = unsigned.contains('.');
  String normalized;
  if (comma && dot) {
    final decimal = unsigned.lastIndexOf(',') > unsigned.lastIndexOf('.') ? ',' : '.';
    final grouping = decimal == ',' ? '.' : ',';
    if (unsigned.indexOf(decimal) != unsigned.lastIndexOf(decimal) ||
        unsigned.split(grouping).length > 2)
      throw const FormatException('El valor numérico no es válido.');
    normalized = unsigned.replaceAll(grouping, '').replaceFirst(decimal, '.');
  } else if (comma || dot) {
    final separator = comma ? ',' : '.';
    final parts = unsigned.split(separator);
    if (parts.length != 2 || parts[0].isEmpty || parts[1].isEmpty)
      throw const FormatException('El valor numérico no es válido.');
    final grouped = parts[1].length == 3 && parts[0].length <= 3;
    normalized = grouped ? parts.join() : parts.join('.');
  } else {
    normalized = unsigned;
  }
  final parsed = num.tryParse('$sign$normalized');
  if (parsed == null || !parsed.isFinite)
    throw const FormatException('El valor numérico no es válido.');
  if (integer && parsed % 1 != 0)
    throw const FormatException('El valor debe ser un número entero.');
  return integer || parsed % 1 == 0 ? parsed.toInt() : parsed.toDouble();
}

bool _coerceBoolean(dynamic value) {
  if (value is bool) return value;
  final normalized = UapCommandParser._normalize(value.toString());
  if ({'true', 'verdadero', 'si', 'activo'}.contains(normalized)) return true;
  if ({'false', 'falso', 'no', 'inactivo'}.contains(normalized)) return false;
  throw const FormatException('El valor booleano debe ser verdadero o falso.');
}

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

class IntentInterpreter {
  const IntentInterpreter();

  Map<String, dynamic> decode(String raw) {
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
    final decoded = jsonDecode(normalized);
    if (decoded is! Map)
      throw const FormatException(
        'La respuesta del modelo local debe ser un objeto JSON.',
      );
    return decoded.cast<String, dynamic>();
  }
}

class UapCommandParser {
  const UapCommandParser();

  AssistantIntent parseModel(Map<String, dynamic> value, List<UapTool> tools) {
    if (value['answer'] is String && value.length == 1) {
      return AssistantIntent.answer(value['answer'] as String);
    }
    if (value['tool'] is! String ||
        value['input'] is! Map ||
        value.keys.any((key) => key != 'tool' && key != 'input')) {
      throw const FormatException(
        'La respuesta del modelo local no describe una herramienta UAP permitida.',
      );
    }
    return AssistantIntent.tool(
      value['tool'] as String,
      (value['input'] as Map).cast<String, dynamic>(),
    );
  }

  AssistantIntent fromSpanish(
    String request,
    List<UapTool> tools,
    Map<String, dynamic> schema,
  ) {
    final normalized = _normalize(request);
    final operations = <String>{};
    for (final entry in _operationWords.entries) {
      if (entry.value.any((word) => _hasWord(normalized, _normalize(word))))
        operations.add(entry.key);
    }
    if (operations.length != 1) return _clarification();
    final operation = operations.single;
    final candidates = tools
        .where((tool) => UapValidator.operation(tool) == operation)
        .toList();
    if (candidates.isEmpty) return _clarification();
    final mentioned =
        <String>{
              ..._schemaEntityNames(schema),
              ...candidates.map(UapValidator.entity),
            }
            .where(
              (entity) =>
                  entity.isNotEmpty && _mentionsEntity(normalized, entity),
            )
            .toSet();
    final filtered = mentioned.isEmpty
        ? candidates
        : candidates
              .where(
                (tool) => mentioned.any(
                  (entity) => _entityMatches(UapValidator.entity(tool), entity),
                ),
              )
              .toList();
    if (filtered.length != 1) return _clarification();
    final tool = filtered.single;
    final properties = UapValidator.properties(tool);
    final input = _explicitFields(request, properties);
    if ((operation == 'get' ||
            operation == 'delete' ||
            operation == 'update') &&
        input['id'] == null)
      return _clarification();
    return AssistantIntent.tool(tool.id, input);
  }

  AssistantIntent _clarification() => const AssistantIntent.answer(
    'No pude determinar una única acción con los datos disponibles. Indicá la operación, la entidad y, si corresponde, cada campo con su valor.',
  );

  static Map<String, dynamic> _explicitFields(
    String request,
    Iterable<String> properties,
  ) {
    final result = <String, dynamic>{};
    for (final field in properties) {
      final names = <String>{
        field,
        ..._fieldAliases[field] ?? const <String>[],
      };
      final match = RegExp(
        r'(^|\s)(?:' +
            names.map(RegExp.escape).join('|') +
            r')(?:\s*[:=]\s*|\s+)([^,;]+)',
        caseSensitive: false,
      ).firstMatch(request);
      if (match != null) {
        var value = match.group(2)!.trim();
        value = value.replaceFirst(
          RegExp(r'^(?:en|a|con)\s+', caseSensitive: false),
          '',
        );
        final nextField = RegExp(
          r'\s+(?:' +
              _fieldAliases.values
                  .expand((values) => values)
                  .map(RegExp.escape)
                  .join('|') +
              r'|[A-Za-z_][A-Za-z0-9_]*)\s+(?:[:=]\s*)?',
          caseSensitive: false,
        ).firstMatch(value);
        if (nextField != null)
          value = value.substring(0, nextField.start).trim();
        value = value.replaceFirst(RegExp(r'[.!?]+$'), '').trim();
        if (value.isNotEmpty) result[field] = value;
      }
    }
    return result;
  }

  static Set<String> _schemaEntityNames(Map<String, dynamic> schema) {
    final raw = schema['entities'] ?? schema['models'] ?? schema['tables'];
    if (raw is List)
      return raw
          .whereType<Map>()
          .map((item) => (item['name'] ?? item['id'] ?? '').toString())
          .toSet();
    if (raw is Map) return raw.keys.map((key) => key.toString()).toSet();
    return {};
  }

  static bool _hasWord(String value, String word) =>
      RegExp(r'(^|\s)' + RegExp.escape(word) + r'($|\s)').hasMatch(value);

  static bool _mentionsEntity(String request, String entity) {
    final normalizedEntity = _normalize(entity);
    final aliases = <String>{
      normalizedEntity,
      _singular(normalizedEntity),
      ..._entityAliases[normalizedEntity] ?? const <String>{},
    };
    return aliases.any((alias) => _hasWord(request, alias));
  }

  static bool _entityMatches(String left, String right) {
    final normalizedLeft = _normalize(left);
    final normalizedRight = _normalize(right);
    return normalizedLeft == normalizedRight ||
        _singular(normalizedLeft) == _singular(normalizedRight) ||
        _entityAliases[normalizedLeft]?.contains(normalizedRight) == true ||
        _entityAliases[normalizedRight]?.contains(normalizedLeft) == true;
  }

  static String _singular(String value) {
    if (value.endsWith('ies'))
      return '${value.substring(0, value.length - 3)}y';
    if (value.endsWith('s') && !value.endsWith('ss'))
      return value.substring(0, value.length - 1);
    return value;
  }

  static const _entityAliases = <String, Set<String>>{
    'user': {'usuario', 'usuarios', 'users'},
    'users': {'usuario', 'usuarios', 'user'},
    'product': {'producto', 'productos', 'products'},
    'products': {'producto', 'productos', 'product'},
    'order': {'pedido', 'pedidos', 'orders'},
    'orders': {'pedido', 'pedidos', 'order'},
  };

  static const _fieldAliases = <String, Set<String>>{
    'name': {'nombre'},
    'email': {'correo', 'e-mail'},
    'active': {'activo', 'activa'},
    'price': {'precio', 'valor'},
    'stock': {'existencias', 'inventario'},
    'lastName': {'apellido', 'apellidos'},
    'apellido': {'lastName', 'apellidos'},
  };
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

class UapValidator {
  const UapValidator();

  AssistantIntent validate(AssistantIntent intent, List<UapTool> tools) {
    if (!intent.isToolCall) return intent;
    final tool = tools.where((item) => item.id == intent.toolId).firstOrNull;
    if (tool == null)
      throw const FormatException(
        'La herramienta solicitada no está en la lista permitida descubierta.',
      );
    final properties = UapValidator.properties(tool);
    if (intent.input.keys.any((key) => !properties.contains(key)))
      throw const FormatException('La entrada contiene un campo desconocido.');
    final required = (tool.inputSchema['required'] as List? ?? const []).map(
      (value) => value.toString(),
    );
    final missing = required
        .where(
          (field) =>
              intent.input[field] == null ||
              intent.input[field].toString().trim().isEmpty,
        )
        .toList();
    if (missing.isNotEmpty)
      return AssistantIntent.answer(
        'Para continuar faltan estos campos obligatorios: ${missing.join(', ')}.',
      );
    final operation = UapValidator.operation(tool);
    if (operation == 'get' || operation == 'update' || operation == 'delete') {
      final id = intent.input['id'];
      if (id == null || id.toString().trim().isEmpty || !_validId(id))
        throw const FormatException(
          'El identificador debe ser un número positivo o un UUID válido.',
        );
    }
    final normalizedInput = <String, dynamic>{...intent.input};
    for (final entry in intent.input.entries) {
      final definition = _definition(tool, entry.key);
      if (entry.value == null) {
        if (!_nullable(definition))
          throw FormatException('El campo ${entry.key} no puede quedar vacío.');
        continue;
      }
      normalizedInput[entry.key] = coerceValue(entry.value, definition);
    }
    return AssistantIntent.tool(tool.id, normalizedInput);
  }

  static Map? _definition(UapTool tool, String field) {
    final properties = tool.inputSchema['properties'];
    final definition = properties is Map ? properties[field] : null;
    if (definition is Map) return definition;
    if (field == 'id') {
      final idSchema = tool.raw['idSchema'];
      if (idSchema is Map) return idSchema;
      return const {'type': 'integer'};
    }
    return null;
  }

  

  static bool _validId(dynamic value) {
    final raw = value.toString().trim();
    return (RegExp(r'^\d+$').hasMatch(raw) && int.tryParse(raw)! > 0) ||
        RegExp(
          r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
        ).hasMatch(raw);
  }

  static List<String> properties(UapTool tool) =>
      ((tool.inputSchema['properties'] as Map?)?.keys ?? const [])
          .map((key) => key.toString())
          .toList()
        ..addAll(_requiresId(tool) ? ['id'] : const []);
  static bool _requiresId(UapTool tool) =>
      {'get', 'update', 'delete'}.contains(operation(tool));
  static String operation(UapTool tool) {
    final value = tool.operation.trim().toLowerCase();
    if (UapCommandParser._operationWords.containsKey(value)) return value;
    return UapCommandParser._operationWords.keys.firstWhere(
      (operation) => tool.id.toLowerCase().endsWith('.$operation'),
      orElse: () => '',
    );
  }

  static String entity(UapTool tool) =>
      tool.raw['entity']?.toString() ?? tool.id.split('.').first;
}

class ConfirmationGate {
  const ConfirmationGate();
  bool requires(UapTool tool) => tool.isWrite || tool.requiresConfirmation;
}

extension<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
