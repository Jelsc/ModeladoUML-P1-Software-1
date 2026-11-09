import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/data/push_notifications.dart';

class FakeMessagingClient implements ObserverMessagingClient {
  final opened = StreamController<RemoteMessage>.broadcast();
  final foreground = StreamController<RemoteMessage>.broadcast();
  final refreshed = StreamController<String>.broadcast();

  @override
  Future<AuthorizationStatus> requestPermission() async =>
      AuthorizationStatus.authorized;
  @override
  Future<RemoteMessage?> getInitialMessage() async => null;
  @override
  Stream<RemoteMessage> get openedMessages => opened.stream;
  @override
  Stream<RemoteMessage> get foregroundMessages => foreground.stream;
  @override
  Stream<String> get refreshedTokens => refreshed.stream;
  @override
  Future<String?> getToken() async => 'test-only-placeholder';
}

void main() {
  test('exposes FCM token refreshes and diagram IDs from notification taps', () async {
    final messaging = FakeMessagingClient();
    final push = PushNotifications(messagingClient: messaging);
    final refresh = expectLater(push.tokenRefreshes, emits('rotated-placeholder'));
    final tap = expectLater(
      push.taps,
      emits(
        isA<PushNotice>().having((notice) => notice.diagramId, 'diagramId', 'diagram-42'),
      ),
    );

    await push.initialize();
    expect(await push.getToken(), 'test-only-placeholder');
    messaging.refreshed.add('rotated-placeholder');
    messaging.opened.add(RemoteMessage(data: {'diagram_id': 'diagram-42'}));
    await Future.wait([refresh, tap]);
    await push.dispose();
    await messaging.opened.close();
    await messaging.foreground.close();
    await messaging.refreshed.close();
  });
}
