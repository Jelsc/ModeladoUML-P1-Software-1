import 'package:flutter/services.dart';

class OfflineVoice {
  const OfflineVoice({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel('uap/offline_voice');
  final MethodChannel _channel;

  Future<bool> get isAvailable async =>
      await _channel.invokeMethod<bool>('isAvailable') ?? false;

  Future<String?> listenOnce() async {
    try {
      return await _channel.invokeMethod<String>('listenOnce');
    } on PlatformException catch (error) {
      throw StateError(
        error.message ??
            'El reconocimiento de voz no está disponible en este dispositivo.',
      );
    }
  }
}
