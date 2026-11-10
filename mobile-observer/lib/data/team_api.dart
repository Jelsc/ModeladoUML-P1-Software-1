import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/team_models.dart';

const chatChannels = {'diseno', 'desarrollo', 'test'};

class ApiFailure implements Exception {
  const ApiFailure(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  bool get unauthorized => statusCode == 401;

  @override
  String toString() => message;
}

class BackendFeaturePending implements Exception {
  const BackendFeaturePending(this.feature);
  final String feature;

  @override
  String toString() =>
      '$feature: el endpoint del backend aún no está disponible.';
}

abstract interface class DeviceTokenRegistrationContract {
  Future<void> registerDeviceToken(DeviceTokenRegistration registration);
  Future<void> unregisterDeviceToken(DeviceTokenRegistration registration);
}

class TeamApi implements DeviceTokenRegistrationContract {
  TeamApi({required String baseUrl, http.Client? client})
    : _baseUrl = normalizeBaseUrl(baseUrl),
      _client = client ?? http.Client();

  final http.Client _client;
  String _baseUrl;
  String? _token;
  final Map<String, _CachedGet> _getCache = {};

  String get baseUrl => _baseUrl;
  String? get token => _token;

  void changeBaseUrl(String value) {
    final next = normalizeBaseUrl(value);
    if (next != _baseUrl) {
      _baseUrl = next;
      _getCache.clear();
    }
  }

  void useToken(String? value) {
    if (_token != value) _getCache.clear();
    _token = value;
  }

  Uri endpoint(String path, {Map<String, String>? queryParameters}) {
    final relative = path.startsWith('/') ? path.substring(1) : path;
    final uri = Uri.parse('$_baseUrl/').resolve(relative);
    return queryParameters == null
        ? uri
        : uri.replace(queryParameters: queryParameters);
  }

  Uri websocketEndpoint(String path) {
    final uri = endpoint(path);
    return uri.replace(
      scheme: uri.scheme == 'https' ? 'wss' : 'ws',
      queryParameters: {'token': _token ?? ''},
    );
  }

  Future<({String token, TeamUser user})> signIn(
    String email,
    String password,
  ) async {
    final response = await _client.post(
      endpoint('auth/sign-in'),
      headers: const {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: jsonEncode({'email': email, 'password': password}),
    );
    final body = _decodeObject(response);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw _failure(response, body);
    }
    final accessToken = body['access_token'];
    if (accessToken is! String || accessToken.isEmpty) {
      throw const ApiFailure(
        'La respuesta de inicio de sesión no contiene un token válido.',
      );
    }
    useToken(accessToken);
    return (
      token: accessToken,
      user: TeamUser.fromJson(_asObject(body['user'])),
    );
  }

  Future<TeamUser> me() async => TeamUser.fromJson(await _getObject('auth/me'));

  Future<List<DiagramSummary>> diagrams({bool refresh = false}) async =>
      _getList('diagrams', refresh: refresh).then(
        (items) => items.map(DiagramSummary.fromJson).toList(growable: false),
      );

  Future<List<InboxNotification>> notificationInbox({
    int limit = 50,
    bool refresh = false,
  }) async {
    if (limit < 1 || limit > 100) throw ArgumentError.value(limit, 'limit');
    return _getList(
      'notifications/inbox',
      query: {'limit': '$limit'},
      refresh: refresh,
    ).then(
      (items) => items.map(InboxNotification.fromJson).toList(growable: false),
    );
  }

  Future<DiagramData> diagram(String diagramId, {bool refresh = false}) async =>
      DiagramData.fromJson(
        await _getObject('diagrams/${_segment(diagramId)}', refresh: refresh),
      );

  Future<List<DiagramMember>> members(
    String diagramId, {
    bool refresh = false,
  }) async => _getList(
    'diagrams/${_segment(diagramId)}/members',
    refresh: refresh,
  ).then((items) => items.map(DiagramMember.fromJson).toList(growable: false));

  Future<List<ChatMessage>> chat(
    String diagramId, {
    String channel = 'diseno',
    int limit = 50,
    String? before,
    bool refresh = false,
  }) async {
    if (!chatChannels.contains(channel)) {
      throw ArgumentError.value(channel, 'channel');
    }
    final query = {'channel': channel, 'limit': '$limit'};
    if (before != null) query['before'] = before;
    final items = await _getList(
      'diagrams/${_segment(diagramId)}/chat',
      query: query,
      refresh: refresh,
    );
    return items.map(ChatMessage.fromJson).toList(growable: false);
  }

  Future<List<ActivityItem>> activity(
    String diagramId, {
    int limit = 50,
    String? before,
    bool refresh = false,
  }) async => _getList(
    'diagrams/${_segment(diagramId)}/activity',
    query: {'limit': '$limit', 'before': ?before},
    refresh: refresh,
  ).then((items) => items.map(ActivityItem.fromJson).toList(growable: false));

  Future<DiagramDigest> digest(
    String diagramId, {
    bool refresh = false,
  }) async => DiagramDigest.fromJson(
    await _getObject(
      'diagrams/${_segment(diagramId)}/digest',
      refresh: refresh,
    ),
  );

  Future<AiSettings> aiSettings(
    String diagramId, {
    bool refresh = false,
  }) async => AiSettings.fromJson(
    await _getObject(
      'diagrams/${_segment(diagramId)}/ai-settings',
      refresh: refresh,
    ),
  );

  @override
  Future<void> registerDeviceToken(DeviceTokenRegistration registration) async {
    await _deviceTokenRequest('POST', registration);
  }

  @override
  Future<void> unregisterDeviceToken(
    DeviceTokenRegistration registration,
  ) async {
    await _deviceTokenRequest('DELETE', registration);
  }

  Future<void> _deviceTokenRequest(
    String method,
    DeviceTokenRegistration registration,
  ) async {
    final bearer = _token;
    if (bearer == null || bearer.isEmpty) {
      throw const ApiFailure('Inicie sesión para continuar.', statusCode: 401);
    }
    final response = await (method == 'POST' ? _client.post : _client.delete)(
      endpoint('devices/fcm-token'),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': 'Bearer $bearer',
      },
      body: jsonEncode(registration.toJson()),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw _failure(response, _decode(response));
    }
  }

  void clearReadCache() => _getCache.clear();
  void close() => _client.close();

  Future<Map<String, dynamic>> _getObject(
    String path, {
    Map<String, String>? query,
    bool refresh = false,
  }) async {
    final value = await _get(path, query: query, refresh: refresh);
    return _asObject(value);
  }

  Future<List<Map<String, dynamic>>> _getList(
    String path, {
    Map<String, String>? query,
    bool refresh = false,
  }) async {
    final value = await _get(path, query: query, refresh: refresh);
    if (value is! List) {
      throw const ApiFailure('El servidor devolvió una respuesta inesperada.');
    }
    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList(growable: false);
  }

  Future<Object?> _get(
    String path, {
    Map<String, String>? query,
    required bool refresh,
  }) async {
    final bearer = _token;
    if (bearer == null || bearer.isEmpty) {
      throw const ApiFailure('Inicie sesión para continuar.', statusCode: 401);
    }
    final uri = endpoint(path, queryParameters: query);
    final key = uri.toString();
    final cached = _getCache[key];
    if (!refresh &&
        cached != null &&
        DateTime.now().difference(cached.savedAt) <
            const Duration(seconds: 15)) {
      return _copyJson(cached.value);
    }
    final response = await _client.get(
      uri,
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer $bearer',
      },
    );
    final decoded = _decode(response);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw _failure(response, decoded);
    }
    _getCache[key] = _CachedGet(decoded, DateTime.now());
    return _copyJson(decoded);
  }

  static String normalizeBaseUrl(String value) {
    final raw = value.trim();
    final uri = Uri.tryParse(raw);
    if (uri == null ||
        !uri.hasAuthority ||
        !{'http', 'https'}.contains(uri.scheme.toLowerCase()) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw const FormatException('Ingrese una URL http:// o https:// válida.');
    }
    final path = uri.path.replaceFirst(RegExp(r'/+$'), '');
    if (path.isNotEmpty && path != '/api') {
      throw const FormatException(
        'La URL debe apuntar al servidor o terminar en /api.',
      );
    }
    return uri
        .replace(scheme: uri.scheme.toLowerCase(), path: path)
        .toString()
        .replaceFirst(RegExp(r'/+$'), '');
  }

  static String _segment(String value) => Uri.encodeComponent(value);

  static Object? _decode(http.Response response) {
    if (response.body.isEmpty) return null;
    try {
      return jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      return response.body;
    }
  }

  static Map<String, dynamic> _decodeObject(http.Response response) =>
      _asObject(_decode(response));

  static Map<String, dynamic> _asObject(Object? value) =>
      value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};

  static Object? _copyJson(Object? value) =>
      value == null ? null : jsonDecode(jsonEncode(value));

  static ApiFailure _failure(http.Response response, Object? body) {
    final detail = body is Map ? body['detail'] : null;
    final message = detail is String && detail.trim().isNotEmpty
        ? detail
        : response.statusCode == 401
        ? 'La sesión venció. Inicie sesión nuevamente.'
        : 'No se pudo completar la consulta (HTTP ${response.statusCode}).';
    return ApiFailure(message, statusCode: response.statusCode);
  }
}

class _CachedGet {
  const _CachedGet(this.value, this.savedAt);
  final Object? value;
  final DateTime savedAt;
}
