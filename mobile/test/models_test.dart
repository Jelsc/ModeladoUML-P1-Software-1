import 'package:flutter_test/flutter_test.dart';
import 'package:universal_uap_client/uap/models.dart';

void main() {
  test('groups tools by side effects and confirmation metadata', () {
    final snapshot = UapSnapshot(
      manifest: {},
      schema: {},
      tools: {
        'tools': [
          {'id': 'a.list', 'operation': 'list', 'sideEffects': false},
          {
            'id': 'a.delete',
            'operation': 'delete',
            'sideEffects': true,
            'requiresConfirmation': true,
          },
        ],
      },
      permissions: {},
      businessRules: {},
    );
    expect(snapshot.toolList.where((tool) => !tool.isWrite).length, 1);
    expect(snapshot.toolList.last.requiresConfirmation, isTrue);
  });
}
