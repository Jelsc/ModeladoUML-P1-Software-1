import 'package:flutter/material.dart';

import '../data/push_notifications.dart';
import '../data/team_api.dart';
import '../models/team_models.dart';
import 'diagram_screen.dart';

class DiagramListScreen extends StatefulWidget {
  const DiagramListScreen({
    super.key,
    required this.api,
    required this.user,
    required this.pushAvailability,
    required this.onSignOut,
    required this.onUnauthorized,
  });

  final TeamApi api;
  final TeamUser user;
  final PushAvailability pushAvailability;
  final VoidCallback onSignOut;
  final VoidCallback onUnauthorized;

  @override
  State<DiagramListScreen> createState() => _DiagramListScreenState();
}

class _DiagramListScreenState extends State<DiagramListScreen> {
  List<DiagramSummary> _diagrams = const [];
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
      final result = await widget.api.diagrams(refresh: refresh);
      if (mounted) {
        setState(() {
          _diagrams = result;
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
    } catch (error) {
      if (mounted) {
        setState(() {
          _error =
              'No se pudo conectar con el servidor. Revise la URL e intente nuevamente.';
          _loading = false;
        });
      }
    }
  }

  void _open(DiagramSummary diagram) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ObserverDiagramScreen(
          api: widget.api,
          summary: diagram,
          onUnauthorized: widget.onUnauthorized,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Equipo'),
        actions: [
          IconButton(
            tooltip: 'Actualizar diagramas',
            onPressed: () => _load(refresh: true),
            icon: const Icon(Icons.refresh),
          ),
          PopupMenuButton<String>(
            onSelected: (value) {
              if (value == 'logout') widget.onSignOut();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'logout', child: Text('Cerrar sesión')),
            ],
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _load(refresh: true),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
          children: [
            Text(
              'Hola, ${widget.user.name}',
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Una vista tranquila de lo que está pasando en tus equipos.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 18),
            _LivePill(
              label: pushAvailabilityLabel(widget.pushAvailability),
              ready: widget.pushAvailability == PushAvailability.ready,
            ),
            const SizedBox(height: 22),
            if (_loading && _diagrams.isEmpty)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(30),
                  child: CircularProgressIndicator(),
                ),
              )
            else if (_error != null)
              _StateCard(
                icon: Icons.cloud_off_outlined,
                title: 'No se pudo cargar',
                message: _error!,
                action: TextButton.icon(
                  onPressed: () => _load(refresh: true),
                  icon: const Icon(Icons.refresh),
                  label: const Text('Reintentar'),
                ),
              )
            else if (_diagrams.isEmpty)
              const _StateCard(
                icon: Icons.dashboard_outlined,
                title: 'Todavía no hay diagramas',
                message:
                    'Solicite al propietario que comparta un diagrama desde la web.',
              )
            else ...[
              Row(
                children: [
                  Text(
                    'DIAGRAMAS',
                    style: theme.textTheme.labelSmall?.copyWith(
                      letterSpacing: 1.4,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${_diagrams.length}',
                    style: theme.textTheme.labelMedium?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              ..._diagrams.map(
                (diagram) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _DiagramCard(
                    diagram: diagram,
                    onTap: () => _open(diagram),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _DiagramCard extends StatelessWidget {
  const _DiagramCard({required this.diagram, required this.onTap});
  final DiagramSummary diagram;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final role = diagram.isOwner
        ? 'Propietario'
        : (diagram.memberRole ?? 'Miembro');
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primaryContainer,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(
                  Icons.account_tree_outlined,
                  color: Theme.of(context).colorScheme.primary,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      diagram.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '$role · ${_updatedLabel(diagram.updatedAt)}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }

  String _updatedLabel(DateTime? date) {
    if (date == null) return 'sin fecha de actualización';
    final local = date.toLocal();
    return 'actualizado ${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}';
  }
}

class _LivePill extends StatelessWidget {
  const _LivePill({required this.label, required this.ready});
  final String label;
  final bool ready;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surface,
      borderRadius: BorderRadius.circular(99),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          ready
              ? Icons.notifications_active_outlined
              : Icons.notifications_none_outlined,
          size: 16,
          color: ready
              ? const Color(0xFF477D68)
              : Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        const SizedBox(width: 8),
        Flexible(
          child: Text(label, style: Theme.of(context).textTheme.labelSmall),
        ),
      ],
    ),
  );
}

class _StateCard extends StatelessWidget {
  const _StateCard({
    required this.icon,
    required this.title,
    required this.message,
    this.action,
  });
  final IconData icon;
  final String title;
  final String message;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: Theme.of(context).colorScheme.secondary),
          const SizedBox(height: 12),
          Text(
            title,
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          Text(message, style: Theme.of(context).textTheme.bodyMedium),
          if (action != null) ...[const SizedBox(height: 6), action!],
        ],
      ),
    ),
  );
}
