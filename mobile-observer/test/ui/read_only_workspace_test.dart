import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/models/team_models.dart';
import 'package:mobile_observer/ui/diagram_screen.dart';

void main() {
  testWidgets(
    'observability tabs show chat composer but no direct diagram edit controls',
    (tester) async {
      String? sentMessage;
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
            onSendMessage: (content) async => sentMessage = content,
            activity: const [],
            digest: null,
            members: const [],
            aiSettings: null,
          ),
        ),
      );
      await tester.tap(find.text('Lista').first);
      await tester.pumpAndSettle();

      expect(find.text('Viaje'), findsNWidgets(2));
      expect(find.text('destino: string'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.byType(FloatingActionButton), findsNothing);
      expect(find.text('Editar'), findsNothing);
      expect(find.byKey(const Key('chat-send-button')), findsNothing);
      expect(find.byTooltip('Analizar foto con IA'), findsNothing);

      for (final tab in ['Conversación', 'Bitácora', 'Resumen']) {
        await tester.tap(find.text(tab));
        await tester.pumpAndSettle();
        expect(
          find.byType(TextField),
          tab == 'Conversación' ? findsOneWidget : findsNothing,
          reason: '$tab composer availability',
        );
        expect(
          find.byType(FloatingActionButton),
          findsNothing,
          reason: '$tab has no write action',
        );
        expect(find.text('Editar'), findsNothing, reason: '$tab has no editor');
        expect(
          find.byKey(const Key('chat-send-button')),
          tab == 'Conversación' ? findsOneWidget : findsNothing,
          reason: '$tab send availability',
        );
        expect(find.byTooltip('Analizar foto con IA'), findsNothing);
        if (tab == 'Conversación') {
          expect(find.textContaining('@ia'), findsOneWidget);
          expect(find.text('Mensaje para todo el equipo'), findsOneWidget);
        }
      }
      await tester.tap(find.text('Conversación'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('chat-message-input')),
        '@ia revisá el modelo',
      );
      await tester.tap(find.byKey(const Key('chat-send-button')));
      await tester.pumpAndSettle();
      expect(sentMessage, '@ia revisá el modelo');
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('chat-message-input')))
            .controller!
            .text,
        isEmpty,
      );
    },
  );
}
