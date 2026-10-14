import 'package:shared_preferences/shared_preferences.dart';

import '../core/url.dart';
import 'api_config.dart';

const backendUrlOverrideKey = 'backend_url_override';

Future<String?> loadBackendUrlOverride() async {
  final value = (await SharedPreferences.getInstance())
      .getString(backendUrlOverrideKey)
      ?.trim();
  if (value == null || value.isEmpty) return null;
  try {
    return normalizeBaseUrl(value);
  } on FormatException {
    return null;
  }
}

Future<String> resolveBackendUrl() async =>
    await loadBackendUrlOverride() ?? normalizeBaseUrl(activeBackendUrl);

Future<void> saveBackendUrlOverride(String value) async {
  final normalized = normalizeBaseUrl(value);
  await (await SharedPreferences.getInstance()).setString(
    backendUrlOverrideKey,
    normalized,
  );
}

Future<void> clearBackendUrlOverride() async {
  await (await SharedPreferences.getInstance()).remove(backendUrlOverrideKey);
}
