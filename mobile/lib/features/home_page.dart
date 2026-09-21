import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:connectivity_plus/connectivity_plus.dart';

import '../assistant/orchestrator.dart';
import '../config/api_config.dart';
import '../core/url.dart';
import '../local_llm/engine.dart';
import '../local_llm/model_manager.dart';
import '../local_llm/model_asset.dart';
import '../uap/client.dart';
import '../uap/models.dart';
import '../voice/offline_voice.dart';
import '../offline/database.dart';
import '../offline/repository.dart';
import '../offline/sync_engine.dart';
import '../offline/models.dart';
import '../speech/speech_output.dart';
import '../timezone.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _Message {
  const _Message(this.author, this.text);
  final String author;
  final String text;
}

enum _AssistantMode { history, alexa }

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  final _url = TextEditingController();
  final _request = TextEditingController();
  final _client = UapClient();
  final _models = ModelManager();
  final _engine = AndroidLlamaCppEngine();
  final _voice = const OfflineVoice();
  final SpeechOutput _speech = AndroidSpeechOutput();
  UapSnapshot? _snapshot;
  String? _modelPath;
  String? _modelInstallError;
  String? _error;
  bool _busy = false;
  bool _loadingModel = false;
  bool _listening = false;
  _AssistantMode _mode = _AssistantMode.history;
  final _messages = <_Message>[];
  String? _lastSpokenText;
  OfflineRepository? _repository;
  SyncEngine? _syncEngine;
  String _syncLabel = 'Solo local';
  String _backendStatus = 'offline';
  StreamSubscription<List<ConnectivityResult>>? _connectivitySubscription;
  Timer? _retryTimer;
  Timer? _pendingTimer;
  int _retryAttempt = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _connectivitySubscription = Connectivity().onConnectivityChanged.listen((_) => _scheduleReconnect());
    _restore();
  }

  Future<void> _restore() async {
    try {
      final database = await openOfflineDatabase();
      _repository = OfflineRepository(database);
      _snapshot = await _repository!.cachedSnapshot();
      _backendStatus = await _repository!.backendStatus();
      _syncEngine = SyncEngine(
        _repository!,
        HttpSyncTransport(
          _client.baseUrl,
          headers: {
            if (hostHeaderFor(_client.baseUrl) != null)
              'host': hostHeaderFor(_client.baseUrl)!,
          },
        ),
      );
      final cachedSync = await _repository!.lastSyncAt();
      if (_snapshot != null) _syncLabel = cachedSync == null ? 'Usando datos locales' : 'Usando datos locales · ${_formatTime(cachedSync)}';
      if ((await _repository!.pendingOperations()).isNotEmpty) _startPendingTimer();
    } catch (_) {
      _repository = null;
    }
    String? modelPath;
    String? modelInstallError;
    try {
      modelPath = await _models.ensureBundledModel();
    } catch (_) {
      modelInstallError =
          'No se pudo instalar el modelo incluido. Reconstruí la aplicación con ${ModelAsset.assetPath}.';
    }
    if (!mounted) return;
    setState(() {
      _url.text = activeBackendUrl;
      _modelPath = modelPath;
      _modelInstallError = modelInstallError;
    });
    await _connect();
    if (mounted && _modelInstallError != null) {
      setState(() => _error = _modelInstallError);
    }
  }

  Future<void> _connect() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final normalized = normalizeBaseUrl(
        _url.text.trim().isEmpty ? activeBackendUrl : _url.text,
      );
      final snapshot = await _client.discover(normalized);
      await _repository?.saveSnapshot(snapshot);
      await _repository?.saveBackendStatus('online');
      setState(() {
        _snapshot = snapshot;
        _backendStatus = 'online';
        _retryAttempt = 0;
        _retryTimer?.cancel();
        _url.text = normalized;
        if (_repository != null) {
          _syncEngine = SyncEngine(
            _repository!,
            HttpSyncTransport(
              _client.baseUrl,
              headers: {
                if (hostHeaderFor(_client.baseUrl) != null)
                  'host': hostHeaderFor(_client.baseUrl)!,
              },
            ),
          );
        }
      });
      await _syncNow(automatic: true);
    } catch (error) {
      await _repository?.saveBackendStatus('offline');
      if (mounted) setState(() {
        _backendStatus = 'offline';
        _syncLabel = _snapshot == null ? 'Backend desconectado' : 'Usando datos locales';
        _error = _snapshot == null
            ? 'No hay un contrato UAP en caché. Conectate una vez para habilitar el CRUD offline; el asistente local sigue disponible para consultas generales.'
            : 'Backend desconectado. Usando datos locales.';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send() async {
    final request = _request.text.trim();
    if (request.isEmpty) return;
    final snapshot = _snapshot ?? UapSnapshot.empty;
    setState(() {
      _messages.add(_Message('Vos', request));
      _request.clear();
      _busy = true;
      _error = null;
    });
    try {
      if (_modelPath == null) {
        throw StateError(
          'El modelo local incluido no está disponible. Revisá la configuración para obtener detalles.',
        );
      }
      setState(() => _loadingModel = true);
      try {
        await _engine.load(_modelPath!);
      } finally {
        if (mounted) setState(() => _loadingModel = false);
      }
      if (mounted) setState(() {});
      final localRecords =
          await _repository?.summaries() ?? const <LocalRecord>[];
      if (mounted) setState(() => _syncLabel = 'Interpretando');
      final raw = await _engine.generate(
        PromptBuilder.build(
           snapshot,
          request,
          localRecords: localRecords,
          syncStatus: _syncLabel,
        ),
      );
      if (mounted) setState(() => _syncLabel = 'Validando');
      final intent = IntentValidator.parse(
        raw,
         snapshot.toolList,
        request: request,
         schema: snapshot.schema,
      );
      if (!intent.isToolCall) {
        final text = intent.text!;
        setState(() => _messages.add(_Message('Asistente', text)));
        await _speakIfAlexa(text);
        return;
      }
      final tool = snapshot.toolList.firstWhere(
        (item) => item.id == intent.toolId,
      );
      if (tool.isWrite) setState(() => _syncLabel = 'Esperando confirmación');
      if (const ConfirmationGate().requires(tool) && !await _confirm(tool)) {
        final text = AssistantResultFormatter.cancelled(tool);
        setState(() => _messages.add(_Message('Asistente', text)));
        await _speakIfAlexa(text);
        return;
      }
      try {
        final operation = UapValidator.operation(tool);
        final entity = UapValidator.entity(tool);
        if (_backendStatus != 'online' && (operation == 'list' || operation == 'get')) {
          if (_repository == null) throw StateError('No hay almacenamiento local disponible.');
          final Map<String, dynamic> result;
          if (operation == 'get') {
            final record = await _repository!.read(entity, intent.input['id'].toString());
            result = {'data': record?.data};
          } else {
            final records = (await _repository!.summaries(entity: entity)).where((record) => record.deletedAt == null).toList();
            result = {'data': records.map((record) => record.data).toList()};
          }
          final text = '${AssistantResultFormatter.read(tool, result)} Datos locales${await _lastSyncSuffix()}.';
          setState(() => _messages.add(_Message('Asistente', text)));
          await _speakIfAlexa(text);
          return;
        }
        if (_backendStatus != 'online' && tool.isWrite) {
          if (_repository == null) throw StateError('No hay almacenamiento local disponible.');
          await _queueOfflineMutation(tool, intent.input);
          const text = 'El backend está desconectado. El cambio se guardó en datos locales y quedó pendiente de sincronización.';
          setState(() => _messages.add(const _Message('Asistente', text)));
          await _speakIfAlexa(text);
          return;
        }
        final result = await _client.invoke(
          tool,
          intent.input,
          confirmed: true,
        );
        final text = tool.isWrite
            ? AssistantResultFormatter.mutation(
                tool,
                result,
                input: intent.input,
              )
            : AssistantResultFormatter.read(tool, result);
        if (tool.isWrite)
          await _cacheSuccessfulMutation(tool, intent.input, result);
        if (!tool.isWrite) await _cacheRead(tool, result);
        await _repository?.saveBackendStatus('online');
        if (mounted) setState(() => _backendStatus = 'online');
        setState(() => _messages.add(_Message('Asistente', text)));
        await _speakIfAlexa(text);
      } catch (error) {
        if (_isConnectivityError(error)) {
          await _repository?.saveBackendStatus('offline');
          if (mounted) setState(() => _backendStatus = 'offline');
        }
        if (tool.isWrite &&
            _repository != null &&
            _isConnectivityError(error)) {
          await _queueOfflineMutation(tool, intent.input);
          setState(
            () => _messages.add(
              const _Message(
                'Asistente',
                'El backend no está disponible. El cambio se guardó localmente y quedó pendiente.',
              ),
            ),
          );
          await _speakIfAlexa(
            'El backend no está disponible. El cambio se guardó localmente y quedó pendiente.',
          );
          return;
        }
        if (!tool.isWrite && _repository != null && _snapshot != null) {
          final operation = UapValidator.operation(tool);
          if (operation == 'list' || operation == 'get') {
            final Map<String, dynamic> result;
            if (operation == 'get') {
              final record = await _repository!.read(UapValidator.entity(tool), intent.input['id'].toString());
              result = {'data': record?.data};
            } else {
              final records = (await _repository!.summaries(entity: UapValidator.entity(tool))).where((record) => record.deletedAt == null).toList();
              result = {'data': records.map((record) => record.data).toList()};
            }
            final text = '${AssistantResultFormatter.read(tool, result)} Datos locales${await _lastSyncSuffix()}.';
            if (mounted) setState(() => _messages.add(_Message('Asistente', text)));
            await _speakIfAlexa(text);
            return;
          }
        }
        final text = AssistantResultFormatter.failure(tool, error);
        setState(() => _messages.add(_Message('Asistente', text)));
        await _speakIfAlexa(text);
      }
    } catch (error) {
      final text = _actionableError(error);
      setState(() => _messages.add(_Message('Asistente', text)));
      await _speakIfAlexa(text);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirm(UapTool tool) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Confirmar acción'),
          content: Text('${tool.name} cambiará datos del backend.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Confirmar'),
            ),
          ],
        ),
      ) ??
      false;
  String _clean(Object error) =>
      error.toString().replaceFirst('Exception: ', '');

  String _actionableError(Object error) {
    final value = _clean(error);
    if (value.contains('BUNDLED_MODEL_MISSING'))
      return 'Falta el modelo incluido del asistente. Reinstalá la aplicación para instalarlo automáticamente.';
    if (value.contains('local model could not be loaded'))
      return 'El modelo incluido está instalado, pero no se pudo cargar. Reiniciá la aplicación y revisá el espacio disponible.';
    if (value.contains('GENERATION_FAILED') ||
        value.contains('Tokenization failed'))
      return 'No pude interpretar la solicitud con el modelo local. Probá con una solicitud más breve y una sola acción.';
    return 'No pude completar la solicitud. $value';
  }

  Future<void> _speakIfAlexa(String text) async {
    if (_mode != _AssistantMode.alexa || text == _lastSpokenText) return;
    _lastSpokenText = text;
    await _speech.stop();
    await _speech.speak(text);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Asistente UAP'),
      actions: [
        IconButton(
          tooltip: 'Configuración y detalles',
          onPressed: _showSettings,
          icon: const Icon(Icons.tune),
        ),
      ],
    ),
    body: SafeArea(
      child: Column(
        children: [
          _statusBar(),
          _modeToggle(),
          Expanded(
            child: _mode == _AssistantMode.history ? _conversation() : _alexa(),
          ),
          if (_mode == _AssistantMode.history) _composer(),
        ],
      ),
    ),
  );
  Widget _statusBar() => Padding(
    padding: const EdgeInsets.fromLTRB(20, 12, 20, 4),
    child: Row(
      children: [
        Icon(_backendStatus == 'online' ? Icons.cloud_done : Icons.cloud_off, size: 16),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
             _backendLabel,
            style: Theme.of(context).textTheme.labelLarge,
          ),
        ),
        Text(_syncLabel, style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(width: 8),
        Text(_modelStatusLabel, style: Theme.of(context).textTheme.labelSmall),
      ],
    ),
  );

  Widget _modeToggle() => Padding(
    padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
    child: SegmentedButton<_AssistantMode>(
      segments: const [
        ButtonSegment(
          value: _AssistantMode.history,
          label: Text('Historial'),
          icon: Icon(Icons.forum_outlined),
        ),
        ButtonSegment(
          value: _AssistantMode.alexa,
          label: Text('Alexa'),
          icon: Icon(Icons.mic_none),
        ),
      ],
      selected: {_mode},
      onSelectionChanged: _busy
          ? null
          : (selection) => setState(() => _mode = selection.first),
    ),
  );

  Widget _alexa() => Padding(
    padding: const EdgeInsets.fromLTRB(24, 20, 24, 12),
    child: Column(
      children: [
        const SizedBox(height: 12),
        Text(
          _listening
              ? 'Escuchando...'
              : _busy
              ? 'Procesando...'
              : '¿Qué necesitás?',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(
          _listening
              ? 'Hablá en español. Enviaré la transcripción al mismo asistente.'
              : 'Tocá el micrófono para hacer una solicitud.',
          textAlign: TextAlign.center,
        ),
        const Spacer(),
        Semantics(
          button: true,
          label: _listening ? 'Detener escucha' : 'Hablar con el asistente',
          child: SizedBox(
            width: 156,
            height: 156,
            child: FilledButton(
              onPressed: _busy ? null : _openComposer,
              style: FilledButton.styleFrom(
                shape: const CircleBorder(),
                padding: EdgeInsets.zero,
              ),
              child: Icon(_listening ? Icons.hearing : Icons.mic, size: 64),
            ),
          ),
        ),
        const SizedBox(height: 24),
        if (_messages.isNotEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(_messages.last.text),
              ),
            ),
          ),
        if (_error != null) _errorBox(),
        const Spacer(),
      ],
    ),
  );

  Widget _conversation() => _messages.isEmpty
      ? Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.forum_outlined,
                  size: 48,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 16),
                Text(
                  'Pedile al asistente local que consulte o actualice este servicio.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                const Text(
                  'No se envía nada a un servicio en la nube.',
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        )
      : ListView.builder(
          padding: const EdgeInsets.all(20),
          itemCount: _messages.length,
          itemBuilder: (context, index) {
            final message = _messages[index];
            return Align(
              alignment: message.author == 'Vos'
                  ? Alignment.centerRight
                  : Alignment.centerLeft,
              child: Container(
                constraints: const BoxConstraints(maxWidth: 340),
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: message.author == 'Vos'
                      ? Theme.of(context).colorScheme.primaryContainer
                      : Theme.of(context).colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Text(message.text),
              ),
            );
          },
        );
  Widget _composer() => Padding(
    padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: TextField(
            controller: _request,
            minLines: 1,
            maxLines: 4,
            enabled: !_busy,
            decoration: const InputDecoration(
              hintText: 'Escribí una solicitud o pregunta',
              border: OutlineInputBorder(),
            ),
            onSubmitted: (_) => _send(),
          ),
        ),
        const SizedBox(width: 4),
        IconButton(
          tooltip: 'Enviar solicitud de texto',
          icon: const Icon(Icons.send),
          onPressed: _busy ? null : _send,
        ),
      ],
    ),
  );
  Future<void> _openComposer() async {
    try {
      if (!await _voice.isAvailable) {
        if (mounted)
          setState(
            () => _error =
                'El reconocimiento de voz de Android no está disponible. Instalá o habilitá un servicio de voz.',
          );
        return;
      }
      if (mounted)
        setState(() {
          _listening = true;
          _error = null;
        });
      final text = await _voice.listenOnce();
      if (text != null && text.trim().isNotEmpty) {
        _request.text = text;
        await _send();
      }
    } catch (error) {
      if (mounted)
        setState(
          () => _error =
              'La entrada de voz no está disponible: ${_clean(error)} Podés escribir la solicitud.',
        );
    } finally {
      if (mounted) setState(() => _listening = false);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _connectivitySubscription?.cancel();
    _retryTimer?.cancel();
    _pendingTimer?.cancel();
    _url.dispose();
    _request.dispose();
    _engine.dispose();
    _speech.dispose();
    super.dispose();
  }

  Future<void> _showSettings() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => Padding(
        padding: const EdgeInsets.all(24),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Configuración y detalles',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 20),
              Text('Endpoint activo: ${_client.baseUrl}'),
              const SizedBox(height: 8),
              Text(
                hostHeaderFor(_client.baseUrl) == null
                    ? 'Enrutamiento normal: se envía el nombre de host de la URL como Host.'
                    : 'Enrutamiento USB: las solicitudes usan 127.0.0.1:8080 y envían Host: $backendHostHeader.',
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _url,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(
                  labelText: 'URL opcional del backend',
                  hintText: 'http://10.0.2.2:8080',
                ),
                onSubmitted: (_) {
                  Navigator.pop(context);
                  _connect();
                },
              ),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _busy
                    ? null
                    : () {
                        Navigator.pop(context);
                        _connect();
                      },
                icon: const Icon(Icons.link),
                label: Text(_busy ? 'Conectando...' : 'Conectar backend'),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: _syncEngine == null || _busy ? null : _syncNow,
                icon: const Icon(Icons.sync),
                label: const Text('Sincronizar ahora'),
              ),
              const Divider(height: 32),
              Text(
                _modelPath == null
                    ? 'Modelo incluido: no instalado'
                    : 'Modelo incluido instalado: ${ModelAsset.displayName}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 8),
              const SizedBox(height: 8),
              const Text(
                'Modelo automático: ${ModelAsset.displayName}. Fuente: ${ModelAsset.sourceUrl}. Licencia: ${ModelAsset.license}. El contexto se limita a 2048 tokens y la salida a 256 tokens.',
              ),
              if (_snapshot != null) ...[
                const SizedBox(height: 16),
                const Text(
                  'Los detalles UAP descubiertos están disponibles para el orquestador y no se muestran en la pantalla principal.',
                ),
              ],
              if (_error != null) ...[const SizedBox(height: 16), _errorBox()],
            ],
          ),
        ),
      ),
    );
  }

  Widget _errorBox() => Card(
    color: Theme.of(context).colorScheme.errorContainer,
    child: Padding(padding: const EdgeInsets.all(14), child: Text(_error!)),
  );

  String get _modelStatusLabel => _loadingModel
      ? 'Cargando modelo...'
      : switch (_engine.status) {
          LocalLlmStatus.modelNotInstalled =>
            _modelPath == null
                ? 'Modelo incluido ausente'
                : 'Modelo incluido instalado',
          LocalLlmStatus.modelSelected => 'Modelo seleccionado',
          LocalLlmStatus.loading => 'Cargando modelo...',
          LocalLlmStatus.ready => 'Modelo listo',
          LocalLlmStatus.error => 'Error del modelo',
          LocalLlmStatus.unavailable => 'Modelo no disponible',
        };

  Future<void> _cacheSuccessfulMutation(
    UapTool tool,
    Map<String, dynamic> input,
    dynamic result,
  ) async {
    final data = result is Map && result['data'] is Map
        ? (result['data'] as Map).cast<String, dynamic>()
        : input;
    final id = data['id']?.toString() ?? input['id']?.toString();
    if (id == null || _repository == null) return;
    await _repository!.upsert(
      entity: tool.raw['entity']?.toString() ?? tool.id.split('.').first,
      recordId: id,
      data: data,
      state: SyncState.synced,
      deletedAt: UapValidator.operation(tool) == 'delete' ? DateTime.now() : null,
    );
    if (mounted) setState(() => _syncLabel = 'Sincronizado');
  }

  Future<void> _queueOfflineMutation(
    UapTool tool,
    Map<String, dynamic> input,
  ) async {
    final entity = tool.raw['entity']?.toString() ?? tool.id.split('.').first;
    final id =
        input['id']?.toString() ??
        _localUuid();
    final operation = UapValidator.operation(tool).isEmpty
        ? tool.id.split('.').last
        : UapValidator.operation(tool);
    await _repository!.applyLocalMutation(
      entity: entity,
      recordId: id,
      operation: operation,
      payload: input,
    );
    _startPendingTimer();
    if (mounted) setState(() => _syncLabel = 'Pendiente de sincronización');
  }

  Future<void> _syncNow({bool automatic = false}) async {
    if (_syncEngine == null) return;
    setState(() => _syncLabel = 'Sincronizando...');
    try {
      final state = await _syncEngine!.sync();
      await _repository?.saveBackendStatus('online');
      if (mounted)
        setState(() {
          _backendStatus = 'online';
          _syncLabel = switch (state) {
            SyncState.conflict => 'Conflicto',
            SyncState.failed => 'Fallido',
            _ => 'Sincronizado',
          };
        });
    } catch (error) {
      if (mounted)
        setState(() {
          _backendStatus = 'offline';
          _syncLabel = _clean(error).contains('no disponible')
              ? 'Protocolo de sincronización no disponible'
              : 'Fallido';
        });
      if (!automatic) await _repository?.saveBackendStatus('offline');
    }
  }

  String get _backendLabel => _backendStatus == 'online'
      ? 'Backend conectado'
      : _snapshot == null ? 'Backend desconectado' : 'Backend desconectado · usando datos locales';

  void _scheduleReconnect() {
    if (_retryAttempt >= 5 || _retryTimer?.isActive == true) return;
    final delays = [1, 2, 5, 10, 30];
    _retryTimer = Timer(Duration(seconds: delays[_retryAttempt]), () async {
      _retryAttempt++;
      await _connect();
      if (_backendStatus != 'online') _scheduleReconnect();
    });
  }

  void _startPendingTimer() {
    _pendingTimer ??= Timer.periodic(const Duration(minutes: 2), (_) {
      if (_backendStatus != 'online') _scheduleReconnect();
      else _syncNow(automatic: true);
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _retryAttempt = 0;
      _scheduleReconnect();
    }
  }

  Future<void> _cacheRead(UapTool tool, dynamic result) async {
    if (_repository == null) return;
    final entity = UapValidator.entity(tool);
    final data = result is Map ? result['data'] : result;
    if (data is List) {
      for (final item in data.whereType<Map>()) {
        final value = item.cast<String, dynamic>();
        final id = value['id']?.toString();
        if (id != null) await _repository!.upsert(entity: entity, recordId: id, data: value);
      }
    } else if (data is Map && data['id'] != null) {
      final value = data.cast<String, dynamic>();
      await _repository!.upsert(entity: entity, recordId: value['id'].toString(), data: value);
    }
  }

  Future<String> _lastSyncSuffix() async {
    final value = await _repository?.lastSyncAt();
    return value == null ? '' : ' · última sincronización ${_formatTime(value)}';
  }

  String _formatTime(DateTime? value) => value == null ? 'nunca' : boliviaTime(value);

  String _localUuid() {
    final seed = DateTime.now().microsecondsSinceEpoch.toRadixString(16).padLeft(12, '0');
    return '00000000-0000-4000-8000-${seed.substring(seed.length - 12)}';
  }

  bool _isConnectivityError(Object error) =>
      error is TimeoutException ||
      error is SocketException ||
      error is http.ClientException;
}
