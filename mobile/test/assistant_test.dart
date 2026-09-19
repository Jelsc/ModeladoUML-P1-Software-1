import 'package:flutter_test/flutter_test.dart';
import 'package:universal_uap_client/assistant/orchestrator.dart';
import 'package:universal_uap_client/local_llm/model_asset.dart';
import 'package:universal_uap_client/local_llm/model_manager.dart';
import 'package:universal_uap_client/uap/models.dart';

void main() {
  final read = UapTool({'id': 'user.list', 'sideEffects': false});
  final write = UapTool({
    'id': 'user.delete',
    'sideEffects': true,
    'requiresConfirmation': true,
  });
  final create = UapTool({
    'id': 'user.create',
    'entity': 'user',
    'operation': 'create',
    'sideEffects': true,
    'inputSchema': {
      'properties': {
        'name': {'type': 'string'},
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
      IntentValidator.parse('{"tool":"user.list","input":{}}', [read]).toolId,
      'user.list',
    );
    expect(
      () => IntentValidator.parse('{"tool":"shell","input":{}}', [read]),
      throwsFormatException,
    );
    expect(
      () => IntentValidator.parse(
        '{"tool":"user.list","input":{"unknown":true}}',
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
      request: 'crea user name Ana',
      schema: {
        'entities': [
          {
            'name': 'user',
            'fields': {'name': {}},
          },
        ],
      },
    );
    expect(intent.isToolCall, isTrue);
    expect(intent.toolId, 'user.create');
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
    expect(ModelAsset.license, 'Apache-2.0');
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
      contains('Realicé'),
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
        'data': [1, 2],
      }),
      contains('Encontré resultados'),
    );
  });
}
