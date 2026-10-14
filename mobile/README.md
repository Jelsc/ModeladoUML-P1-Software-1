# Universal UAP Assistant

This Flutter app is a focused conversational assistant for a generated UAP v1 backend. The home screen has one primary action, **Talk / give an order**, a compact chat, and a text fallback. Raw manifest, schema and tool details are behind Settings.

## Offline architecture

- The assistant engine is local-only. There is no cloud LLM and no cloud speech API or fallback.
- Models use the `GGUF` file format and are executed directly on the phone by `llamadart 0.8.23`. The bundled file is `assets/models/assistant.gguf`, a real 806,058,496-byte `Gemma 3 1B IT Q4_K_M` model from [bartowski's Hugging Face repository](https://huggingface.co/bartowski/google_gemma-3-1b-it-GGUF/blob/main/google_gemma-3-1b-it-Q4_K_M.gguf). SHA-256 is `12BF0FFF8815D5F73A3C9B586BD8FEE8E7B248C935DE70DEC367679873D0F29D`. It uses Google's Gemma Terms of Use (`gemma`), not Apache-2.0. The model is text-only in this app; Gemma 3n multimodal inference is not enabled.
- Android streams the bundled asset to app-private `files/local-models/assistant.gguf` on first start, with an 8 GB limit, atomic temp-file replacement, and persisted path. The APK and first-start storage are about 105 MB larger. Installation is automatic; normal Settings only reports the bundled model and never offers model selection or deletion.
- `LocalLlmEngine` is the testable abstraction; `AndroidLlamaCppEngine` uses the real `llamadart` engine for load, unload, and streamed generation. There is no cloud LLM fallback. The Android channel is only a document picker/copy seam and does not implement inference.
- The runtime uses a 2048-token context, 32-256 output tokens, and zero GPU layers (CPU backend) to keep baseline memory and thermal load reasonable on Snapdragon 720G. The prompt is also hard-capped and contains only a compact bounded contract summary, not raw manifest/schema JSON. Q4 inference is CPU-heavy and can take several seconds per response; keep other apps closed when loading a model.
- `llamadart` requires Dart >=3.10.7 and Flutter >=3.38.0. This project uses Flutter 3.41.8/Dart 3.11.5. The first `flutter build` or `flutter run` may download and bundle native runtime assets, so network access is required for that build step even though inference is offline afterward. Android arm64-v8a is the intended phone target and requires the Android SDK/NDK versions selected by Flutter.
- Offline speech uses the maintained `sherpa_onnx` Flutter package and the bundled Spanish Moonshine v2 model. `record` captures mono PCM16 at 16 kHz for one 8-second utterance; Sherpa-ONNX decodes it on-device with two CPU threads. There is no Android `SpeechRecognizer`, Google speech service, cloud URL, or speech fallback. The only runtime permission is `RECORD_AUDIO`.
- The model is `sherpa-onnx-moonshine-base-es-quantized-2026-02-27` from [the official Sherpa-ONNX ASR release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models). Its bundled `LICENSE` identifies the Spanish model as subject to the Moonshine Community License, a non-commercial license. The three required files occupy 65,108,610 bytes (about 62.1 MiB): `encoder_model.ort` (20,964,320 bytes), `decoder_model_merged.ort` (43,612,200 bytes), and `tokens.txt` (532,090 bytes). SHA-256 values are recorded in `lib/voice/speech_model.dart`. At build time they are packaged in `assets/speech/`; on first use they are copied atomically to app-private storage under `sherpa-onnx-es`. The app does not download them at runtime.
- The official model documentation reports approximately real-time CPU decoding on its reference run. On a Snapdragon 720G, plan for a short warm-up and several seconds per 8-second utterance; this is an expectation, not a device benchmark. The app uses the CPU provider and two threads to avoid requiring Qualcomm NPU support. No physical-device latency or microphone result is claimed until the APK is tested on hardware.
- Alexa mode is microphone-only and sends the resulting Spanish transcript through the existing deterministic UAP parser, confirmation gate and outbox pipeline. History remains text-only. Alexa responses still use the separate local Android `TextToSpeech` path (`es-ES` with a Spanish fallback), which is unchanged and may require Spanish TTS data installed on the phone.

The orchestrator embeds a bounded, deterministic summary of the discovered service, entities, fields and tools in a strict prompt. The formal stages are `IntentInterpreter`, `UapCommandParser`, `UapValidator`, confirmation gate and the single `UapClient.invoke` execution seam. Natural Spanish CRUD requests are parsed deterministically against discovered metadata; unknown fields, invalid values, non-positive IDs and ambiguous entities are refused. The model accepts only a JSON answer or general tool candidate, tolerates harmless Markdown JSON fences, and never supplies executable URLs, SQL, shell or reflection content.

## Assistant modes

- **History** keeps the conversation list and compact text composer, with a microphone shortcut.
- **Alexa** focuses on one large accessible microphone button, listening/loading/error states, the latest response, and a text fallback in the same screen. Settings remain secondary.
- Read results say what was found. Mutations confirm what was performed, or explicitly say no action was performed when cancelled or rejected.

## Commands

```bash
flutter pub get
flutter analyze
flutter test
flutter run
flutter build apk --debug
flutter build apk --release
```

### Offline voice test

1. Run `flutter pub get`, build and install the APK while connected so Gradle can resolve dependencies.
2. Grant the microphone permission when Alexa requests it. The Sherpa model is already inside the APK; no Google voice package is required.
3. Disconnect USB, Wi-Fi and mobile data, open **Alexa**, and speak a Spanish request. A cached UAP contract can be processed locally; pending mutations remain in the local outbox until synchronization is possible.
4. If the model is missing, the native library cannot load, microphone permission is denied, or no speech is detected, the app shows an explicit Spanish local-ASR error and never switches to a cloud recognizer.

Edit `lib/config/api_config.dart` to choose the compiled public endpoint; this is not a secret. The app normalizes trailing slashes and discovers UAP automatically at startup. For the verified physical-phone USB path, run `adb reverse tcp:8080 tcp:80`, keep `activeBackendUrl = usbTestBackendUrl` (`http://127.0.0.1:8080`), and keep `backendHostHeader = 'api-gymnasio-bab1fac.localhost'`. The client sends that Host header to Nginx while connecting to the phone-side loopback address. For normal LAN/emulator/deployed use, set `activeBackendUrl = deployedBackendUrl` or a reachable LAN URL; the client then does not override Host. A valid URL entered in Settings is persisted as `backend_url_override` and wins on every next launch. **Restablecer URL compilada** removes the override and returns to `activeBackendUrl`. Public HTTPS overrides never receive a custom Host header.

To switch the app to another backend without carrying stale local state, open **Configuración y detalles** and choose **Borrar base local SQLite**. After an explicit confirmation, the app closes and recreates only its default `uap_offline.db`; cached records, the UAP snapshot, identity mappings, generations, cursor, and pending/failed/conflict outbox operations are permanently deleted and cannot be synchronized. The configured backend URL is not deleted. The app then discovers the current backend again. Use this action only when intentional data loss is acceptable.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## Durable local data and synchronization

SQLite is the phone's durable store. It uses `local_records`, `sync_outbox`, and `sync_metadata`; the schema is versioned and generic, with no gym/vet domain hardcoded. Redis is not used on the phone. Accepted offline mutations are stored immediately with client-generated record IDs where needed and operation IDs for idempotency; visible states are `Pendiente de sincronización`, `Sincronizado`, `Conflicto` and `Fallido`. The Context Broker selects only relevant exact tool IDs/input fields and bounded local record summaries for the GGUF prompt. Use **Sincronizar ahora** in Settings after connectivity returns. If a backend lacks the sync endpoints, the app reports **Protocolo de sincronización no disponible** and normal online UAP invocation remains available.

Example: 15 local `Member` records remain queryable offline; changes appear as `pending` and are pushed in deterministic order when USB or LAN returns. A duplicate `operationId` is acknowledged idempotently. A stale `baseVersion` remains `conflict`; the backend is authoritative and never silently overwrites it.

Exact USB behavior: run `adb reverse tcp:8080 tcp:80`, configure `http://127.0.0.1:8080`, and keep `backendHostHeader = 'api-<slug>.localhost'`. The phone uses loopback while the Host header selects the generated Nginx route. This is not a cloud fallback and does not expose the phone database.
