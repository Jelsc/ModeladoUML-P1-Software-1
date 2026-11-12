import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/models/team_models.dart';
import 'package:mobile_observer/ui/diagram_screen.dart';

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
  test('decodes optional chat image metadata', () {
    final message = ChatMessage.fromJson({
      'id': 'm-photo',
      'diagram_id': 'd-1',
      'author_kind': 'user',
      'content': 'Analizar esta foto',
      'channel': 'diseno',
      'image': {'id': 'image-1', 'name': 'uml.png'},
    });
    expect(message.image?.id, 'image-1');
    expect(message.image?.name, 'uml.png');
    expect(ChatMessage.fromJson({'id': 'm-plain'}).image, isNull);
  });
  test('preserves association-class metadata in a vision proposal', () {
    final proposal = VisionProposal.fromJson({
      'project_name': 'Gym',
      'classes': [
        {
          'id': 'c-1',
          'name': 'OrderItem',
          'selected': true,
          'attributes': [],
          'methods': [],
        },
      ],
      'relations': [
        {
          'id': 'r-1',
          'source_id': 'c-1',
          'target_id': 'c-2',
          'source': 'Order',
          'target': 'Product',
          'type': 'association',
          'association_class': 'OrderItem',
          'association_class_id': 'c-1',
          'selected': true,
        },
      ],
      'warnings': [],
    });

    final relation = proposal.toJson()['relations'] as List;
    expect(relation.single['association_class'], 'OrderItem');
    expect(relation.single['association_class_id'], 'c-1');
    final restored = VisionProposal.fromJson(proposal.toJson());
    expect(restored.relations.single.associationClass, 'OrderItem');
    expect(restored.relations.single.associationClassId, 'c-1');
  });
  test('detects image MIME from content signature, not filename extension', () {
    final png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    expect(detectImageMime(Uint8List.fromList(png)), 'image/png');
    // A .jpg filename does not override PNG bytes; MIME is derived from bytes.
    expect(detectImageMime(Uint8List.fromList(png)), isNot('image/jpeg'));
  });
  test('rejects unsupported HEVC ftyp brands', () {
    expect(
      detectImageMime(
        Uint8List.fromList([
          0,
          0,
          0,
          0,
          0x66,
          0x74,
          0x79,
          0x70,
          0x68,
          0x65,
          0x76,
          0x63,
        ]),
      ),
      isNull,
    );
  });
  test('parses persisted notification contract and timestamp', () {
    final item = InboxNotification.fromJson({
      'id': 'n-1',
      'event': 'class.updated',
      'diagram_id': 'd-1',
      'diagram_title': 'Modelo',
      'title': 'Actualización del equipo',
      'body': 'Hay nueva actividad en un diagrama.',
      'created_at': '2026-11-08T10:00:00+00:00',
    });
    expect(item.diagramId, 'd-1');
    expect(item.createdAt, DateTime.parse('2026-11-08T10:00:00+00:00'));
  });
}
