import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/models/team_models.dart';
import 'package:mobile_observer/ui/diagram_screen.dart';

void main() {
  testWidgets(
    'observability tabs show data without edit or chat-send controls',
    (tester) async {
      final diagram = DiagramData.fromJson({
        'id': 'd-1',
        'title': 'Sistema de viajes',
        'classes': [
          {
            'id': 'c-1',
            'name': 'Viaje',
            'x': 0,
            'y': 0,
            'is_association': false,
            'attributes': [
              {'id': 'a-1', 'name': 'destino', 'type': 'string'},
            ],
            'methods': [],
          },
        ],
        'relations': [
          {
            'id': 'r-1',
            'source_id': 'c-1',
            'target_id': 'c-2',
            'from': 'Viaje',
            'to': 'Pasajero',
            'type': 'association',
            'label': null,
            'source_multiplicity': null,
            'target_multiplicity': '0..*',
          },
        ],
      });
      await tester.pumpWidget(
        MaterialApp(
          home: ReadOnlyDiagramWorkspace(
            diagram: diagram,
            messages: const [],
            channel: 'diseno',
            onChannelChanged: (_) {},
            activity: const [],
            digest: null,
            members: const [],
            aiSettings: null,
          ),
        ),
      );

      expect(find.text('Viaje'), findsNWidgets(2));
      expect(find.text('destino: string'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.byType(FloatingActionButton), findsNothing);
      expect(find.text('Editar'), findsNothing);
      expect(find.text('Enviar'), findsNothing);

      for (final tab in ['Conversación', 'Bitácora', 'Resumen']) {
        await tester.tap(find.text(tab));
        await tester.pumpAndSettle();
        expect(
          find.byType(TextField),
          findsNothing,
          reason: '$tab has no composer',
        );
        expect(
          find.byType(FloatingActionButton),
          findsNothing,
          reason: '$tab has no write action',
        );
        expect(find.text('Editar'), findsNothing, reason: '$tab has no editor');
        expect(
          find.text('Enviar'),
          findsNothing,
          reason: '$tab has no chat send',
        );
      }
    },
  );
}
