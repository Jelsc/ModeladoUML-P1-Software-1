import 'package:flutter_test/flutter_test.dart';
import 'package:universal_uap_client/voice/speech_errors.dart';
import 'package:universal_uap_client/voice/speech_model.dart';

void main() {
  test(
    'maps Android network speech errors to the offline Spanish guidance',
    () {
      final message = speechRecognitionErrorMessage(2);

      expect(message, contains('paquete de voz español sin conexión'));
      expect(message, isNot(contains('LLM')));
      expect(message, isNot(contains('Speech recognition failed')));
    },
  );

  test('keeps non-network speech errors actionable and Spanish', () {
    expect(
      speechRecognitionErrorMessage(7),
      'No se pudo reconocer la voz. Revisá el servicio de voz de Android o escribí la solicitud.',
    );
  });

  test('validates the bundled Spanish Sherpa model file manifest', () {
    expect(
      SpeechModelAsset.validateSizes(SpeechModelAsset.expectedFiles),
      isTrue,
    );
    expect(
      SpeechModelAsset.validateSizes({
        ...SpeechModelAsset.expectedFiles,
        'tokens.txt': 12,
      }),
      isFalse,
    );
  });

  test('exposes explicit local ASR error states', () {
    expect(
      offlineAsrErrorMessage(OfflineAsrErrorCode.microphoneDenied),
      contains('micrófono'),
    );
    expect(
      offlineAsrErrorMessage(OfflineAsrErrorCode.modelMissing),
      contains('modelo local'),
    );
  });
}
