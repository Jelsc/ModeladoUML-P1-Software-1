import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:universal_uap_client/assistant/orchestrator.dart';
import 'package:universal_uap_client/local_llm/model_asset.dart';
import 'package:universal_uap_client/local_llm/model_manager.dart';
import 'package:universal_uap_client/uap/models.dart';

void main() {
  final read = UapTool({
    'id': 'users.list',
    'entity': 'users',
    'sideEffects': false,
  });
  final write = UapTool({
    'id': 'users.delete',
    'sideEffects': true,
    'requiresConfirmation': true,
  });
  final create = UapTool({
    'id': 'users.create',
    'entity': 'users',
    'operation': 'create',
    'sideEffects': true,
    'inputSchema': {
      'properties': {
        'name': {'type': 'string'},
      },
    },
  });
  final typedCreate = UapTool({
    'id': 'products.create',
    'entity': 'products',
    'operation': 'create',
    'sideEffects': true,
    'inputSchema': {
      'properties': {
        'price': {'type': 'number'},
        'stock': {'type': 'integer'},
        'active': {'type': 'boolean'},
      },
    },
  });

  test('accepts answer and allowlisted tool only', () {
    expect(IntentValidator.parse('{"answer":"ok"}', [read]).text, 'ok');
    expect(
      IntentValidator.parse('```json\n{"answer":"ok"}\n```', [read]).text,
      'ok',
    );
    expect(
      IntentValidator.parse('{"tool":"users.list","input":{}}', [read]).toolId,
      'users.list',
    );
    expect(
      () => IntentValidator.parse('{"tool":"shell","input":{}}', [read]),
      throwsFormatException,
    );
    expect(
      () => IntentValidator.parse(
        '{"tool":"users.list","input":{"unknown":true}}',
        [read],
      ),
      throwsFormatException,
    );
    expect(
      () => IntentValidator.parse('not json', [read]),
      throwsFormatException,
    );
    expect(write.isWrite, isTrue);
  });

  test('falls back from malformed output for an unambiguous request', () {
    final intent = IntentValidator.parse(
      'No puedo devolver JSON.',
      [create],
      request: 'crea usuario name Ana',
      schema: {
        'entities': [
          {
            'name': 'users',
            'fields': {'name': {}},
          },
        ],
      },
    );
    expect(intent.isToolCall, isTrue);
    expect(intent.toolId, 'users.create');
    expect(intent.input, {'name': 'Ana'});
  });

  test('refuses malformed output when the request is ambiguous', () {
    final intent = IntentValidator.parse('respuesta libre', [
      read,
      UapTool({'id': 'order.list', 'operation': 'list'}),
    ], request: 'lista');
    expect(intent.isToolCall, isFalse);
    expect(intent.text, contains('No pude determinar'));
  });

  test('rejects invalid model paths', () async {
    expect(() => ModelManager().savePath('model.bin'), throwsFormatException);
    expect(() => ModelManager().savePath(' '), throwsFormatException);
  });

  test('defines the bundled model asset and filename', () {
    expect(ModelAsset.assetPath, 'assets/models/assistant.gguf');
    expect(ModelAsset.fileName, 'assistant.gguf');
    expect(ModelAsset.displayName, contains('Gemma 3 1B'));
    expect(ModelAsset.license, contains('Gemma Terms of Use'));
    expect(ModelAsset.byteSize, 806058496);
  });

  test('prompt includes discovered contract and strict output shape', () {
    final snapshot = UapSnapshot(
      manifest: {'name': 'x'},
      schema: {},
      tools: {'tools': []},
      permissions: {},
      businessRules: {},
    );
    final prompt = PromptBuilder.build(snapshot, 'list users');
    expect(prompt, contains('exactly one JSON object'));
    expect(prompt, contains('list users'));
  });

  test('accepts Gemma-like JSON and validates the discovered contract', () {
    final intent = IntentValidator.parse(
      '{"tool":"users.create","input":{"name":"Ana"}}',
      [create],
    );
    expect(intent.toolId, 'users.create');
    expect(intent.input['name'], 'Ana');
  });

  test('rejects missing ids and invalid values before execution', () {
    final get = UapTool({
      'id': 'user.get',
      'operation': 'get',
      'inputSchema': {'type': 'object'},
    });
    expect(
      () => IntentValidator.parse('{"tool":"user.get","input":{}}', [get]),
      throwsFormatException,
    );
    expect(
      () =>
          IntentValidator.parse('{"tool":"user.get","input":{"id":0}}', [get]),
      throwsFormatException,
    );
  });

  test('coerces locale-aware numbers and Spanish booleans from model JSON', () {
    AssistantIntent parseInput(Map<String, dynamic> input) =>
        IntentValidator.parse(
          '{"tool":"products.create","input":${jsonEncode(input)}}',
          [typedCreate],
        );

    expect(parseInput({'price': '2500', 'stock': '10'}).input, {
      'price': 2500,
      'stock': 10,
    });
    expect(
      parseInput({'price': '25,000', 'stock': '10'}).input['price'],
      25000,
    );
    expect(
      parseInput({'price': '25.000', 'stock': '10'}).input['price'],
      25000,
    );
    expect(parseInput({'price': '2500.50', 'active': 'verdadero'}).input, {
      'price': 2500.5,
      'active': true,
    });
    expect(
      parseInput({'price': '2500', 'active': 'falso'}).input['active'],
      false,
    );
    expect(() => parseInput({'price': '25,00,0'}), throwsFormatException);
    expect(() => parseInput({'price': 'mucho'}), throwsFormatException);
    expect(() => parseInput({'active': 'quizás'}), throwsFormatException);
  });

  test('preserves numeric-looking values for string schemas', () {
    final legacy = UapTool({
      'id': 'products.update',
      'entity': 'products',
      'operation': 'update',
      'sideEffects': true,
      'inputSchema': {
        'properties': {
          'price': {'type': 'string'},
          'stock': {'type': 'string'},
        },
      },
    });
    final intent = IntentValidator.parse(
      '{"tool":"products.update","input":{"id":"2","price":"25.000","stock":"10"}}',
      [legacy],
    );
    expect(intent.input, {'id': 2, 'price': '25000', 'stock': '10'});
  });

  test('parses the exact Spanish update through string and numeric schemas', () {
    final request =
        'Actualizá el producto con id 2 y establecé el precio en 25000 y el stock en 10.';
    UapTool tool(String priceType) => UapTool({
      'id': 'products.update',
      'entity': 'products',
      'operation': 'update',
      'sideEffects': true,
      'inputSchema': {
        'properties': {
          'id': {'type': 'integer'},
          'price': {'type': priceType},
          'stock': {'type': 'integer'},
        },
      },
    });
    final schema = {
      'entities': [
        {'name': 'products'},
      ],
    };
    final stringIntent = IntentValidator.parse(
      'respuesta inválida',
      [tool('string')],
      request: request,
      schema: schema,
    );
    final numberIntent = IntentValidator.parse(
      'respuesta inválida',
      [tool('number')],
      request: request,
      schema: schema,
    );
    expect(stringIntent.input, {
      'id': 2,
      'price': '25000',
      'stock': 10,
    });
    expect(numberIntent.input, {
      'id': 2,
      'price': 25000,
      'stock': 10,
    });
  });

  test('coerces Spanish booleans and rejects invalid typed values', () {
    final active = UapTool({
      'id': 'products.create',
      'entity': 'products',
      'operation': 'create',
      'inputSchema': {
        'properties': {'active': {'type': 'boolean'}},
      },
    });
    expect(
      IntentValidator.parse(
        '{"tool":"products.create","input":{"active":"falso"}}',
        [active],
      ).input['active'],
      false,
    );
    expect(
      () => IntentValidator.parse(
        '{"tool":"products.create","input":{"active":"quizás"}}',
        [active],
      ),
      throwsFormatException,
    );
  });

  test('extracts product aliases and typed values from Spanish fallback', () {
    final intent = IntentValidator.parse(
      'respuesta inválida',
      [
        UapTool({
          'id': 'products.create',
          'entity': 'products',
          'operation': 'create',
          'sideEffects': true,
          'inputSchema': {
            'properties': {
              'name': {'type': 'string'},
              'price': {'type': 'number'},
              'stock': {'type': 'integer'},
            },
          },
        }),
      ],
      request: 'registra un producto con nombre teclado precio 2500 y stock 10',
      schema: {
        'entities': [
          {'name': 'products'},
        ],
      },
    );
    expect(intent.input, {'name': 'teclado', 'price': 2500, 'stock': 10});
  });

  test('confirmation gate protects every mutation', () {
    expect(const ConfirmationGate().requires(create), isTrue);
    expect(const ConfirmationGate().requires(read), isFalse);
  });

  test('prompt stays bounded while preserving tool ids and fields', () {
    final snapshot = UapSnapshot(
      manifest: {'name': 'large service', 'description': 'x' * 10000},
      schema: {
        'entities': List.generate(
          100,
          (index) => {
            'name': 'Entity$index',
            'fields': {
              'important_field': {'type': 'string'},
              'noise': 'x' * 500,
            },
          },
        ),
      },
      tools: {
        'tools': [
          {
            'id': 'entity.create',
            'name': 'Create entity',
            'operation': 'create',
            'sideEffects': true,
            'inputSchema': {
              'properties': {
                'important_field': {'type': 'string'},
              },
            },
          },
        ],
      },
      permissions: {},
      businessRules: {},
    );
    final prompt = PromptBuilder.build(snapshot, 'x' * 10000);
    expect(prompt.length, lessThanOrEqualTo(PromptBuilder.maxPromptCharacters));
    expect(prompt, contains('entity.create'));
    expect(prompt, contains('important_field'));
    expect(prompt, isNot(contains('http://')));
  });

  test('formats tool outcomes without claiming failed mutations', () {
    expect(
      AssistantResultFormatter.mutation(write, {'message': 'saved'}),
      contains('Eliminé'),
    );
    expect(
      AssistantResultFormatter.cancelled(write),
      contains('No se realizó'),
    );
    expect(
      AssistantResultFormatter.failure(write, Exception('denied')),
      contains('No pude realizar'),
    );
    expect(
      AssistantResultFormatter.read(read, {
        'data': [
          {'id': 1, 'name': 'Ana', 'active': true},
        ],
      }),
      contains('Encontré 1 usuarios'),
    );
    expect(
      AssistantResultFormatter.read(read, {'ok': true, 'data': []}),
      'No hay usuarios para mostrar.',
    );
  });

  test('resolves singular Spanish entities and ignores model policy claims', () {
    final intent = IntentValidator.parse(
      '{"answer":"No hay herramienta para registrar usuarios"}',
      [
        UapTool({
          'id': 'users.create',
          'entity': 'users',
          'operation': 'create',
          'sideEffects': true,
          'inputSchema': {
            'properties': {
              'name': {'type': 'string'},
              'email': {'type': 'string'},
              'active': {'type': 'boolean'},
              'apellido': {'type': 'string'},
            },
          },
        }),
      ],
      request:
          'registra un usuario nombre Ana apellido Perez correo ana@example.com activo true',
      schema: {
        'entities': [
          {'name': 'users'},
        ],
      },
    );
    expect(intent.toolId, 'users.create');
    expect(intent.input, {
      'name': 'Ana',
      'apellido': 'Perez',
      'email': 'ana@example.com',
      'active': true,
    });
  });

  test('formats actual mutation data and flags missing backend values', () {
    expect(
      AssistantResultFormatter.mutation(
        typedCreate,
        {
          'data': {'id': 7, 'name': 'teclado', 'price': null, 'stock': 10},
        },
        input: {'name': 'teclado', 'price': 2500, 'stock': 10},
      ),
      allOf(
        contains('No confirmé'),
        contains('precio: sin dato'),
        contains('backend devolvió'),
        isNot(contains('{')),
      ),
    );
  });

  test('does not claim update success when backend values differ', () {
    final text = AssistantResultFormatter.mutation(
      typedCreate,
      {
        'data': {'id': 2, 'price': null, 'stock': 10},
      },
      input: {'id': 2, 'price': 25000, 'stock': 10},
    );
    expect(text, contains('No confirmé'));
    expect(text, contains('precio: sin dato'));
    expect(text, isNot(contains('Actualicé')));
  });

  test('does not claim success when backend returns null data', () {
    final text = AssistantResultFormatter.mutation(
      typedCreate,
      {'ok': true, 'data': null},
      input: {'price': 25000, 'stock': 10},
    );
    expect(text, contains('No confirmé'));
    expect(text, isNot(contains('Actualicé')));
  });
}
