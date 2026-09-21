class UapTool {
  const UapTool(this.raw);
  final Map<String, dynamic> raw;
  String get id => raw['id']?.toString() ?? '';
  String get name => raw['name']?.toString() ?? id;
  String get operation => raw['operation']?.toString() ?? '';
  String get method => raw['method']?.toString() ?? '';
  String get path => raw['path']?.toString() ?? '';
  bool get requiresConfirmation => raw['requiresConfirmation'] == true;
  bool get isWrite => raw['sideEffects'] == true;
  Map<String, dynamic> get inputSchema =>
      (raw['inputSchema'] as Map?)?.cast<String, dynamic>() ?? {};
}

class UapSnapshot {
  const UapSnapshot({
    required this.manifest,
    required this.schema,
    required this.tools,
    required this.permissions,
    required this.businessRules,
  });
  final Map<String, dynamic> manifest;
  final Map<String, dynamic> schema;
  final Map<String, dynamic> tools;
  final Map<String, dynamic> permissions;
  final Map<String, dynamic> businessRules;

  List<UapTool> get toolList => ((tools['tools'] as List?) ?? const [])
      .whereType<Map>()
      .map((item) => UapTool(item.cast<String, dynamic>()))
      .toList();

  Map<String, dynamic> toJson() => {
    'manifest': manifest,
    'schema': schema,
    'tools': tools,
    'permissions': permissions,
    'businessRules': businessRules,
  };

  factory UapSnapshot.fromJson(Map<String, dynamic> json) => UapSnapshot(
    manifest: (json['manifest'] as Map? ?? const {}).cast<String, dynamic>(),
    schema: (json['schema'] as Map? ?? const {}).cast<String, dynamic>(),
    tools: (json['tools'] as Map? ?? const {}).cast<String, dynamic>(),
    permissions: (json['permissions'] as Map? ?? const {}).cast<String, dynamic>(),
    businessRules: (json['businessRules'] as Map? ?? const {}).cast<String, dynamic>(),
  );

  static const empty = UapSnapshot(
    manifest: {}, schema: {}, tools: {}, permissions: {}, businessRules: {},
  );
}
