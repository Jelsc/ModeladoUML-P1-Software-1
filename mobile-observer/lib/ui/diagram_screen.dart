import 'dart:async';

import 'package:flutter/material.dart';

import '../data/team_api.dart';
import '../data/team_realtime.dart';
import '../models/team_models.dart';
import 'observer_theme.dart';

class ObserverDiagramScreen extends StatefulWidget {
  const ObserverDiagramScreen({
    super.key,
    required this.api,
    required this.summary,
    required this.onUnauthorized,
  });
  final TeamApi api;
  final DiagramSummary summary;
  final VoidCallback onUnauthorized;

  @override
  State<ObserverDiagramScreen> createState() => _ObserverDiagramScreenState();
}

class _ObserverDiagramScreenState extends State<ObserverDiagramScreen>
    with WidgetsBindingObserver {
  DiagramData? _diagram;
  List<DiagramMember> _members = const [];
  List<ChatMessage> _messages = const [];
  List<ActivityItem> _activity = const [];
  DiagramDigest? _digest;
  AiSettings? _aiSettings;
  String _channel = 'diseno';
  String? _error;
  bool _loading = true;
  bool _backgrounded = false;
  bool _aiThinking = false;
  String? _aiRequester;
  RealtimeStatus _realtimeStatus = RealtimeStatus.disconnected;
  TeamRealtime? _realtime;
  Timer? _readRefreshTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_loadAll());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _readRefreshTimer?.cancel();
    unawaited(_realtime?.stop());
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _backgrounded = true;
      unawaited(_realtime?.stop());
      _realtime = null;
    } else if (state == AppLifecycleState.resumed && _backgrounded) {
      _backgrounded = false;
      unawaited(_loadAll(refresh: true));
    }
  }

  Future<void> _loadAll({bool refresh = false}) async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final results = await Future.wait<Object>([
        widget.api.diagram(widget.summary.id, refresh: refresh),
        widget.api.members(widget.summary.id, refresh: refresh),
        widget.api.chat(widget.summary.id, channel: _channel, refresh: refresh),
        widget.api.activity(widget.summary.id, refresh: refresh),
        widget.api.digest(widget.summary.id, refresh: refresh),
        widget.api.aiSettings(widget.summary.id, refresh: refresh),
      ]);
      if (!mounted) return;
      setState(() {
        _diagram = results[0] as DiagramData;
        _members = results[1] as List<DiagramMember>;
        _messages = _mergeMessages(const [], results[2] as List<ChatMessage>);
        _activity = results[3] as List<ActivityItem>;
        _digest = results[4] as DiagramDigest;
        _aiSettings = results[5] as AiSettings;
        _loading = false;
      });
      _startRealtime();
    } on ApiFailure catch (error) {
      if (_handleRequestFailure(error)) return;
      if (mounted) {
        setState(() {
          _error = error.message;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error =
              'No se pudieron actualizar los datos. Revise la conexión e intente nuevamente.';
          _loading = false;
        });
      }
      _startRealtime();
    }
  }

  Future<void> _loadChannel(String channel) async {
    setState(() {
      _channel = channel;
      _messages = const [];
    });
    try {
      final messages = await widget.api.chat(
        widget.summary.id,
        channel: channel,
        refresh: true,
      );
      if (mounted && _channel == channel) {
        setState(() => _messages = _mergeMessages(const [], messages));
      }
    } on ApiFailure catch (error) {
      if (_handleRequestFailure(error)) return;
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'No se pudo cargar este canal de conversación.',
        );
      }
    }
  }

  void _startRealtime() {
    if (!mounted ||
        _backgrounded ||
        _realtime != null ||
        widget.api.token == null) {
      return;
    }
    final client = TeamRealtime(
      uri: widget.api.websocketEndpoint(
        'diagrams/${Uri.encodeComponent(widget.summary.id)}/ws',
      ),
      onEvent: _onEvent,
      onStatus: (status) {
        if (mounted) setState(() => _realtimeStatus = status);
        if (status == RealtimeStatus.connected && _diagram == null) {
          unawaited(_loadAll(refresh: true));
        }
      },
      onRefreshAfterReconnect: () => _loadAll(refresh: true),
      onUnauthorized: widget.onUnauthorized,
    );
    _realtime = client;
    unawaited(client.start());
  }

  void _onEvent(RealtimeEvent event) {
    final data = event.data;
    switch (event.name) {
      case 'chat.message':
        final message = data['message'];
        if (message is Map) {
          final parsed = ChatMessage.fromJson(
            Map<String, dynamic>.from(message),
          );
          if (parsed.channel == _channel && mounted) {
            setState(() => _messages = _mergeMessages(_messages, [parsed]));
          }
        }
        _scheduleActivityRefresh();
      case 'ai.thinking':
        if (mounted) {
          setState(() {
            _aiThinking = true;
            _aiRequester = data['requester'] is String
                ? data['requester'] as String
                : null;
          });
        }
      case 'ai.done':
      case 'ai.error':
        if (mounted) {
          setState(() {
            _aiThinking = false;
            _aiRequester = null;
          });
        }
      case 'ai.settings':
        unawaited(_refreshAiSettings());
      default:
        if (event.name.startsWith('class.') ||
            event.name.startsWith('relation.') ||
            event.name.startsWith('diagram.')) {
          unawaited(_refreshDiagram());
          _scheduleActivityRefresh();
        }
        if (event.name.startsWith('member.')) unawaited(_refreshMembers());
    }
  }

  Future<void> _refreshDiagram() async {
    try {
      final value = await widget.api.diagram(widget.summary.id, refresh: true);
      if (mounted) setState(() => _diagram = value);
    } on ApiFailure catch (error) {
      _handleRequestFailure(error);
    } catch (_) {}
  }

  Future<void> _refreshMembers() async {
    try {
      final value = await widget.api.members(widget.summary.id, refresh: true);
      if (mounted) setState(() => _members = value);
    } on ApiFailure catch (error) {
      _handleRequestFailure(error);
    } catch (_) {}
  }

  Future<void> _refreshAiSettings() async {
    try {
      final value = await widget.api.aiSettings(
        widget.summary.id,
        refresh: true,
      );
      if (mounted) setState(() => _aiSettings = value);
    } on ApiFailure catch (error) {
      _handleRequestFailure(error);
    } catch (_) {}
  }

  bool _handleRequestFailure(ApiFailure error) {
    if (error.unauthorized) {
      widget.onUnauthorized();
      return true;
    }
    if ((error.statusCode == 403 || error.statusCode == 404) &&
        Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
      return true;
    }
    return false;
  }

  void _scheduleActivityRefresh() {
    _readRefreshTimer?.cancel();
    _readRefreshTimer = Timer(const Duration(milliseconds: 300), () {
      unawaited(_refreshActivityAndDigest());
    });
  }

  Future<void> _refreshActivityAndDigest() async {
    try {
      final results = await Future.wait<Object>([
        widget.api.activity(widget.summary.id, refresh: true),
        widget.api.digest(widget.summary.id, refresh: true),
      ]);
      if (mounted) {
        setState(() {
          _activity = results[0] as List<ActivityItem>;
          _digest = results[1] as DiagramDigest;
        });
      }
    } on ApiFailure catch (error) {
      _handleRequestFailure(error);
    } catch (_) {}
  }

  List<ChatMessage> _mergeMessages(
    List<ChatMessage> current,
    List<ChatMessage> incoming,
  ) {
    final byId = {for (final message in current) message.id: message};
    for (final message in incoming) {
      byId[message.id] = message;
    }
    final result = byId.values.toList();
    result.sort(
      (left, right) =>
          (left.createdAt ?? DateTime.fromMillisecondsSinceEpoch(0)).compareTo(
            right.createdAt ?? DateTime.fromMillisecondsSinceEpoch(0),
          ),
    );
    return result;
  }

  @override
  Widget build(BuildContext context) {
    final diagram = _diagram;
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: Text(
            diagram?.title ?? widget.summary.title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          actions: [
            IconButton(
              tooltip: 'Actualizar',
              onPressed: () => _loadAll(refresh: true),
              icon: const Icon(Icons.refresh),
            ),
          ],
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Modelo'),
              Tab(text: 'Conversación'),
              Tab(text: 'Bitácora'),
              Tab(text: 'Resumen'),
            ],
          ),
        ),
        body: Column(
          children: [
            _RealtimeStrip(status: _realtimeStatus),
            if (_aiThinking) _ThinkingStrip(requester: _aiRequester),
            if (_error != null && diagram != null)
              MaterialBanner(
                content: Text(_error!),
                actions: [
                  TextButton(
                    onPressed: () => _loadAll(refresh: true),
                    child: const Text('Reintentar'),
                  ),
                ],
              ),
            Expanded(
              child: _loading && diagram == null
                  ? const Center(child: CircularProgressIndicator())
                  : diagram == null
                  ? _LoadError(
                      message: _error ?? 'No se pudo cargar el diagrama.',
                      onRetry: () => _loadAll(refresh: true),
                    )
                  : TabBarView(
                      children: [
                        DiagramModelTab(diagram: diagram),
                        ChatReadOnlyTab(
                          messages: _messages,
                          channel: _channel,
                          onChannelChanged: _loadChannel,
                        ),
                        ActivityReadOnlyTab(items: _activity),
                        SummaryReadOnlyTab(
                          digest: _digest,
                          members: _members,
                          aiSettings: _aiSettings,
                        ),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class DiagramModelTab extends StatefulWidget {
  const DiagramModelTab({super.key, required this.diagram});
  final DiagramData diagram;

  @override
  State<DiagramModelTab> createState() => _DiagramModelTabState();
}

class _DiagramModelTabState extends State<DiagramModelTab> {
  bool _diagramView = true;
  final TransformationController _transform = TransformationController();

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final diagram = widget.diagram;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 8, 4),
          child: Row(
            children: [
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(
                    value: true,
                    label: Text('Diagrama'),
                    icon: Icon(Icons.account_tree_outlined),
                  ),
                  ButtonSegment(
                    value: false,
                    label: Text('Lista'),
                    icon: Icon(Icons.list_alt),
                  ),
                ],
                selected: {_diagramView},
                onSelectionChanged: (value) =>
                    setState(() => _diagramView = value.first),
              ),
              const Spacer(),
              if (_diagramView && diagram.classes.isNotEmpty)
                IconButton(
                  tooltip: 'Restablecer vista',
                  onPressed: () => _transform.value = Matrix4.identity(),
                  icon: const Icon(Icons.center_focus_strong),
                ),
            ],
          ),
        ),
        Expanded(
          child: _diagramView
              ? _UmlCanvas(diagram: diagram, controller: _transform)
              : _modelList(diagram),
        ),
      ],
    );
  }

  Widget _modelList(DiagramData diagram) => ListView(
    physics: const AlwaysScrollableScrollPhysics(),
    padding: const EdgeInsets.all(16),
    children: [
      _SectionHeading(title: 'Clases', count: diagram.classes.length),
      const SizedBox(height: 10),
      if (diagram.classes.isEmpty)
        const _EmptyNote('Este diagrama todavía no tiene clases.'),
      ...diagram.classes.map(
        (item) => Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: _ClassCard(item: item),
        ),
      ),
      const SizedBox(height: 14),
      _SectionHeading(title: 'Relaciones', count: diagram.relations.length),
      const SizedBox(height: 10),
      if (diagram.relations.isEmpty)
        const _EmptyNote('No hay relaciones para mostrar.'),
      ...diagram.relations.map(
        (relation) => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: _RelationCard(relation: relation),
        ),
      ),
    ],
  );
}

class _UmlCanvas extends StatelessWidget {
  const _UmlCanvas({required this.diagram, required this.controller});
  final DiagramData diagram;
  final TransformationController controller;

  @override
  Widget build(BuildContext context) {
    if (diagram.classes.isEmpty) {
      return const Center(
        child: _EmptyNote('Este diagrama todavía no tiene clases.'),
      );
    }
    final positioned = <DiagramClass>[];
    final used = <String>{};
    for (var index = 0; index < diagram.classes.length; index++) {
      final item = diagram.classes[index];
      var x = item.x.clamp(0, 18000), y = item.y.clamp(0, 18000);
      final key = '$x:$y';
      if (!used.add(key)) {
        x = (x + (index % 4) * 36).clamp(0, 18000);
        y = (y + (index ~/ 4 + 1) * 36).clamp(0, 18000);
      }
      positioned.add(
        DiagramClass(
          id: item.id,
          name: item.name,
          x: x,
          y: y,
          isAssociation: item.isAssociation,
          attributes: item.attributes,
          methods: item.methods,
        ),
      );
    }
    final width =
        (positioned
                    .map((item) => item.x)
                    .fold<int>(0, (a, b) => a > b ? a : b) +
                320)
            .clamp(640, 20000)
            .toDouble();
    final height =
        (positioned
                    .map((item) => item.y)
                    .fold<int>(0, (a, b) => a > b ? a : b) +
                240)
            .clamp(480, 20000)
            .toDouble();
    return InteractiveViewer(
      transformationController: controller,
      constrained: false,
      minScale: .15,
      maxScale: 2.5,
      boundaryMargin: const EdgeInsets.all(120),
      child: SizedBox(
        width: width,
        height: height,
        child: CustomPaint(
          painter: _UmlPainter(
            positioned,
            diagram.relations,
            Theme.of(context).colorScheme,
            Theme.of(context).textTheme,
          ),
        ),
      ),
    );
  }
}

class _UmlPainter extends CustomPainter {
  _UmlPainter(this.classes, this.relations, this.colors, this.textTheme);
  final List<DiagramClass> classes;
  final List<DiagramRelation> relations;
  final ColorScheme colors;
  final TextTheme textTheme;
  static const nodeWidth = 240.0;
  double _nodeHeight(DiagramClass item) =>
      48 +
      (item.attributes.length + item.methods.length) * 22.0 +
      (item.attributes.isNotEmpty && item.methods.isNotEmpty ? 1 : 0) * 8;
  @override
  void paint(Canvas canvas, Size size) {
    final byId = {for (final item in classes) item.id: item};
    for (final relation in relations) {
      final source = byId[relation.sourceId], target = byId[relation.targetId];
      if (source == null || target == null) continue;
      final a = Offset(
            source.x + nodeWidth / 2,
            source.y + _nodeHeight(source) / 2,
          ),
          b = Offset(
            target.x + nodeWidth / 2,
            target.y + _nodeHeight(target) / 2,
          );
      canvas.drawLine(
        a,
        b,
        Paint()
          ..color = ObserverTheme.blue
          ..strokeWidth = 2,
      );
      final label =
          '${relation.type}${relation.label == null ? '' : ' · ${relation.label}'}${relation.sourceMultiplicity == null && relation.targetMultiplicity == null ? '' : ' · ${relation.sourceMultiplicity ?? ''} — ${relation.targetMultiplicity ?? ''}'}';
      _drawText(
        canvas,
        label,
        Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2),
        textTheme.labelSmall?.copyWith(color: ObserverTheme.ink),
        maxWidth: 200,
      );
    }
    for (final item in classes) {
      final rect = Rect.fromLTWH(
        item.x.toDouble(),
        item.y.toDouble(),
        nodeWidth,
        _nodeHeight(item),
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(12)),
        Paint()..color = colors.surface,
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(12)),
        Paint()
          ..color = ObserverTheme.ink
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
      var y = item.y + 8.0;
      _drawText(
        canvas,
        item.name,
        Offset(item.x + 12.0, y),
        textTheme.titleSmall?.copyWith(
          fontWeight: FontWeight.w700,
          color: ObserverTheme.ink,
        ),
        maxWidth: nodeWidth - 24,
      );
      y += 32;
      canvas.drawLine(
        Offset(item.x.toDouble(), y),
        Offset(item.x + nodeWidth, y),
        Paint()..color = ObserverTheme.blue.withValues(alpha: .5),
      );
      y += 6;
      for (final attribute in item.attributes) {
        _drawText(
          canvas,
          '+ ${attribute.name}: ${attribute.type}',
          Offset(item.x + 10.0, y),
          textTheme.bodySmall?.copyWith(color: ObserverTheme.ink),
          maxWidth: nodeWidth - 20,
        );
        y += 22;
      }
      if (item.attributes.isNotEmpty && item.methods.isNotEmpty) y += 8;
      if (item.methods.isNotEmpty) {
        canvas.drawLine(
          Offset(item.x.toDouble(), y),
          Offset(item.x + nodeWidth, y),
          Paint()..color = ObserverTheme.blue.withValues(alpha: .5),
        );
        y += 6;
      }
      for (final method in item.methods) {
        _drawText(
          canvas,
          '+ ${method.name}(): ${method.type}',
          Offset(item.x + 10.0, y),
          textTheme.bodySmall?.copyWith(color: ObserverTheme.ink),
          maxWidth: nodeWidth - 20,
        );
        y += 22;
      }
    }
  }

  void _drawText(
    Canvas canvas,
    String value,
    Offset offset,
    TextStyle? style, {
    required double maxWidth,
  }) {
    final painter = TextPainter(
      text: TextSpan(text: value, style: style),
      textDirection: TextDirection.ltr,
      maxLines: 2,
      ellipsis: '…',
    )..layout(maxWidth: maxWidth);
    painter.paint(canvas, offset);
  }

  @override
  bool shouldRepaint(covariant _UmlPainter oldDelegate) =>
      oldDelegate.classes != classes ||
      oldDelegate.relations != relations ||
      oldDelegate.colors != colors;
}

class ChatReadOnlyTab extends StatelessWidget {
  const ChatReadOnlyTab({
    super.key,
    required this.messages,
    required this.channel,
    required this.onChannelChanged,
  });
  final List<ChatMessage> messages;
  final String channel;
  final ValueChanged<String> onChannelChanged;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
        child: Row(
          children: [
            const Icon(Icons.lock_outline, size: 17),
            const SizedBox(width: 7),
            Text(
              'Solo lectura',
              style: Theme.of(context).textTheme.labelMedium,
            ),
            const Spacer(),
            DropdownButton<String>(
              value: channel,
              underline: const SizedBox.shrink(),
              items: const [
                DropdownMenuItem(value: 'diseno', child: Text('Diseño')),
                DropdownMenuItem(
                  value: 'desarrollo',
                  child: Text('Desarrollo'),
                ),
                DropdownMenuItem(value: 'test', child: Text('Test')),
              ],
              onChanged: (value) {
                if (value != null) onChannelChanged(value);
              },
            ),
          ],
        ),
      ),
      Expanded(
        child: messages.isEmpty
            ? const Center(
                child: _EmptyNote('Todavía no hay mensajes en este canal.'),
              )
            : ListView.builder(
                reverse: true,
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
                itemCount: messages.length,
                itemBuilder: (context, index) => _MessageCard(
                  message: messages[messages.length - index - 1],
                ),
              ),
      ),
    ],
  );
}

class ActivityReadOnlyTab extends StatelessWidget {
  const ActivityReadOnlyTab({super.key, required this.items});
  final List<ActivityItem> items;
  @override
  Widget build(BuildContext context) => items.isEmpty
      ? const Center(child: _EmptyNote('Todavía no hay actividad registrada.'))
      : ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          itemCount: items.length,
          itemBuilder: (context, index) => _ActivityCard(item: items[index]),
        );
}

class SummaryReadOnlyTab extends StatelessWidget {
  const SummaryReadOnlyTab({
    super.key,
    required this.digest,
    required this.members,
    required this.aiSettings,
  });
  final DiagramDigest? digest;
  final List<DiagramMember> members;
  final AiSettings? aiSettings;

  @override
  Widget build(BuildContext context) {
    final settings = aiSettings;
    final digestValue = digest;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      children: [
        _SectionHeading(title: 'Estado de la IA'),
        const SizedBox(height: 10),
        _InfoCard(
          icon: Icons.auto_awesome_outlined,
          title: settings == null
              ? 'Estado no disponible'
              : !settings.enabled
              ? 'IA desactivada'
              : settings.canEdit
              ? 'IA activa · puede editar'
              : 'IA activa · solo responde',
          subtitle: 'La aplicación no envía solicitudes a la IA.',
          tint: const Color(0xFFFFF1D9),
        ),
        const SizedBox(height: 20),
        _SectionHeading(title: 'Desde tu última visita'),
        const SizedBox(height: 10),
        if (digestValue == null)
          const _EmptyNote('Resumen no disponible.')
        else
          _DigestCard(digest: digestValue),
        const SizedBox(height: 20),
        _SectionHeading(title: 'Equipo', count: members.length),
        const SizedBox(height: 10),
        if (members.isEmpty)
          const _EmptyNote('No hay integrantes para mostrar.'),
        ...members.map((member) => _MemberCard(member: member)),
      ],
    );
  }
}

class ReadOnlyDiagramWorkspace extends StatelessWidget {
  const ReadOnlyDiagramWorkspace({
    super.key,
    required this.diagram,
    required this.messages,
    required this.channel,
    required this.onChannelChanged,
    required this.activity,
    required this.digest,
    required this.members,
    required this.aiSettings,
  });
  final DiagramData diagram;
  final List<ChatMessage> messages;
  final String channel;
  final ValueChanged<String> onChannelChanged;
  final List<ActivityItem> activity;
  final DiagramDigest? digest;
  final List<DiagramMember> members;
  final AiSettings? aiSettings;

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 4,
    child: Scaffold(
      appBar: AppBar(
        title: Text(diagram.title),
        bottom: const TabBar(
          tabs: [
            Tab(text: 'Modelo'),
            Tab(text: 'Conversación'),
            Tab(text: 'Bitácora'),
            Tab(text: 'Resumen'),
          ],
        ),
      ),
      body: TabBarView(
        children: [
          DiagramModelTab(diagram: diagram),
          ChatReadOnlyTab(
            messages: messages,
            channel: channel,
            onChannelChanged: onChannelChanged,
          ),
          ActivityReadOnlyTab(items: activity),
          SummaryReadOnlyTab(
            digest: digest,
            members: members,
            aiSettings: aiSettings,
          ),
        ],
      ),
    ),
  );
}

class _ClassCard extends StatelessWidget {
  const _ClassCard({required this.item});
  final DiagramClass item;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  item.name,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              if (item.isAssociation) const _Tag(label: 'CLASE DE ASOCIACIÓN'),
            ],
          ),
          if (item.attributes.isNotEmpty) ...[
            const SizedBox(height: 12),
            const _MiniLabel('ATRIBUTOS'),
            const SizedBox(height: 4),
            ...item.attributes.map(
              (attribute) => Text(
                '${attribute.name}: ${attribute.type}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
          ],
          if (item.methods.isNotEmpty) ...[
            const SizedBox(height: 12),
            const _MiniLabel('MÉTODOS'),
            const SizedBox(height: 4),
            ...item.methods.map(
              (method) => Text(
                '${method.name}(): ${method.type}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
          ],
        ],
      ),
    ),
  );
}

class _RelationCard extends StatelessWidget {
  const _RelationCard({required this.relation});
  final DiagramRelation relation;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Text(
              relation.from,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 7),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  relation.type,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.secondary,
                  ),
                ),
                const Icon(Icons.arrow_forward, size: 17),
              ],
            ),
          ),
          Expanded(
            child: Text(
              relation.to,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (relation.sourceMultiplicity != null ||
              relation.targetMultiplicity != null)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Text(
                '${relation.sourceMultiplicity ?? ''} · ${relation.targetMultiplicity ?? ''}',
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
        ],
      ),
    ),
  );
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({required this.message});
  final ChatMessage message;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  message.authorKind == 'ai'
                      ? 'Asistente'
                      : message.authorName ?? 'Usuario eliminado',
                  style: Theme.of(
                    context,
                  ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              Text(
                _formatDate(message.createdAt),
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            message.content,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(height: 1.45),
          ),
        ],
      ),
    ),
  );
}

class _ActivityCard extends StatelessWidget {
  const _ActivityCard({required this.item});
  final ActivityItem item;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 9),
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              item.actorKind == 'ai'
                  ? Icons.auto_awesome_outlined
                  : Icons.circle_outlined,
              size: 19,
              color: Theme.of(context).colorScheme.secondary,
            ),
            const SizedBox(width: 11),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.summary,
                    style: Theme.of(
                      context,
                    ).textTheme.bodyMedium?.copyWith(height: 1.35),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '${item.actorKind == 'ai' ? 'IA' : item.actorName ?? 'Usuario eliminado'} · ${_formatDate(item.createdAt)}',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class _DigestCard extends StatelessWidget {
  const _DigestCard({required this.digest});
  final DiagramDigest digest;
  @override
  Widget build(BuildContext context) {
    final actors = digest.byActor.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${digest.activityTotal} cambios · ${digest.chatTotal} mensajes',
              style: Theme.of(
                context,
              ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            if (actors.isNotEmpty) ...[
              const SizedBox(height: 5),
              Text(
                actors
                    .map((entry) => '${entry.key} (${entry.value})')
                    .join(' · '),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            if (digest.activity.isNotEmpty) ...[
              const SizedBox(height: 12),
              ...digest.activity
                  .take(8)
                  .map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(bottom: 7),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('•  '),
                          Expanded(
                            child: Text(
                              item.summary,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
            ],
            if (digest.since == null) ...[
              const SizedBox(height: 8),
              Text(
                'No hay una visita anterior registrada.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _MemberCard extends StatelessWidget {
  const _MemberCard({required this.member});
  final DiagramMember member;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 7),
    child: Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: Theme.of(context).colorScheme.primaryContainer,
          child: Text(member.name.isEmpty ? '?' : member.name[0].toUpperCase()),
        ),
        title: Text(member.name),
        subtitle: Text(member.email),
        trailing: Text(
          member.isOwner ? 'Propietario' : member.role,
          style: Theme.of(context).textTheme.labelSmall,
        ),
      ),
    ),
  );
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.tint,
  });
  final IconData icon;
  final String title;
  final String subtitle;
  final Color tint;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: tint,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: ObserverTheme.amber),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 3),
                Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class _RealtimeStrip extends StatelessWidget {
  const _RealtimeStrip({required this.status});
  final RealtimeStatus status;
  @override
  Widget build(BuildContext context) {
    final connected = status == RealtimeStatus.connected;
    final label = switch (status) {
      RealtimeStatus.connected => 'En vivo',
      RealtimeStatus.connecting => 'Conectando…',
      RealtimeStatus.reconnecting => 'Reconectando…',
      RealtimeStatus.disconnected => 'Tiempo real desconectado',
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 8, 18, 4),
      child: Row(
        children: [
          Icon(
            Icons.circle,
            size: 9,
            color: connected ? ObserverTheme.green : ObserverTheme.amber,
          ),
          const SizedBox(width: 8),
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          const Spacer(),
          Text(
            'SOLO LECTURA',
            style: Theme.of(
              context,
            ).textTheme.labelSmall?.copyWith(letterSpacing: 1.1),
          ),
        ],
      ),
    );
  }
}

class _ThinkingStrip extends StatelessWidget {
  const _ThinkingStrip({this.requester});
  final String? requester;
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
    decoration: BoxDecoration(
      color: const Color(0xFFFFF1D9),
      borderRadius: BorderRadius.circular(11),
    ),
    child: Text(
      requester == null
          ? 'La IA está respondiendo…'
          : 'La IA está respondiendo a $requester…',
      style: Theme.of(context).textTheme.labelMedium,
    ),
  );
}

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({required this.title, this.count});
  final String title;
  final int? count;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Text(
        title,
        style: Theme.of(
          context,
        ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
      ),
      if (count != null) ...[
        const SizedBox(width: 8),
        Text(
          '$count',
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    ],
  );
}

class _MiniLabel extends StatelessWidget {
  const _MiniLabel(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Text(
    text,
    style: Theme.of(context).textTheme.labelSmall?.copyWith(
      fontWeight: FontWeight.w700,
      letterSpacing: 1.1,
      color: Theme.of(context).colorScheme.secondary,
    ),
  );
}

class _Tag extends StatelessWidget {
  const _Tag({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.primaryContainer,
      borderRadius: BorderRadius.circular(7),
    ),
    child: Text(
      label,
      style: Theme.of(context).textTheme.labelSmall?.copyWith(
        fontSize: 9,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class _EmptyNote extends StatelessWidget {
  const _EmptyNote(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(18),
    child: Text(
      text,
      textAlign: TextAlign.center,
      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
    ),
  );
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.cloud_off_outlined,
            size: 34,
            color: Theme.of(context).colorScheme.secondary,
          ),
          const SizedBox(height: 12),
          Text(message, textAlign: TextAlign.center),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Reintentar'),
          ),
        ],
      ),
    ),
  );
}

String _formatDate(DateTime? value) {
  if (value == null) return '';
  final date = value.toLocal();
  return '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')} '
      '${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
}
