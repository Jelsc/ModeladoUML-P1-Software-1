import 'dart:async';
import 'dart:convert';
import 'dart:io';

enum RealtimeStatus { disconnected, connecting, connected, reconnecting }

class RealtimeEvent {
  const RealtimeEvent({required this.name, required this.data});
  final String name;
  final Map<String, dynamic> data;

  factory RealtimeEvent.fromJson(Map<String, dynamic> json) => RealtimeEvent(
    name: json['event'] is String ? json['event'] as String : '',
    data: json,
  );
}

abstract interface class ReceiveOnlyConnection {
  Stream<String> get messages;
  int? get closeCode;
  Future<void> close();
}

typedef ReceiveOnlyConnector = Future<ReceiveOnlyConnection> Function(Uri uri);
typedef DelayFunction = Future<void> Function(Duration duration);

class _IoReceiveOnlyConnection implements ReceiveOnlyConnection {
  _IoReceiveOnlyConnection(this._socket);
  final WebSocket _socket;

  @override
  Stream<String> get messages => _socket.map((message) => message.toString());

  @override
  int? get closeCode => _socket.closeCode;

  @override
  Future<void> close() async {
    await _socket.close();
  }
}

class TeamRealtime {
  TeamRealtime({
    required this.uri,
    required this.onEvent,
    required this.onStatus,
    required this.onRefreshAfterReconnect,
    required this.onUnauthorized,
    ReceiveOnlyConnector? connector,
    DelayFunction? delay,
  }) : _connector = connector ?? _connectIo,
       _delay = delay ?? Future<void>.delayed;

  final Uri uri;
  final void Function(RealtimeEvent event) onEvent;
  final void Function(RealtimeStatus status) onStatus;
  final Future<void> Function() onRefreshAfterReconnect;
  final void Function() onUnauthorized;
  final ReceiveOnlyConnector _connector;
  final DelayFunction _delay;
  ReceiveOnlyConnection? _connection;
  bool _active = false;
  bool _connectedBefore = false;

  static const retrySeconds = [1, 2, 5, 10, 30];

  static Duration retryDelay(int attempt) => Duration(
    seconds: retrySeconds[attempt.clamp(0, retrySeconds.length - 1)],
  );

  Future<void> start() async {
    if (_active) return;
    _active = true;
    var attempt = 0;
    while (_active) {
      onStatus(
        _connectedBefore
            ? RealtimeStatus.reconnecting
            : RealtimeStatus.connecting,
      );
      try {
        final connection = await _connector(uri);
        if (!_active) {
          await connection.close();
          break;
        }
        _connection = connection;
        onStatus(RealtimeStatus.connected);
        if (_connectedBefore) await onRefreshAfterReconnect();
        _connectedBefore = true;
        await for (final raw in connection.messages) {
          if (!_active) break;
          try {
            final decoded = jsonDecode(raw);
            if (decoded is Map) {
              onEvent(
                RealtimeEvent.fromJson(Map<String, dynamic>.from(decoded)),
              );
            }
          } on FormatException {
            // Ignore malformed or non-JSON server frames.
          }
        }
        final closeCode = connection.closeCode;
        await connection.close();
        _connection = null;
        if (closeCode == 1008) {
          _active = false;
          onUnauthorized();
          return;
        }
      } on WebSocketException {
        _connection = null;
      } on SocketException {
        _connection = null;
      } catch (_) {
        _connection = null;
      }
      if (_active) {
        onStatus(RealtimeStatus.reconnecting);
        await _delay(retryDelay(attempt));
        attempt++;
      }
    }
    onStatus(RealtimeStatus.disconnected);
  }

  Future<void> stop() async {
    _active = false;
    final current = _connection;
    _connection = null;
    await current?.close();
  }

  static Future<ReceiveOnlyConnection> _connectIo(Uri uri) async =>
      _IoReceiveOnlyConnection(await WebSocket.connect(uri.toString()));
}
