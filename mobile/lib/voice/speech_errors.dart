enum OfflineAsrErrorCode {
  modelMissing,
  nativeLibraryMissing,
  microphoneDenied,
  noSpeech,
  busy,
  captureFailed,
  decodeFailed,
}

class OfflineAsrException implements Exception {
  const OfflineAsrException(this.code, this.message);
  final OfflineAsrErrorCode code;
  final String message;

  @override
  String toString() => message;
}

String offlineAsrErrorMessage(OfflineAsrErrorCode code) => switch (code) {
  OfflineAsrErrorCode.modelMissing =>
    'Falta el modelo local de voz español incluido en la aplicación.',
  OfflineAsrErrorCode.nativeLibraryMissing =>
    'No se pudo cargar la biblioteca local de Sherpa-ONNX para Android.',
  OfflineAsrErrorCode.microphoneDenied =>
    'Se denegó el permiso del micrófono. Habilitalo en los permisos de Android.',
  OfflineAsrErrorCode.noSpeech =>
    'No se reconoció ninguna voz. Hablá más cerca del micrófono e intentá de nuevo.',
  OfflineAsrErrorCode.busy => 'El reconocimiento local ya está escuchando.',
  OfflineAsrErrorCode.captureFailed =>
    'No se pudo capturar el audio del micrófono.',
  OfflineAsrErrorCode.decodeFailed =>
    'El reconocimiento local no pudo decodificar el audio.',
};

// Retained for the existing error-mapping unit test; Android recognizer codes
// are no longer used by the production voice path.
String speechRecognitionErrorMessage(int code) => code == 1 || code == 2 || code == 4
    ? 'El reconocimiento local requiere el paquete de voz español sin conexión incluido en la aplicación.'
    : 'No se pudo reconocer la voz. Revisá el servicio de voz de Android o escribí la solicitud.';
