import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:mobile_observer/data/team_api.dart';
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

  testWidgets(
    'canvas pan stays in Modelo while tab taps and Lista swipes navigate',
    (tester) async {
      final api = FakeObserverTeamApi();
      await tester.pumpWidget(
        MaterialApp(
          theme: ObserverTheme.data,
          home: ObserverDiagramScreen(
            api: api,
            summary: const DiagramSummary(
              id: 'd',
              title: 'Modelo de prueba',
              isOwner: false,
            ),
            onUnauthorized: () {},
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pump(const Duration(milliseconds: 100));

      final canvas = find.byType(InteractiveViewer);
      expect(canvas, findsOneWidget);
      final viewer = tester.widget<InteractiveViewer>(canvas);
      final initialTransform = Matrix4.copy(
        viewer.transformationController!.value,
      );
      await tester.drag(canvas, const Offset(-180, 0));
      await tester.pump(const Duration(milliseconds: 500));
      expect(viewer.transformationController!.value, isNot(initialTransform));
      expect(find.text('Solo lectura'), findsNothing);

      await tester.tap(
        find.descendant(
          of: find.byType(TabBar),
          matching: find.text('Conversación'),
        ),
      );
      for (var frame = 0; frame < 10; frame++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(tester.widget<TabBar>(find.byType(TabBar)).controller!.index, 1);
      expect(find.text('Solo lectura'), findsOneWidget);

      await tester.tap(
        find.descendant(of: find.byType(TabBar), matching: find.text('Modelo')),
      );
      for (var frame = 0; frame < 10; frame++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(tester.widget<TabBar>(find.byType(TabBar)).controller!.index, 0);
      await tester.tap(find.text('Lista'));
      await tester.pump(const Duration(milliseconds: 500));
      await tester.drag(find.byType(TabBarView), const Offset(-300, 0));
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Solo lectura'), findsOneWidget);

      await tester.pumpWidget(const SizedBox.shrink());
      api.close();
    },
  );
}

class FakeObserverTeamApi extends TeamApi {
  FakeObserverTeamApi()
    : super(
        baseUrl: 'https://example.test/api',
        client: MockClient((_) async => throw StateError('Unexpected request')),
      );

  @override
  String? get token => null;

  @override
  Future<DiagramData> diagram(String diagramId, {bool refresh = false}) async =>
      DiagramData(
        id: diagramId,
        title: 'Modelo de prueba',
        classes: [
          DiagramClass(
            id: 'c1',
            name: 'Cliente',
            x: 80,
            y: 60,
            isAssociation: false,
            attributes: const [],
            methods: const [],
          ),
        ],
        relations: const [],
      );

  @override
  Future<List<DiagramMember>> members(
    String diagramId, {
    bool refresh = false,
  }) async => const [];

  @override
  Future<List<ChatMessage>> chat(
    String diagramId, {
    String channel = 'diseno',
    int limit = 50,
    String? before,
    bool refresh = false,
  }) async => const [];

  @override
  Future<List<ActivityItem>> activity(
    String diagramId, {
    int limit = 50,
    String? before,
    bool refresh = false,
  }) async => const [];

  @override
  Future<DiagramDigest> digest(
    String diagramId, {
    bool refresh = false,
  }) async => const DiagramDigest(
    activity: [],
    activityTotal: 0,
    chatTotal: 0,
    byActor: {},
  );

  @override
  Future<AiSettings> aiSettings(
    String diagramId, {
    bool refresh = false,
  }) async => const AiSettings(enabled: false, canEdit: false);
}
