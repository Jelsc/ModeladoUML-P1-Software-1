import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/models/team_models.dart';
import 'package:mobile_observer/ui/diagram_screen.dart';
import 'package:mobile_observer/ui/observer_theme.dart';

void main() {
  DiagramClass item(String id, String name, int x, int y) => DiagramClass(
    id: id,
    name: name,
    x: x,
    y: y,
    isAssociation: false,
    attributes: const [DiagramAttribute(id: 'a', name: 'codigo', type: 'int')],
    methods: const [DiagramMethod(id: 'm', name: 'buscar', type: 'bool')],
  );

  testWidgets(
    'diagram mode exposes pan canvas and text list without edit controls',
    (tester) async {
      final diagram = DiagramData(
        id: 'd',
        title: 'Modelo',
        classes: [item('a', 'Cliente', 40, 60), item('b', 'Pedido', 340, 180)],
        relations: const [
          DiagramRelation(
            id: 'r',
            sourceId: 'a',
            targetId: 'b',
            from: 'Cliente',
            to: 'Pedido',
            type: 'association',
            targetMultiplicity: '0..*',
          ),
        ],
      );
      await tester.pumpWidget(
        MaterialApp(
          theme: ObserverTheme.data,
          home: Scaffold(body: DiagramModelTab(diagram: diagram)),
        ),
      );
      expect(find.text('Diagrama'), findsOneWidget);
    expect(find.byTooltip('Restablecer vista'), findsOneWidget);
      expect(find.byType(InteractiveViewer), findsOneWidget);
      expect(find.byType(IconButton), findsOneWidget);
      expect(find.text('Editar'), findsNothing);
      await tester.tap(find.text('Lista'));
      await tester.pumpAndSettle();
      expect(find.text('Clases'), findsOneWidget);
      expect(find.text('Relaciones'), findsOneWidget);
    },
  );

  testWidgets('empty diagrams show empty state in both modes', (tester) async {
    const diagram = DiagramData(
      id: 'd',
      title: 'Vacío',
      classes: [],
      relations: [],
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: ObserverTheme.data,
        home: Scaffold(body: DiagramModelTab(diagram: diagram)),
      ),
    );
    expect(find.text('Este diagrama todavía no tiene clases.'), findsOneWidget);
    await tester.tap(find.text('Lista'));
    await tester.pumpAndSettle();
    expect(find.text('Este diagrama todavía no tiene clases.'), findsOneWidget);
  });
}
