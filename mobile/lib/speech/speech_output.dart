import 'package:flutter/services.dart';

abstract class SpeechOutput {
  Future<void> speak(String text);
  Future<void> stop();
  Future<void> dispose();
}

class AndroidSpeechOutput implements SpeechOutput {
  AndroidSpeechOutput({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel('uap/text_to_speech');
  final MethodChannel _channel;

  @override
  Future<void> speak(String text) async {
    if (text.trim().isEmpty) return;
    try {
      await _channel.invokeMethod<void>('speak', {'text': text});
    } on PlatformException {
      // Speech is an enhancement; visible assistant text remains available.
    } on MissingPluginException {
      // Non-Android targets keep the text-only fallback.
    }
  }

  @override
  Future<void> stop() async {
    try {
      await _channel.invokeMethod<void>('stop');
    } on PlatformException {
      // The visible response remains the fallback when native TTS is unavailable.
    } on MissingPluginException {
      // Non-Android targets keep the text-only fallback.
    }
  }

  @override
  Future<void> dispose() async {
    try {
      await _channel.invokeMethod<void>('dispose');
    } on PlatformException {
      // There is no native resource to release when TTS is unavailable.
    } on MissingPluginException {
      // Non-Android targets keep the text-only fallback.
    }
  }
}
