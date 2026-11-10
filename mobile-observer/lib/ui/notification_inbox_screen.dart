import 'package:flutter/material.dart';

import '../data/team_api.dart';
import '../models/team_models.dart';

class NotificationInboxScreen extends StatefulWidget {
  const NotificationInboxScreen({
    super.key,
    required this.api,
    required this.onUnauthorized,
    required this.onOpenDiagram,
  });
  final TeamApi api;
  final VoidCallback onUnauthorized;
  final ValueChanged<InboxNotification> onOpenDiagram;

  @override
  State<NotificationInboxScreen> createState() =>
      _NotificationInboxScreenState();
}

class _NotificationInboxScreenState extends State<NotificationInboxScreen> {
  List<InboxNotification> _items = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool refresh = false}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.api.notificationInbox(refresh: refresh);
      if (mounted) {
        setState(() {
          _items = items;
          _loading = false;
        });
      }
    } on ApiFailure catch (error) {
      if (error.unauthorized) widget.onUnauthorized();
      if (mounted) {
        setState(() {
          _error = error.message;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = 'No se pudieron cargar las notificaciones.';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Notificaciones'),
      actions: [
        IconButton(
          tooltip: 'Actualizar notificaciones',
          onPressed: () => _load(refresh: true),
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: RefreshIndicator(
      onRefresh: () => _load(refresh: true),
      child: _loading && _items.isEmpty
          ? ListView(
              children: const [
                Padding(
                  padding: EdgeInsets.all(48),
                  child: Center(child: CircularProgressIndicator()),
                ),
              ],
            )
          : _error != null && _items.isEmpty
          ? ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    children: [
                      Text(_error!),
                      TextButton.icon(
                        onPressed: () => _load(refresh: true),
                        icon: const Icon(Icons.refresh),
                        label: const Text('Reintentar'),
                      ),
                    ],
                  ),
                ),
              ],
            )
          : _items.isEmpty
          ? ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: const [
                Padding(
                  padding: EdgeInsets.all(48),
                  child: Center(child: Text('Todavía no hay actividad nueva.')),
                ),
              ],
            )
          : ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: _items.length,
              separatorBuilder: (_, _) => const Divider(height: 1, indent: 72),
              itemBuilder: (context, index) {
                final item = _items[index];
                return ListTile(
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 8,
                  ),
                  leading: const CircleAvatar(
                    child: Icon(Icons.notifications_none),
                  ),
                  title: Text(
                    _eventLabel(item.event),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  subtitle: Text(
                    '${item.diagramTitle}\n${item.body}',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  isThreeLine: true,
                  trailing: item.createdAt == null
                      ? null
                      : Text(
                          _timeLabel(item.createdAt!),
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                  onTap: () => widget.onOpenDiagram(item),
                );
              },
            ),
    ),
  );

  String _eventLabel(String event) => switch (event) {
    'chat.message' => 'Nuevo mensaje',
    'class.created' => 'Clase agregada',
    'class.updated' => 'Clase actualizada',
    'class.deleted' => 'Clase eliminada',
    'relation.created' => 'Relación agregada',
    'relation.updated' => 'Relación actualizada',
    'relation.deleted' => 'Relación eliminada',
    'diagram.xmi_imported' => 'Diagrama importado',
    'ai.done' || 'ai.endpoints' => 'Asistencia completada',
    'ai.error' => 'Asistencia con error',
    _ => 'Actualización del equipo',
  };
  String _timeLabel(DateTime value) {
    final local = value.toLocal();
    final now = DateTime.now();
    return local.year == now.year &&
            local.month == now.month &&
            local.day == now.day
        ? '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}'
        : '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}';
  }
}
