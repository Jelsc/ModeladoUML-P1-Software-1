import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/services.dart';

import 'engine.dart';
import 'model_asset.dart';

class ModelManager {
  static const modelPathKey = 'local_gguf_model_path';

  ModelManager({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel('uap/model_picker');

  final MethodChannel _channel;

  Future<String?> getPath() async {
    final prefs = await SharedPreferences.getInstance();
    final path = prefs.getString(modelPathKey);
    if (path == null || await ModelPathPolicy.isValidFile(path)) return path;
    await prefs.remove(modelPathKey);
    return null;
  }

  Future<void> savePath(String path) async {
    final value = path.trim();
    if (!await ModelPathPolicy.isValidFile(value)) {
      throw const FormatException(
        'Se requiere un archivo de modelo .gguf local.',
      );
    }
    await (await SharedPreferences.getInstance()).setString(
      modelPathKey,
      value,
    );
  }

  Future<String> ensureBundledModel() async {
    final current = await getPath();
    if (current != null) return current;
    final path = await _channel.invokeMethod<String>('copyBundledModel');
    if (path == null || !await ModelPathPolicy.isValidFile(path)) {
      throw StateError(
        'BUNDLED_MODEL_MISSING: falta ${ModelAsset.fileName} o no es válido en la aplicación. Reinstalá el paquete.',
      );
    }
    await savePath(path);
    return path;
  }

  Future<void> clear() async =>
      (await SharedPreferences.getInstance()).remove(modelPathKey);
}
