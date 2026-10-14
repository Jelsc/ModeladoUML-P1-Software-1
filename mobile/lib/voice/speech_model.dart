class SpeechModelAsset {
  const SpeechModelAsset._();

  static const directory = 'assets/speech';
  static const sourceUrl =
      'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-moonshine-base-es-quantized-2026-02-27.tar.bz2';
  static const license = 'Moonshine Community License (non-commercial)';
  static const modelName =
      'sherpa-onnx-moonshine-base-es-quantized-2026-02-27';
  static const sampleRate = 16000;
  static const expectedFiles = <String, int>{
    'encoder_model.ort': 20964320,
    'decoder_model_merged.ort': 43612200,
    'tokens.txt': 532090,
  };
  static const sha256 = <String, String>{
    'encoder_model.ort':
        '331AAFA2FC7F7E55BA28376EEF08EAF919AE105BB719CD64BA6875505DCA72B3',
    'decoder_model_merged.ort':
        '8E6513AD66A3A71CA86824746A09051EEB60468940EAF8201CE758E8919E2B5D',
    'tokens.txt':
        'C6E35883BA038F70CEEA8B4A21CF79742ADBDA7E6730CBFF27460857E0667A02',
  };

  static bool validateSizes(Map<String, int> files) => expectedFiles.entries.every(
    (entry) => files[entry.key] == entry.value,
  );
}
