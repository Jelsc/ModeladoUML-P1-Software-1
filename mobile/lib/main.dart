import 'package:flutter/material.dart';

import 'features/home_page.dart';

void main() => runApp(const UapApp());

class UapApp extends StatelessWidget {
  const UapApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Protocolo de Asistente Universal',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff165dff)),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xfff6f7fb),
      ),
      home: const HomePage(),
    );
  }
}
