import 'dart:convert';

import 'package:http/http.dart' as http;

import '../core/url.dart';
import '../config/api_config.dart';
import 'models.dart';

class UapClient {
  UapClient({http.Client? httpClient}) : _http = httpClient ?? http.Client();
  final http.Client _http;
  String baseUrl = normalizeBaseUrl(activeBackendUrl);

  Map<String, String> _headers() {
    final hostHeader = hostHeaderFor(baseUrl);
    return {'host': ?hostHeader};
  }

  Future<UapSnapshot> discover([String? rawUrl]) async {
    baseUrl = normalizeBaseUrl(rawUrl ?? activeBackendUrl);
    final values = <String, Map<String, dynamic>>{};
    for (final resource in [
      'manifest',
      'schema',
      'tools',
      'permissions',
      'business-rules',
    ]) {
      final response = await _http
          .get(Uri.parse('$baseUrl/uap/v1/$resource'), headers: _headers())
          .timeout(const Duration(seconds: 10));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception(
          'Falló el descubrimiento de $resource (HTTP ${response.statusCode}).',
        );
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map) {
        throw Exception('El recurso $resource devolvió JSON no válido.');
      }
      values[resource] = decoded.cast<String, dynamic>();
    }
    return UapSnapshot(
      manifest: values['manifest']!,
      schema: values['schema']!,
      tools: values['tools']!,
      permissions: values['permissions']!,
      businessRules: values['business-rules']!,
    );
  }

  Future<dynamic> invoke(
    UapTool tool,
    Map<String, dynamic> input, {
    required bool confirmed,
  }) async {
    final url = baseUrl;
    final response = await _http
        .post(
          Uri.parse(
            '$url/uap/v1/tools/${Uri.encodeComponent(tool.id)}/invoke?confirmation=$confirmed',
          ),
          headers: {'content-type': 'application/json', ..._headers()},
          body: jsonEncode(input),
        )
        .timeout(const Duration(seconds: 10));
    dynamic body;
    try {
      body = jsonDecode(response.body);
    } catch (_) {
      body = {'raw': response.body};
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        (body is Map ? body['error'] : null)?.toString() ??
            'Falló la invocación de la herramienta (HTTP ${response.statusCode}).',
      );
    }
    return body;
  }

  Future<void> health() async {
    final response = await _http.get(Uri.parse('$baseUrl/uap/v1/manifest'), headers: _headers()).timeout(const Duration(seconds: 5));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Backend no disponible (HTTP ${response.statusCode}).');
    }
  }
}
