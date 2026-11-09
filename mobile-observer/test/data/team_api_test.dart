import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mobile_observer/data/team_api.dart';
import 'package:mobile_observer/models/team_models.dart';

void main() {
  test(
    'normalizes direct and production URLs and rejects unsafe base paths',
    () {
      expect(
        TeamApi.normalizeBaseUrl(' http://example.test:8000/ '),
        'http://example.test:8000',
      );
      expect(
        TeamApi.normalizeBaseUrl('https://example.test/api/'),
        'https://example.test/api',
      );
      expect(
        () => TeamApi.normalizeBaseUrl('file:///tmp/api'),
        throwsFormatException,
      );
      expect(
        () => TeamApi.normalizeBaseUrl('https://example.test/other'),
        throwsFormatException,
      );
      final api = TeamApi(baseUrl: 'https://example.test/api');
      api.useToken('jwt');
      expect(
        api.websocketEndpoint('diagrams/d-1/ws').toString(),
        'wss://example.test/api/diagrams/d-1/ws?token=jwt',
      );
      api.close();
    },
  );

  test(
    'auth and observability endpoints use only login POST plus protected GET routes',
    () async {
      final calls = <http.Request>[];
      final client = MockClient((request) async {
        calls.add(request);
        if (request.url.path.endsWith('/auth/sign-in')) {
          return http.Response(
            jsonEncode({
              'access_token': 'jwt-value',
              'user': {
                'id': 12,
                'email': 'team@example.test',
                'name': 'Ana',
                'role': 'viewer',
                'active': true,
              },
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/auth/me')) {
          return http.Response(
            jsonEncode({
              'id': 12,
              'email': 'team@example.test',
              'name': 'Ana',
              'role': 'viewer',
              'active': true,
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/diagrams')) {
          return http.Response('[]', 200);
        }
        if (request.url.path.endsWith('/chat')) return http.Response('[]', 200);
        if (request.url.path.endsWith('/activity')) {
          return http.Response('[]', 200);
        }
        if (request.url.path.endsWith('/members')) {
          return http.Response('[]', 200);
        }
        if (request.url.path.endsWith('/digest')) {
          return http.Response(
            jsonEncode({
              'since': null,
              'activity': [],
              'activity_total': 0,
              'chat_total': 0,
              'by_actor': {},
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/ai-settings')) {
          return http.Response('{"ai_enabled":true,"ai_can_edit":false}', 200);
        }
        if (request.url.path.endsWith('/d-1')) {
          return http.Response(
            '{"id":"d-1","title":"Modelo","classes":[],"relations":[]}',
            200,
          );
        }
        return http.Response('not found', 404);
      });
      final api = TeamApi(baseUrl: 'https://example.test/api', client: client);

      final signedIn = await api.signIn('ana@example.test', 'not-persisted');
      expect(signedIn.token, 'jwt-value');
      expect((await api.me()).id, 12);
      await api.diagrams();
      await api.diagram('d-1');
      await api.members('d-1');
      await api.chat('d-1', channel: 'test');
      await api.activity('d-1');
      await api.digest('d-1');
      await api.aiSettings('d-1');

      expect(calls.map((request) => request.method), [
        'POST',
        ...List.filled(8, 'GET'),
      ]);
      expect(calls.first.url.path, '/api/auth/sign-in');
      expect(calls.first.headers['authorization'], isNull);
      expect(calls.first.body, contains('ana@example.test'));
      for (final request in calls.skip(1)) {
        expect(request.headers['authorization'], 'Bearer jwt-value');
      }
      expect(
        calls
            .singleWhere((request) => request.url.path.endsWith('/chat'))
            .url
            .queryParameters['channel'],
        'test',
      );
    },
  );

  test(
    'URL-encodes chat cursor plus signs and returns typed unauthorized failures',
    () async {
      http.Request? request;
      final api = TeamApi(
        baseUrl: 'http://localhost:8000',
        client: MockClient((value) async {
          request = value;
          return http.Response('{"detail":"token vencido"}', 401);
        }),
      );
      api.useToken('secret-token');

      await expectLater(
        api.chat('d-1', before: '2026-11-08T10:00:00+00:00'),
        throwsA(
          isA<ApiFailure>().having((e) => e.unauthorized, 'unauthorized', true),
        ),
      );
      expect(request!.url.toString(), contains('%2B00%3A00'));
      expect(request!.method, 'GET');
    },
  );

  test(
    'device token registration and removal are authenticated write requests',
    () async {
      final requests = <http.Request>[];
      final api = TeamApi(
        baseUrl: 'http://localhost:8000',
        client: MockClient((request) async {
          requests.add(request);
          return http.Response('', 204);
        }),
      );
      api.useToken('session-token');
      final registration = const DeviceTokenRegistration(
        token: 'fcm-token',
        platform: 'android',
      );

      await api.registerDeviceToken(registration);
      await api.unregisterDeviceToken(registration);
      expect(requests.map((request) => request.method), ['POST', 'DELETE']);
      expect(requests.every((request) => request.url.path == '/devices/fcm-token'), isTrue);
      expect(requests.every((request) => request.headers['authorization'] == 'Bearer session-token'), isTrue);
      expect(requests.every((request) => request.body.contains('"platform":"android"')), isTrue);
      expect(requests.every((request) => request.body.contains('fcm-token')), isTrue);
    },
  );

  test(
    'only GET responses are cached and refresh bypasses the memory cache',
    () async {
      var requests = 0;
      final api = TeamApi(
        baseUrl: 'http://localhost:8000',
        client: MockClient((request) async {
          requests++;
          expect(request.method, 'GET');
          return http.Response('[]', 200);
        }),
      );
      api.useToken('read-token');

      await api.diagrams();
      await api.diagrams();
      expect(requests, 1);
      await api.diagrams(refresh: true);
      expect(requests, 2);
      api.close();
    },
  );
}
