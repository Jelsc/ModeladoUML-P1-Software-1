import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/models/team_models.dart';

void main() {
  test('parses diagram, relation endpoint extras and nullable fields', () {
    final diagram = DiagramData.fromJson({
      'id': 'd-1',
      'title': 'Sistema',
      'server_added_field': {'ignored': true},
      'classes': [
        {
          'id': 'c-1',
          'name': 'Cliente',
          'x': 30,
          'y': 40,
          'is_association': false,
          'attributes': [
            {'id': 'a-1', 'name': 'correo', 'type': 'string', 'extra': 3},
          ],
          'methods': [
            {'id': 'm-1', 'name': 'validar', 'type': 'bool'},
          ],
        },
      ],
      'relations': [
        {
          'id': 'r-1',
          'source_id': 'c-1',
          'target_id': 'c-2',
          'from': 'Cliente',
          'to': 'Pedido',
          'type': 'association',
          'label': null,
          'source_multiplicity': null,
          'target_multiplicity': '0..*',
          'association_class_id': null,
          'source_endpoint_info': {'type': 'attribute'},
        },
      ],
    });

    expect(diagram.classes.single.attributes.single.name, 'correo');
    expect(diagram.relations.single.label, isNull);
    expect(diagram.relations.single.sourceMultiplicity, isNull);
    expect(diagram.relations.single.targetMultiplicity, '0..*');
  });

  test(
    'parses nullable AI authors, digest fields and unknown extras safely',
    () {
      final message = ChatMessage.fromJson({
        'id': 'm-1',
        'diagram_id': 'd-1',
        'author_user_id': null,
        'author_name': null,
        'author_kind': 'ai',
        'content': 'Estado actualizado',
        'reply_to_id': null,
        'channel': 'test',
        'created_at': '2026-11-08T10:00:00+00:00',
        'future': true,
      });
      final digest = DiagramDigest.fromJson({
        'since': null,
        'activity': [],
        'activity_total': 0,
        'chat_total': 2,
        'by_actor': {'IA': 2},
        'future': 'ignored',
      });
      final settings = AiSettings.fromJson({
        'ai_enabled': true,
        'ai_can_edit': false,
        'extra': 1,
      });

      expect(message.authorUserId, isNull);
      expect(message.authorName, isNull);
      expect(message.channel, 'test');
      expect(digest.since, isNull);
      expect(digest.byActor, {'IA': 2});
      expect(settings.enabled, isTrue);
      expect(settings.canEdit, isFalse);
    },
  );
}
