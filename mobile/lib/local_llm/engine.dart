import 'dart:io';

import 'package:flutter/services.dart';
import 'package:llamadart/llamadart.dart';

enum LocalLlmStatus {
  modelNotInstalled,
  modelSelected,
  ready,
  loading,
  unavailable,
  error,
}

abstract class LocalLlmEngine {
  LocalLlmStatus get status;
  Future<String> chooseModel();
  Future<void> load(String modelPath);
  Future<void> unload();
  Future<String> generate(String prompt, {int maxTokens = 256});
}

class AndroidLlamaCppEngine implements LocalLlmEngine {
  AndroidLlamaCppEngine({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel('uap/model_picker'),
      _engine = LlamaEngine(LlamaBackend());

  final MethodChannel _channel;
  final LlamaEngine _engine;
  LocalLlmStatus _status = LocalLlmStatus.modelNotInstalled;
  String? _loadedPath;
  Future<void> _generationQueue = Future<void>.value();

  @override
  LocalLlmStatus get status => _status;

  @override
  Future<String> chooseModel() async {
    final selected = await _channel.invokeMethod<String>('chooseModel');
    if (selected == null || !ModelPathPolicy.isValidExtension(selected)) {
      throw const FormatException('Elegí un archivo de modelo .gguf local.');
    }
    _status = LocalLlmStatus.modelSelected;
    return selected;
  }

  @override
  Future<void> load(String modelPath) async {
    if (!await ModelPathPolicy.isValidFile(modelPath)) {
      _status = LocalLlmStatus.error;
      throw const FormatException(
        'El modelo .gguf copiado falta, está vacío, es demasiado grande o no es válido.',
      );
    }
    _status = LocalLlmStatus.loading;
    try {
      if (_loadedPath != modelPath) {
        await _engine.unloadModel();
        await _engine.loadModel(
          modelPath,
          modelParams: const ModelParams(contextSize: 2048, gpuLayers: 0),
        );
        _loadedPath = modelPath;
      }
      _status = LocalLlmStatus.ready;
    } catch (error) {
      _status = LocalLlmStatus.error;
      throw StateError('No se pudo cargar el modelo local: $error');
    }
  }

  @override
  Future<void> unload() async {
    await _engine.unloadModel();
    _loadedPath = null;
    _status = LocalLlmStatus.modelNotInstalled;
  }

  @override
  Future<String> generate(String prompt, {int maxTokens = 256}) async {
    final result = _generationQueue.then(
      (_) => _generateExclusive(prompt, maxTokens),
    );
    _generationQueue = result.then<void>((_) {}, onError: (_, __) {});
    return result;
  }

  Future<String> _generateExclusive(String prompt, int maxTokens) async {
    if (_status != LocalLlmStatus.ready) {
      throw StateError('GENERATION_FAILED: el modelo incluido no está listo.');
    }
    try {
      final output = StringBuffer();
      await for (final chunk in _engine.create([
        LlamaChatMessage.fromText(role: LlamaChatRole.user, text: prompt),
      ], params: GenerationParams(maxTokens: maxTokens.clamp(32, 256)))) {
        final text = chunk.choices.first.delta.content;
        if (text != null) output.write(text);
      }
      final value = output.toString().trim();
      if (value.isEmpty) {
        throw StateError(
          'GENERATION_FAILED: el modelo no devolvió una respuesta.',
        );
      }
      return value;
    } catch (error) {
      await _resetAfterGenerationFailure();
      rethrow;
    }
  }

  Future<void> _resetAfterGenerationFailure() async {
    try {
      await _engine.unloadModel();
      _loadedPath = null;
      _status = LocalLlmStatus.modelSelected;
    } catch (_) {
      _loadedPath = null;
      _status = LocalLlmStatus.error;
    }
  }

  Future<void> dispose() => _engine.dispose();
}

class ModelPathPolicy {
  static const maxModelBytes = 8 * 1024 * 1024 * 1024;

  static bool isValidExtension(String path) =>
      path.trim().toLowerCase().endsWith('.gguf');

  static Future<bool> isValidFile(String path) async {
    if (!isValidExtension(path)) return false;
    try {
      final file = File(path);
      final length = await file.length();
      return await file.exists() && length > 0 && length <= maxModelBytes;
    } on FileSystemException {
      return false;
    }
  }
}
