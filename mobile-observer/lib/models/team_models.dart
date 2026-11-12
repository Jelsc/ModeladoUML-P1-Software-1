class TeamUser {
  const TeamUser({
    required this.id,
    required this.email,
    required this.name,
    required this.role,
    required this.active,
  });

  final int id;
  final String email;
  final String name;
  final String role;
  final bool active;

  factory TeamUser.fromJson(Map<String, dynamic> json) => TeamUser(
    id: _integer(json['id']),
    email: _string(json['email']),
    name: _string(json['name'], fallback: 'Usuario'),
    role: _string(json['role'], fallback: 'viewer'),
    active: json['active'] != false,
  );
}

class DiagramSummary {
  const DiagramSummary({
    required this.id,
    required this.title,
    this.updatedAt,
    required this.isOwner,
    this.memberRole,
  });

  final String id;
  final String title;
  final DateTime? updatedAt;
  final bool isOwner;
  final String? memberRole;

  factory DiagramSummary.fromJson(Map<String, dynamic> json) => DiagramSummary(
    id: _string(json['id']),
    title: _string(json['title'], fallback: 'Diagrama sin título'),
    updatedAt: _date(json['updated_at']),
    isOwner: json['is_owner'] == true,
    memberRole: _nullableString(json['member_role']),
  );
}

class DiagramAttribute {
  const DiagramAttribute({
    required this.id,
    required this.name,
    required this.type,
  });
  final String id;
  final String name;
  final String type;

  factory DiagramAttribute.fromJson(Map<String, dynamic> json) =>
      DiagramAttribute(
        id: _string(json['id']),
        name: _string(json['name']),
        type: _string(json['type'], fallback: 'string'),
      );
}

class DiagramMethod {
  const DiagramMethod({
    required this.id,
    required this.name,
    required this.type,
  });
  final String id;
  final String name;
  final String type;

  factory DiagramMethod.fromJson(Map<String, dynamic> json) => DiagramMethod(
    id: _string(json['id']),
    name: _string(json['name']),
    type: _string(json['type'], fallback: 'void'),
  );
}

class DiagramClass {
  const DiagramClass({
    required this.id,
    required this.name,
    required this.x,
    required this.y,
    required this.isAssociation,
    required this.attributes,
    required this.methods,
  });

  final String id;
  final String name;
  final int x;
  final int y;
  final bool isAssociation;
  final List<DiagramAttribute> attributes;
  final List<DiagramMethod> methods;

  factory DiagramClass.fromJson(Map<String, dynamic> json) => DiagramClass(
    id: _string(json['id']),
    name: _string(json['name'], fallback: 'Clase'),
    x: _integer(json['x']),
    y: _integer(json['y']),
    isAssociation: json['is_association'] == true,
    attributes: _objects(
      json['attributes'],
    ).map(DiagramAttribute.fromJson).toList(growable: false),
    methods: _objects(
      json['methods'],
    ).map(DiagramMethod.fromJson).toList(growable: false),
  );
}

class DiagramRelation {
  const DiagramRelation({
    required this.id,
    required this.sourceId,
    required this.targetId,
    required this.from,
    required this.to,
    required this.type,
    this.label,
    this.sourceMultiplicity,
    this.targetMultiplicity,
    this.associationClassId,
  });

  final String id;
  final String sourceId;
  final String targetId;
  final String from;
  final String to;
  final String type;
  final String? label;
  final String? sourceMultiplicity;
  final String? targetMultiplicity;
  final String? associationClassId;

  factory DiagramRelation.fromJson(Map<String, dynamic> json) =>
      DiagramRelation(
        id: _string(json['id']),
        sourceId: _string(json['source_id']),
        targetId: _string(json['target_id']),
        from: _string(json['from'], fallback: 'Clase'),
        to: _string(json['to'], fallback: 'Clase'),
        type: _string(json['type'], fallback: 'association'),
        label: _nullableString(json['label']),
        sourceMultiplicity: _nullableString(json['source_multiplicity']),
        targetMultiplicity: _nullableString(json['target_multiplicity']),
        associationClassId: _nullableString(json['association_class_id']),
      );
}

class VisionProposal {
  const VisionProposal({
    required this.projectName,
    required this.classes,
    required this.relations,
    required this.warnings,
  });
  final String projectName;
  final List<VisionClass> classes;
  final List<VisionRelation> relations;
  final List<String> warnings;
  factory VisionProposal.fromJson(Map<String, dynamic> json) => VisionProposal(
    projectName: _string(json['project_name'], fallback: 'Diagrama importado'),
    classes: _objects(json['classes']).map(VisionClass.fromJson).toList(),
    relations: _objects(
      json['relations'],
    ).map(VisionRelation.fromJson).toList(),
    warnings: (json['warnings'] as List? ?? const [])
        .whereType<String>()
        .toList(),
  );
  Map<String, dynamic> toJson() => {
    'project_name': projectName,
    'classes': classes.map((value) => value.toJson()).toList(),
    'relations': relations.map((value) => value.toJson()).toList(),
    'warnings': warnings,
  };
}

class VisionClass {
  const VisionClass({
    required this.id,
    required this.name,
    required this.selected,
    required this.attributes,
    required this.methods,
  });
  final String id, name;
  final bool selected;
  final List<VisionAttribute> attributes;
  final List<VisionMethod> methods;
  factory VisionClass.fromJson(Map<String, dynamic> json) => VisionClass(
    id: _string(json['id']),
    name: _string(json['name']),
    selected: json['selected'] != false,
    attributes: _objects(
      json['attributes'],
    ).map(VisionAttribute.fromJson).toList(),
    methods: _objects(json['methods']).map(VisionMethod.fromJson).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'selected': selected,
    'attributes': attributes.map((e) => e.toJson()).toList(),
    'methods': methods.map((e) => e.toJson()).toList(),
  };
}

class VisionAttribute {
  const VisionAttribute({
    required this.id,
    required this.name,
    required this.type,
    required this.selected,
  });
  final String id, name, type;
  final bool selected;
  factory VisionAttribute.fromJson(Map<String, dynamic> j) => VisionAttribute(
    id: _string(j['id']),
    name: _string(j['name']),
    type: _string(j['type'], fallback: 'string'),
    selected: j['selected'] != false,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'type': type,
    'selected': selected,
  };
}

class VisionMethod {
  const VisionMethod({
    required this.id,
    required this.name,
    required this.returnType,
    required this.selected,
  });
  final String id, name, returnType;
  final bool selected;
  factory VisionMethod.fromJson(Map<String, dynamic> j) => VisionMethod(
    id: _string(j['id']),
    name: _string(j['name']),
    returnType: _string(j['return_type'], fallback: 'void'),
    selected: j['selected'] != false,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'return_type': returnType,
    'selected': selected,
  };
}

class VisionRelation {
  const VisionRelation({
    required this.id,
    required this.sourceId,
    required this.targetId,
    required this.source,
    required this.target,
    required this.type,
    this.label,
    this.sourceMultiplicity,
    this.targetMultiplicity,
    this.associationClass,
    this.associationClassId = '',
    required this.selected,
  });
  final String id, sourceId, targetId, source, target, type;
  final String? label, sourceMultiplicity, targetMultiplicity;
  final String? associationClass;
  final String associationClassId;
  final bool selected;
  factory VisionRelation.fromJson(Map<String, dynamic> j) => VisionRelation(
    id: _string(j['id']),
    sourceId: _string(j['source_id']),
    targetId: _string(j['target_id']),
    source: _string(j['source'], fallback: 'Clase'),
    target: _string(j['target'], fallback: 'Clase'),
    type: _string(j['type'], fallback: 'association'),
    label: _nullableString(j['label']),
    sourceMultiplicity: _nullableString(j['source_multiplicity']),
    targetMultiplicity: _nullableString(j['target_multiplicity']),
    associationClass: _nullableString(j['association_class']),
    associationClassId: _string(j['association_class_id']),
    selected: j['selected'] != false,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'source_id': sourceId,
    'target_id': targetId,
    'source': source,
    'target': target,
    'type': type,
    'label': label,
    'source_multiplicity': sourceMultiplicity,
    'target_multiplicity': targetMultiplicity,
    'association_class': associationClass,
    'association_class_id': associationClassId,
    'selected': selected,
  };
}

class DiagramData {
  const DiagramData({
    required this.id,
    required this.title,
    required this.classes,
    required this.relations,
  });
  final String id;
  final String title;
  final List<DiagramClass> classes;
  final List<DiagramRelation> relations;

  factory DiagramData.fromJson(Map<String, dynamic> json) => DiagramData(
    id: _string(json['id']),
    title: _string(json['title'], fallback: 'Diagrama sin título'),
    classes: _objects(
      json['classes'],
    ).map(DiagramClass.fromJson).toList(growable: false),
    relations: _objects(
      json['relations'],
    ).map(DiagramRelation.fromJson).toList(growable: false),
  );
}

class InboxNotification {
  const InboxNotification({
    required this.id,
    required this.event,
    required this.diagramId,
    required this.diagramTitle,
    required this.title,
    required this.body,
    required this.createdAt,
  });
  final String id, event, diagramId, diagramTitle, title, body;
  final DateTime? createdAt;

  factory InboxNotification.fromJson(Map<String, dynamic> json) =>
      InboxNotification(
        id: _string(json['id']),
        event: _string(json['event']),
        diagramId: _string(json['diagram_id']),
        diagramTitle: _string(
          json['diagram_title'],
          fallback: 'Diagrama sin título',
        ),
        title: _string(json['title'], fallback: 'Actualización del equipo'),
        body: _string(
          json['body'],
          fallback: 'Hay nueva actividad en un diagrama.',
        ),
        createdAt: json['created_at'] == null
            ? null
            : _date(json['created_at']),
      );
}

class DiagramMember {
  const DiagramMember({
    required this.id,
    required this.email,
    required this.name,
    required this.role,
    required this.isOwner,
  });
  final String id;
  final String email;
  final String name;
  final String role;
  final bool isOwner;

  factory DiagramMember.fromJson(Map<String, dynamic> json) => DiagramMember(
    id: _string(json['id']),
    email: _string(json['email']),
    name: _string(json['name'], fallback: 'Usuario'),
    role: _string(json['role'], fallback: 'viewer'),
    isOwner: json['is_owner'] == true,
  );
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.diagramId,
    this.authorUserId,
    this.authorName,
    required this.authorKind,
    required this.content,
    this.replyToId,
    required this.channel,
    this.createdAt,
    this.image,
  });
  final String id;
  final String diagramId;
  final int? authorUserId;
  final String? authorName;
  final String authorKind;
  final String content;
  final String? replyToId;
  final String channel;
  final DateTime? createdAt;
  final ChatImageMetadata? image;

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
    id: _string(json['id']),
    diagramId: _string(json['diagram_id']),
    authorUserId: json['author_user_id'] == null
        ? null
        : _integer(json['author_user_id']),
    authorName: _nullableString(json['author_name']),
    authorKind: _string(json['author_kind'], fallback: 'user'),
    content: _string(json['content']),
    replyToId: _nullableString(json['reply_to_id']),
    channel: _string(json['channel'], fallback: 'diseno'),
    createdAt: _date(json['created_at']),
    image: json['image'] is Map
        ? ChatImageMetadata.fromJson(
            Map<String, dynamic>.from(json['image'] as Map),
          )
        : null,
  );
}

class ChatImageMetadata {
  const ChatImageMetadata({required this.id, this.name});
  final String id;
  final String? name;

  factory ChatImageMetadata.fromJson(Map<String, dynamic> json) =>
      ChatImageMetadata(
        id: _string(json['id']),
        name: _nullableString(json['name']),
      );
}

class ActivityItem {
  const ActivityItem({
    required this.id,
    required this.diagramId,
    this.actorUserId,
    this.actorName,
    required this.actorKind,
    required this.action,
    required this.entityType,
    this.entityId,
    required this.summary,
    this.createdAt,
  });
  final String id;
  final String diagramId;
  final int? actorUserId;
  final String? actorName;
  final String actorKind;
  final String action;
  final String entityType;
  final String? entityId;
  final String summary;
  final DateTime? createdAt;

  factory ActivityItem.fromJson(Map<String, dynamic> json) => ActivityItem(
    id: _string(json['id']),
    diagramId: _string(json['diagram_id']),
    actorUserId: json['actor_user_id'] == null
        ? null
        : _integer(json['actor_user_id']),
    actorName: _nullableString(json['actor_name']),
    actorKind: _string(json['actor_kind'], fallback: 'user'),
    action: _string(json['action']),
    entityType: _string(json['entity_type']),
    entityId: _nullableString(json['entity_id']),
    summary: _string(json['summary']),
    createdAt: _date(json['created_at']),
  );
}

class DiagramDigest {
  const DiagramDigest({
    this.since,
    required this.activity,
    required this.activityTotal,
    required this.chatTotal,
    required this.byActor,
  });
  final DateTime? since;
  final List<ActivityItem> activity;
  final int activityTotal;
  final int chatTotal;
  final Map<String, int> byActor;

  factory DiagramDigest.fromJson(Map<String, dynamic> json) => DiagramDigest(
    since: _date(json['since']),
    activity: _objects(
      json['activity'],
    ).map(ActivityItem.fromJson).toList(growable: false),
    activityTotal: _integer(json['activity_total']),
    chatTotal: _integer(json['chat_total']),
    byActor: _integerMap(json['by_actor']),
  );
}

class AiSettings {
  const AiSettings({required this.enabled, required this.canEdit});
  final bool enabled;
  final bool canEdit;

  factory AiSettings.fromJson(Map<String, dynamic> json) => AiSettings(
    enabled: json['ai_enabled'] == true,
    canEdit: json['ai_can_edit'] == true,
  );
}

class DeviceTokenRegistration {
  const DeviceTokenRegistration({required this.token, required this.platform});
  final String token;
  final String platform;

  Map<String, String> toJson() => {'token': token, 'platform': platform};
}

List<Map<String, dynamic>> _objects(dynamic value) => value is List
    ? value
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList(growable: false)
    : const [];
Map<String, int> _integerMap(dynamic value) => value is Map
    ? value.map((key, item) => MapEntry(key.toString(), _integer(item)))
    : const {};
String _string(dynamic value, {String fallback = ''}) =>
    value is String ? value : fallback;
String? _nullableString(dynamic value) => value is String ? value : null;
int _integer(dynamic value) =>
    value is int ? value : int.tryParse(value?.toString() ?? '') ?? 0;
DateTime? _date(dynamic value) =>
    value is String ? DateTime.tryParse(value) : null;
