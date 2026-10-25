---
paths:
  - "mobile/**"
---

# Mobile (Flutter) rules

- Package `universal_uap_client`, Dart SDK `^3.11.5`. Commands from `mobile/`: `flutter pub get`, `flutter analyze`, `flutter test`, `flutter run`, `flutter build apk --debug|--release`.
- Layout in `lib/`: `assistant/` (orchestrator, pipeline, context_broker), `uap/` (`client.dart`, models), `offline/` (sqflite database, repository, `sync_engine.dart`), `local_llm/` (llamadart engine + model asset/manager), `voice/` and `speech/` (sherpa_onnx ASR, TTS), `config/api_config.dart`, `features/home_page.dart`.
- `UapClient.invoke` is the only tool-execution seam. Never add another path that calls the backend for mutations, and never accept URLs, SQL or shell from model output. Write tools need in-app confirmation.
- Local-only intelligence: no cloud LLM, no cloud speech. Do not add cloud fallbacks.
- Offline-first: SQLite cache + durable outbox with `operationId`, conflict on stale `baseVersion`, backoff 1/2/5/10/30 s (max 5 attempts). Do not claim server success for queued operations.
- `lib/config/api_config.dart` contains public endpoints only (no secrets). Change `activeBackendUrl` only when asked. Emulator uses `10.0.2.2`; USB uses `adb reverse`.
- Assets: `assets/speech/` (Moonshine ASR, tracked) and `assets/models/assistant.gguf` (git-ignored, ~806 MB, absent in a fresh checkout; pubspec lists it so builds fail without it). Never read or regenerate these binaries.
- "Borrar base local SQLite" in the app is destructive by design; do not trigger or script it.
- Tests: `test/{assistant,models,offline,speech,url,widget}_test.dart` (`sqflite_common_ffi` for DB tests). Never run successfully so far: on the Windows host `flutter test` stops until Developer Mode (symlinks) is enabled. `flutter` commands there rewrite `analysis_options.yaml` and `pubspec.lock`; revert those if unintended.
