import 'package:flutter_test/flutter_test.dart';
import 'package:universal_uap_client/timezone.dart';
import 'package:universal_uap_client/uap/models.dart';

void main() {
  test('formats UTC instants in Bolivia time without a four-hour drift', () {
    expect(boliviaTime(DateTime.parse('2026-01-15T12:00:00Z')), '08:00');
  });
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
