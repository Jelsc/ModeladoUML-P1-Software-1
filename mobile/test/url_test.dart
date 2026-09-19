import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:universal_uap_client/config/api_config.dart';
import 'package:universal_uap_client/core/url.dart';
import 'package:universal_uap_client/uap/client.dart';
import 'package:universal_uap_client/uap/models.dart';

void main() {
  test('normalizes scheme and trailing slash', () {
    expect(normalizeBaseUrl(' example.test/// '), 'http://example.test');
    expect(normalizeBaseUrl('https://example.test/'), 'https://example.test');
  });
  test(
    'rejects empty URL',
    () => expect(() => normalizeBaseUrl(' '), throwsFormatException),
  );
  test('uses the configured backend URL by default', () {
    final client = UapClient();
    expect(client.baseUrl, normalizeBaseUrl(activeBackendUrl));
    expect(hostHeaderFor(activeBackendUrl), backendHostHeader);
    expect(
      normalizeBaseUrl('http://api-gymnasio-bab1fac.localhost///'),
      'http://api-gymnasio-bab1fac.localhost',
    );
  });

  test(
    'sends the deploy Host header for every USB discovery request',
    () async {
      final requests = <http.BaseRequest>[];
      final client = UapClient(
        httpClient: MockClient((request) async {
          requests.add(request);
          return http.Response('{}', 200);
        }),
      );

      await client.discover();

      expect(requests, hasLength(5));
      expect(
        requests.map((request) => request.headers['host']),
        everyElement(backendHostHeader),
      );
      expect(
        requests.map((request) => request.url.host),
        everyElement('127.0.0.1'),
      );
      expect(requests.map((request) => request.url.port), everyElement(8080));
    },
  );

  test('sends the USB Host header for invocation', () async {
    late http.BaseRequest request;
    final client = UapClient(
      httpClient: MockClient((incoming) async {
        request = incoming;
        return http.Response('{}', 200);
      }),
    );
    final tool = UapTool({
      'id': 'list_people',
      'name': 'List people',
      'method': 'GET',
      'path': '/people',
      'permission': 'read',
      'effect': 'read',
      'confirmationRequired': false,
    });

    await client.invoke(tool, const {}, confirmed: true);

    expect(request.headers['host'], backendHostHeader);
    expect(request.headers['content-type'], 'application/json');
  });

  test('does not override Host in normal deployed mode', () async {
    late http.BaseRequest request;
    final client = UapClient(
      httpClient: MockClient((incoming) async {
        request = incoming;
        return http.Response('{}', 200);
      }),
    );

    await client.discover(deployedBackendUrl);

    expect(request.headers.containsKey('host'), isFalse);
  });
}
