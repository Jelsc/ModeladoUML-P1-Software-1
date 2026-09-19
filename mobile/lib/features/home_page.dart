import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

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

class _HomePageState extends State<HomePage> {
  final _url = TextEditingController();
  final _request = TextEditingController();
  final _client = UapClient();
  final _models = ModelManager();
  final _engine = AndroidLlamaCppEngine();
  final _voice = const OfflineVoice();
  UapSnapshot? _snapshot;
  String? _modelPath;
  String? _modelInstallError;
  String? _error;
  bool _busy = false;
  bool _loadingModel = false;
  bool _listening = false;
  _AssistantMode _mode = _AssistantMode.history;
  final _messages = <_Message>[];
  OfflineRepository? _repository;
  SyncEngine? _syncEngine;
  String _syncLabel = 'Solo local';

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    try {
      final database = await openOfflineDatabase();
      _repository = OfflineRepository(database);
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
      setState(() {
        _snapshot = snapshot;
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
    } catch (error) {
      setState(() => _error = _clean(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send() async {
    final request = _request.text.trim();
    if (request.isEmpty) return;
    if (_snapshot == null) {
      setState(
        () => _error = 'Conectá un backend UAP antes de enviar una solicitud.',
      );
      return;
    }
    setState(() {
      _messages.add(_Message('You', request));
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
      final raw = await _engine.generate(
        PromptBuilder.build(
          _snapshot!,
          request,
          localRecords: localRecords,
          syncStatus: _syncLabel,
        ),
      );
      final intent = IntentValidator.parse(
        raw,
        _snapshot!.toolList,
        request: request,
        schema: _snapshot!.schema,
      );
      if (!intent.isToolCall) {
        setState(() => _messages.add(_Message('Assistant', intent.text!)));
        return;
      }
      final tool = _snapshot!.toolList.firstWhere(
        (item) => item.id == intent.toolId,
      );
      if (tool.isWrite && !await _confirm(tool)) {
        setState(
          () => _messages.add(
            _Message('Assistant', AssistantResultFormatter.cancelled(tool)),
          ),
        );
        return;
      }
      try {
        final result = await _client.invoke(
          tool,
          intent.input,
          confirmed: true,
        );
        final text = tool.isWrite
            ? AssistantResultFormatter.mutation(tool, result)
            : AssistantResultFormatter.read(tool, result);
        if (tool.isWrite)
          await _cacheSuccessfulMutation(tool, intent.input, result);
        setState(() => _messages.add(_Message('Assistant', text)));
      } catch (error) {
        if (tool.isWrite &&
            _repository != null &&
            _isConnectivityError(error)) {
          await _queueOfflineMutation(tool, intent.input);
          setState(
            () => _messages.add(
              const _Message(
                'Assistant',
                'El backend no está disponible. El cambio se guardó localmente y quedó pendiente.',
              ),
            ),
          );
          return;
        }
        setState(
          () => _messages.add(
            _Message(
              'Assistant',
              AssistantResultFormatter.failure(tool, error),
            ),
          ),
        );
      }
    } catch (error) {
      setState(
        () => _messages.add(_Message('Assistant', _actionableError(error))),
      );
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
        Icon(_snapshot == null ? Icons.cloud_off : Icons.cloud_done, size: 16),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            _snapshot == null ? 'Backend desconectado' : 'UAP conectado',
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
              alignment: message.author == 'You'
                  ? Alignment.centerRight
                  : Alignment.centerLeft,
              child: Container(
                constraints: const BoxConstraints(maxWidth: 340),
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: message.author == 'You'
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
    _url.dispose();
    _request.dispose();
    _engine.dispose();
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
        'local-${DateTime.now().microsecondsSinceEpoch}';
    final operation = tool.operation.isEmpty
        ? tool.id.split('.').last
        : tool.operation;
    await _repository!.upsert(
      entity: entity,
      recordId: id,
      data: input,
      state: SyncState.pending,
      deletedAt: operation == 'delete' ? DateTime.now() : null,
    );
    await _repository!.enqueue(
      entity: entity,
      recordId: id,
      operation: operation,
      payload: input,
      baseVersion: null,
    );
    if (mounted) setState(() => _syncLabel = 'Pendiente');
  }

  Future<void> _syncNow() async {
    if (_syncEngine == null) return;
    setState(() => _syncLabel = 'Sincronizando...');
    try {
      await _syncEngine!.sync();
      if (mounted) setState(() => _syncLabel = 'Sincronizado');
    } catch (error) {
      if (mounted)
        setState(
          () => _syncLabel = _clean(error).contains('no disponible')
              ? 'Protocolo de sincronización no disponible'
              : 'Sincronización fallida',
        );
    }
  }

  bool _isConnectivityError(Object error) =>
      error is TimeoutException ||
      error is SocketException ||
      error is http.ClientException;
}
