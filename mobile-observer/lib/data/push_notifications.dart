import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

@pragma('vm:entry-point')
Future<void> observerPushBackgroundHandler(RemoteMessage _) async {}

class PushNotice {
  const PushNotice({this.title, this.body, this.diagramId});
  final String? title;
  final String? body;
  final String? diagramId;

  factory PushNotice.fromMessage(RemoteMessage message) => PushNotice(
    title: message.notification?.title,
    body: message.notification?.body,
    diagramId: message.data['diagram_id'] is String
        ? message.data['diagram_id'] as String
        : null,
  );
}

enum PushAvailability { unavailable, permissionDenied, ready, failed }

abstract interface class ObserverMessagingClient {
  Future<AuthorizationStatus> requestPermission();
  Future<RemoteMessage?> getInitialMessage();
  Stream<RemoteMessage> get openedMessages;
  Stream<RemoteMessage> get foregroundMessages;
  Stream<String> get refreshedTokens;
  Future<String?> getToken();
}

class PushNotifications {
  PushNotifications({ObserverMessagingClient? messagingClient})
    : _injectedMessagingClient = messagingClient,
      _messagingClient = messagingClient;

  final ObserverMessagingClient? _injectedMessagingClient;
  ObserverMessagingClient? _messagingClient;
  final _taps = StreamController<PushNotice>.broadcast();
  final _foreground = StreamController<PushNotice>.broadcast();
  StreamSubscription<RemoteMessage>? _tapSubscription;
  StreamSubscription<RemoteMessage>? _foregroundSubscription;
  StreamSubscription<String>? _tokenSubscription;
  final _tokenRefreshes = StreamController<String>.broadcast();
  PushAvailability availability = PushAvailability.unavailable;

  Stream<PushNotice> get taps => _taps.stream;
  Stream<PushNotice> get foregroundMessages => _foreground.stream;
  Stream<String> get tokenRefreshes => _tokenRefreshes.stream;

  Future<void> initialize() async {
    try {
      if (defaultTargetPlatform == TargetPlatform.iOS) return;
      if (_injectedMessagingClient == null) {
        await Firebase.initializeApp();
        FirebaseMessaging.onBackgroundMessage(observerPushBackgroundHandler);
        _messagingClient = _FirebaseMessagingClient(FirebaseMessaging.instance);
      }
      final client = _messagingClient ?? _injectedMessagingClient!;
      _messagingClient = client;
      final permission = await client.requestPermission();
      final initial = await client.getInitialMessage();
      if (initial != null) _taps.add(PushNotice.fromMessage(initial));
      _tapSubscription = client.openedMessages.listen(
        (message) => _taps.add(PushNotice.fromMessage(message)),
      );
      _foregroundSubscription = client.foregroundMessages.listen(
        (message) => _foreground.add(PushNotice.fromMessage(message)),
      );
      // FCM Admin delivery targets registration tokens; keep this API until
      // the server supports Firebase Installation IDs.
      // ignore: deprecated_member_use
      _tokenSubscription = client.refreshedTokens.listen(
        _tokenRefreshes.add,
      );
      availability = permission == AuthorizationStatus.denied
          ? PushAvailability.permissionDenied
          : PushAvailability.ready;
    } catch (_) {
      availability = PushAvailability.unavailable;
    }
  }

  Future<String?> getToken() async {
    if (availability != PushAvailability.ready) return null;
    try {
      // ignore: deprecated_member_use
      return await _messagingClient?.getToken();
    } catch (_) {
      return null;
    }
  }

  Future<void> dispose() async {
    await _tapSubscription?.cancel();
    await _foregroundSubscription?.cancel();
    await _tokenSubscription?.cancel();
    await _taps.close();
    await _foreground.close();
    await _tokenRefreshes.close();
  }
}

class _FirebaseMessagingClient implements ObserverMessagingClient {
  _FirebaseMessagingClient(this.messaging);
  final FirebaseMessaging messaging;

  @override
  Future<AuthorizationStatus> requestPermission() async =>
      (await messaging.requestPermission(alert: true, badge: true, sound: true))
          .authorizationStatus;
  @override
  Future<RemoteMessage?> getInitialMessage() => messaging.getInitialMessage();
  @override
  Stream<RemoteMessage> get openedMessages => FirebaseMessaging.onMessageOpenedApp;
  @override
  Stream<RemoteMessage> get foregroundMessages => FirebaseMessaging.onMessage;
  @override
  // ignore: deprecated_member_use
  Stream<String> get refreshedTokens => messaging.onTokenRefresh;
  @override
  // ignore: deprecated_member_use
  Future<String?> getToken() => messaging.getToken();
}

String pushAvailabilityLabel(PushAvailability availability) =>
    switch (availability) {
      PushAvailability.unavailable => 'Notificaciones push no configuradas',
      PushAvailability.permissionDenied => 'Permiso de notificaciones denegado',
      PushAvailability.ready =>
        'Notificaciones push disponibles',
      PushAvailability.failed =>
        'Notificaciones push no disponibles en este dispositivo',
    };
