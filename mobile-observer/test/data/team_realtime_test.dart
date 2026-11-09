import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_observer/data/team_realtime.dart';

class _FakeConnection implements ReceiveOnlyConnection {
  final controller = StreamController<String>();
  int? _closeCode;
  @override
  Stream<String> get messages => controller.stream;
  @override
  int? get closeCode => _closeCode;
  @override
  Future<void> close() async {
    if (!controller.isClosed) await controller.close();
  }

  Future<void> finish([int? code]) async {
    _closeCode = code;
    await close();
  }
}

void main() {
  test('retry policy follows capped backoff', () {
    expect(
      List.generate(6, (index) => TeamRealtime.retryDelay(index).inSeconds),
      [1, 2, 5, 10, 30, 30],
    );
  });

  test(
    'receives events, refreshes after reconnect, and signs out on close 1008',
    () async {
      final firstReady = Completer<void>();
      final secondReady = Completer<void>();
      final eventReceived = Completer<RealtimeEvent>();
      final first = _FakeConnection();
      final second = _FakeConnection();
      var connections = 0;
      var refreshes = 0;
      var unauthorized = false;
      final client = TeamRealtime(
        uri: Uri.parse('ws://example.test/diagrams/d/ws?token=hidden'),
        connector: (_) async {
          connections++;
          if (connections == 1) {
            firstReady.complete();
            return first;
          }
          secondReady.complete();
          return second;
        },
        delay: (_) async {},
        onEvent: (event) {
          if (!eventReceived.isCompleted) eventReceived.complete(event);
        },
        onStatus: (_) {},
        onRefreshAfterReconnect: () async {
          refreshes++;
        },
        onUnauthorized: () {
          unauthorized = true;
        },
      );

      final running = client.start();
      await firstReady.future;
      first.controller.add(
        jsonEncode({
          'event': 'chat.message',
          'message': {'id': 'm-1'},
        }),
      );
      expect((await eventReceived.future).name, 'chat.message');
      await first.finish();
      await secondReady.future;
      await Future<void>.delayed(Duration.zero);
      expect(refreshes, 1);
      await second.finish(1008);
      await running;
      expect(unauthorized, isTrue);
      expect(connections, 2);
    },
  );
}
