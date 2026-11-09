import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

abstract interface class ObserverSessionStore {
  Future<String?> readToken();
  Future<void> writeToken(String token);
  Future<void> clearToken();
  Future<String?> readServerUrl();
  Future<void> writeServerUrl(String value);
}

class SecureObserverSessionStore implements ObserverSessionStore {
  SecureObserverSessionStore({FlutterSecureStorage? secureStorage})
    : _secureStorage = secureStorage ?? const FlutterSecureStorage();

  static const _tokenKey = 'observer.session.token';
  static const _serverUrlKey = 'observer.server.url';
  final FlutterSecureStorage _secureStorage;

  @override
  Future<String?> readToken() => _secureStorage.read(key: _tokenKey);

  @override
  Future<void> writeToken(String token) =>
      _secureStorage.write(key: _tokenKey, value: token);

  @override
  Future<void> clearToken() => _secureStorage.delete(key: _tokenKey);

  @override
  Future<String?> readServerUrl() async =>
      (await SharedPreferences.getInstance()).getString(_serverUrlKey);

  @override
  Future<void> writeServerUrl(String value) async {
    await (await SharedPreferences.getInstance()).setString(
      _serverUrlKey,
      value,
    );
  }
}
