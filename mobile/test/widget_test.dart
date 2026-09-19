// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';

import 'package:universal_uap_client/main.dart';

void main() {
  testWidgets('assistant screen keeps one primary talk action', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const UapApp());
    expect(find.text('Asistente UAP'), findsOneWidget);
    expect(find.byTooltip('Hablar con el asistente'), findsNothing);
    expect(find.text('Modelo incluido ausente'), findsOneWidget);
    expect(find.text('Historial'), findsOneWidget);
    expect(find.text('Alexa'), findsOneWidget);
  });
}
