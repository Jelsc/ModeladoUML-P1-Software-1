import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../data/push_notifications.dart';
import '../data/session_store.dart';
import '../data/team_api.dart';
import '../models/team_models.dart';
import '../ui/diagram_list_screen.dart';
import '../ui/diagram_screen.dart';
import '../ui/login_screen.dart';
import '../ui/observer_theme.dart';

const defaultObserverServerUrl = 'http://10.0.2.2:8000';

class ObserverApp extends StatefulWidget {
  const ObserverApp({
    super.key,
    ObserverSessionStore? sessionStore,
    PushNotifications? pushNotifications,
  }) : _sessionStore = sessionStore,
       _pushNotifications = pushNotifications;

  final ObserverSessionStore? _sessionStore;
  final PushNotifications? _pushNotifications;

  @override
  State<ObserverApp> createState() => _ObserverAppState();
}

class _ObserverAppState extends State<ObserverApp> {
  final _navigatorKey = GlobalKey<NavigatorState>();
  final _messengerKey = GlobalKey<ScaffoldMessengerState>();
  late final ObserverSessionStore _sessionStore =
      widget._sessionStore ?? SecureObserverSessionStore();
  late final PushNotifications _push =
      widget._pushNotifications ?? PushNotifications();
  late final StreamSubscription<PushNotice> _tapSubscription;
  late final StreamSubscription<PushNotice> _foregroundSubscription;
  late final StreamSubscription<String> _tokenRefreshSubscription;
  late TeamApi _api;
  TeamUser? _user;
  String _serverUrl = defaultObserverServerUrl;
  String? _loginMessage;
  String? _pendingDiagramId;
  String? _pendingDiagramTitle;
  PushAvailability _pushAvailability = PushAvailability.unavailable;
  DeviceTokenRegistration? _registeredDevice;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _api = TeamApi(baseUrl: _serverUrl);
    _tapSubscription = _push.taps.listen(_handlePushTap);
    _foregroundSubscription = _push.foregroundMessages.listen(
      _handleForegroundMessage,
    );
    _tokenRefreshSubscription = _push.tokenRefreshes.listen(_registerDeviceToken);
    unawaited(_initialize());
  }

  Future<void> _initialize() async {
    final savedUrl = await _sessionStore.readServerUrl();
    if (savedUrl != null) {
      try {
        _serverUrl = TeamApi.normalizeBaseUrl(savedUrl);
        _api.changeBaseUrl(_serverUrl);
      } on FormatException {
        _serverUrl = defaultObserverServerUrl;
      }
    }
    await _push.initialize();
    _pushAvailability = _push.availability;
    final savedToken = await _sessionStore.readToken();
    if (savedToken != null && savedToken.isNotEmpty) {
      _api.useToken(savedToken);
      try {
        _user = await _api.me();
        await _registerCurrentDevice();
      } on ApiFailure catch (error) {
        if (error.unauthorized) {
          await _sessionStore.clearToken();
          _api.useToken(null);
          _loginMessage = 'La sesión venció. Inicie sesión nuevamente.';
        } else {
          _loginMessage = error.message;
        }
      } catch (_) {
        _loginMessage =
            'No se pudo validar la sesión. Revise la conexión e inicie sesión.';
      }
    }
    if (mounted) setState(() => _ready = true);
    _openPendingPush();
  }

  Future<void> _signIn(String serverUrl, String email, String password) async {
    final normalized = TeamApi.normalizeBaseUrl(serverUrl);
    _api.changeBaseUrl(normalized);
    await _sessionStore.writeServerUrl(normalized);
    final result = await _api.signIn(email, password);
    await _sessionStore.writeToken(result.token);
    if (!mounted) return;
    setState(() {
      _serverUrl = normalized;
      _user = result.user;
      _loginMessage = null;
    });
    await _registerCurrentDevice();
    _openPendingPush();
  }

  Future<void> _signOut({bool expired = false}) async {
    final registration = _registeredDevice;
    if (registration != null) {
      try {
        await _api.unregisterDeviceToken(registration);
      } catch (_) {}
      _registeredDevice = null;
    }
    _api.useToken(null);
    _api.clearReadCache();
    await _sessionStore.clearToken();
    if (!mounted) return;
    setState(() {
      _user = null;
      _loginMessage = expired
          ? 'La sesión venció. Inicie sesión nuevamente.'
          : null;
    });
    _navigatorKey.currentState?.popUntil((route) => route.isFirst);
  }

  Future<void> _registerCurrentDevice() async {
    final token = await _push.getToken();
    if (token == null || token.isEmpty || _user == null) return;
    await _registerDeviceToken(token);
  }

  Future<void> _registerDeviceToken(String token) async {
    if (_user == null) return;
    final registration = DeviceTokenRegistration(
      token: token,
      platform: defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android',
    );
    try {
      await _api.registerDeviceToken(registration);
      _registeredDevice = registration;
    } catch (_) {
      // Push registration must not block read-only use of the observer.
    }
  }

  void _handlePushTap(PushNotice notice) {
    if (notice.diagramId == null || notice.diagramId!.isEmpty) return;
    _pendingDiagramId = notice.diagramId;
    _pendingDiagramTitle = notice.title;
    _openPendingPush();
  }

  void _openPendingPush() {
    final diagramId = _pendingDiagramId;
    if (diagramId == null || _user == null || !_ready) return;
    _pendingDiagramId = null;
    final summary = DiagramSummary(
      id: diagramId,
      title: _pendingDiagramTitle ?? 'Actualización del equipo',
      isOwner: false,
      memberRole: null,
    );
    _navigatorKey.currentState?.push(
      MaterialPageRoute<void>(
        builder: (_) => ObserverDiagramScreen(
          api: _api,
          summary: summary,
          onUnauthorized: () => _signOut(expired: true),
        ),
      ),
    );
  }

  void _handleForegroundMessage(PushNotice notice) {
    if (!mounted) return;
    final messenger = _messengerKey.currentState;
    if (messenger == null) return;
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          notice.title ?? notice.body ?? 'Nueva actividad del equipo',
        ),
        action: notice.diagramId == null
            ? null
            : SnackBarAction(
                label: 'Ver',
                onPressed: () => _handlePushTap(notice),
              ),
      ),
    );
  }

  @override
  void dispose() {
    unawaited(_tapSubscription.cancel());
    unawaited(_foregroundSubscription.cancel());
    unawaited(_tokenRefreshSubscription.cancel());
    unawaited(_push.dispose());
    _api.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Observador de equipo',
    navigatorKey: _navigatorKey,
    scaffoldMessengerKey: _messengerKey,
    theme: ObserverTheme.data,
    debugShowCheckedModeBanner: false,
    home: !_ready
        ? const _StartupScreen()
        : _user == null
        ? LoginScreen(
            initialServerUrl: _serverUrl,
            message: _loginMessage,
            onSignIn: _signIn,
          )
        : DiagramListScreen(
            api: _api,
            user: _user!,
            pushAvailability: _pushAvailability,
            onSignOut: _signOut,
            onUnauthorized: () => _signOut(expired: true),
          ),
  );
}

class _StartupScreen extends StatelessWidget {
  const _StartupScreen();
  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: CircularProgressIndicator()));
}
