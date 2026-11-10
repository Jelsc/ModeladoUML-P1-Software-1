import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/ui/login_screen.dart';

void main() {
  testWidgets('login asks for credentials without a server URL', (tester) async {
    String? submittedEmail;
    String? submittedPassword;

    await tester.pumpWidget(
      MaterialApp(
        home: LoginScreen(
          onSignIn: (email, password) async {
            submittedEmail = email;
            submittedPassword = password;
          },
        ),
      ),
    );

    expect(find.text('Servidor'), findsNothing);
    await tester.enterText(find.byType(TextFormField).at(0), 'person@example.com');
    await tester.enterText(find.byType(TextFormField).at(1), 'secret');
    await tester.tap(find.text('Ingresar'));
    await tester.pump();

    expect(submittedEmail, 'person@example.com');
    expect(submittedPassword, 'secret');
  });
}
