import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import 'speech_errors.dart';
import 'speech_model.dart';

enum OfflineAsrState { idle, listening, stopping, error }

abstract interface class OfflineAsrEngine {
  Future<bool> get isAvailable;
  OfflineAsrState get state;
  Future<String?> listenOnce();
  Future<void> stop();
  Future<void> dispose();
}

class SherpaOfflineAsrEngine implements OfflineAsrEngine {
  SherpaOfflineAsrEngine({AudioRecorder? recorder})
    : _recorder = recorder ?? AudioRecorder();

  static const _maxDuration = Duration(seconds: 8);
  final AudioRecorder _recorder;
  sherpa.OfflineRecognizer? _recognizer;
  StreamSubscription<Uint8List>? _audioSubscription;
  Timer? _stopTimer;
  Completer<String?>? _result;
  final _pcm = BytesBuilder(copy: false);
  OfflineAsrState _state = OfflineAsrState.idle;

  @override
  OfflineAsrState get state => _state;

  @override
  Future<bool> get isAvailable async {
    if (!Platform.isAndroid) return false;
    try {
      sherpa.initBindings();
      for (final file in SpeechModelAsset.expectedFiles.keys) {
        await rootBundle.load('${SpeechModelAsset.directory}/$file');
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> listenOnce() async {
    if (_state == OfflineAsrState.listening ||
        _state == OfflineAsrState.stopping) {
      throw OfflineAsrException(
        OfflineAsrErrorCode.busy,
        offlineAsrErrorMessage(OfflineAsrErrorCode.busy),
      );
    }
    if (!Platform.isAndroid) {
      throw OfflineAsrException(
        OfflineAsrErrorCode.nativeLibraryMissing,
        offlineAsrErrorMessage(OfflineAsrErrorCode.nativeLibraryMissing),
      );
    }
    if (!await _recorder.hasPermission()) {
      throw OfflineAsrException(
        OfflineAsrErrorCode.microphoneDenied,
        offlineAsrErrorMessage(OfflineAsrErrorCode.microphoneDenied),
      );
    }

    _state = OfflineAsrState.listening;
    _result = Completer<String?>();
    _pcm.clear();
    try {
      await _prepareRecognizer();
      final audio = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: SpeechModelAsset.sampleRate,
          numChannels: 1,
        ),
      );
      _audioSubscription = audio.listen(
        _pcm.add,
        onError: (Object _, StackTrace __) => _fail(
          OfflineAsrException(
            OfflineAsrErrorCode.captureFailed,
            offlineAsrErrorMessage(OfflineAsrErrorCode.captureFailed),
          ),
        ),
      );
      _stopTimer = Timer(_maxDuration, _finishRecognition);
      return await _result!.future;
    } on OfflineAsrException {
      _stopTimer?.cancel();
      _state = OfflineAsrState.error;
      rethrow;
    } catch (error) {
      final exception = OfflineAsrException(
        _isModelError(error)
            ? OfflineAsrErrorCode.modelMissing
            : OfflineAsrErrorCode.nativeLibraryMissing,
        _isModelError(error)
            ? offlineAsrErrorMessage(OfflineAsrErrorCode.modelMissing)
            : offlineAsrErrorMessage(OfflineAsrErrorCode.nativeLibraryMissing),
      );
      _state = OfflineAsrState.error;
      if (!(_result?.isCompleted ?? true)) _result!.completeError(exception);
      throw exception;
    }
  }

  @override
  Future<void> stop() async {
    if (_result == null || _result!.isCompleted) return;
    _state = OfflineAsrState.stopping;
    _stopTimer?.cancel();
    await _stopCapture();
    _result?.complete(null);
    _state = OfflineAsrState.idle;
  }

  Future<void> _finishRecognition() async {
    if (_result == null || _result!.isCompleted) return;
    _state = OfflineAsrState.stopping;
    await _stopCapture();
    try {
      final bytes = _pcm.takeBytes();
      if (bytes.length < 3200) {
        throw OfflineAsrException(
          OfflineAsrErrorCode.noSpeech,
          offlineAsrErrorMessage(OfflineAsrErrorCode.noSpeech),
        );
      }
      final stream = _recognizer!.createStream();
      late final String text;
      try {
        stream.acceptWaveform(
          samples: _pcmToFloat(bytes),
          sampleRate: SpeechModelAsset.sampleRate,
        );
        _recognizer!.decode(stream);
        text = _recognizer!.getResult(stream).text.trim();
      } finally {
        stream.free();
      }
      if (text.isEmpty) {
        throw OfflineAsrException(
          OfflineAsrErrorCode.noSpeech,
          offlineAsrErrorMessage(OfflineAsrErrorCode.noSpeech),
        );
      }
      _result?.complete(text);
      _state = OfflineAsrState.idle;
    } catch (error) {
      _fail(
        error is OfflineAsrException
            ? error
            : OfflineAsrException(
                OfflineAsrErrorCode.decodeFailed,
                offlineAsrErrorMessage(OfflineAsrErrorCode.decodeFailed),
              ),
      );
    }
  }

  Future<void> _prepareRecognizer() async {
    try {
      sherpa.initBindings();
      final directory = await _installModel();
      _recognizer?.free();
      _recognizer = sherpa.OfflineRecognizer(
        sherpa.OfflineRecognizerConfig(
          model: sherpa.OfflineModelConfig(
            moonshine: sherpa.OfflineMoonshineModelConfig(
              encoder: p.join(directory.path, 'encoder_model.ort'),
              mergedDecoder: p.join(directory.path, 'decoder_model_merged.ort'),
            ),
            tokens: p.join(directory.path, 'tokens.txt'),
            modelType: 'moonshine',
            numThreads: 2,
            debug: false,
          ),
        ),
      );
    } catch (error) {
      if (error is OfflineAsrException) rethrow;
      throw OfflineAsrException(
        _isModelError(error)
            ? OfflineAsrErrorCode.modelMissing
            : OfflineAsrErrorCode.nativeLibraryMissing,
        _isModelError(error)
            ? offlineAsrErrorMessage(OfflineAsrErrorCode.modelMissing)
            : offlineAsrErrorMessage(OfflineAsrErrorCode.nativeLibraryMissing),
      );
    }
  }

  Future<Directory> _installModel() async {
    final root = await getApplicationSupportDirectory();
    final directory = Directory(p.join(root.path, 'sherpa-onnx-es'));
    await directory.create(recursive: true);
    for (final entry in SpeechModelAsset.expectedFiles.entries) {
      final data = await rootBundle.load(
        '${SpeechModelAsset.directory}/${entry.key}',
      );
      if (data.lengthInBytes != entry.value) {
        throw OfflineAsrException(
          OfflineAsrErrorCode.modelMissing,
          offlineAsrErrorMessage(OfflineAsrErrorCode.modelMissing),
        );
      }
      final target = File(p.join(directory.path, entry.key));
      if (await target.exists() && await target.length() == entry.value)
        continue;
      final temporary = File('${target.path}.tmp');
      final output = temporary.openWrite();
      final bytes = data.buffer.asUint8List(
        data.offsetInBytes,
        data.lengthInBytes,
      );
      for (var offset = 0; offset < bytes.length; offset += 1024 * 1024) {
        final end = (offset + 1024 * 1024).clamp(0, bytes.length);
        output.add(bytes.sublist(offset, end));
      }
      await output.close();
      await temporary.rename(target.path);
    }
    return directory;
  }

  Future<void> _stopCapture() async {
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    await _recorder.stop();
  }

  void _fail(OfflineAsrException error) {
    _state = OfflineAsrState.error;
    if (!(_result?.isCompleted ?? true)) _result!.completeError(error);
  }

  static Float32List _pcmToFloat(Uint8List bytes) {
    final samples = Float32List(bytes.length ~/ 2);
    final data = ByteData.sublistView(bytes);
    for (var index = 0; index < samples.length; index++) {
      samples[index] = data.getInt16(index * 2, Endian.little) / 32768.0;
    }
    return samples;
  }

  static bool _isModelError(Object error) =>
      error is OfflineAsrException &&
      error.code == OfflineAsrErrorCode.modelMissing;

  @override
  Future<void> dispose() async {
    _stopTimer?.cancel();
    try {
      await _stopCapture();
    } finally {
      if (!(_result?.isCompleted ?? true)) _result!.complete(null);
      _state = OfflineAsrState.idle;
      await _recorder.dispose();
      _recognizer?.free();
      _recognizer = null;
    }
  }
}
