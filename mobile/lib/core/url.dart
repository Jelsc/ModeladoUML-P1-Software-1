String normalizeBaseUrl(String value) {
  var url = value.trim();
  if (url.isEmpty) throw const FormatException('Ingresá una URL de backend.');
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    url = 'http://$url';
  }
  final parsed = Uri.tryParse(url);
  if (parsed == null || parsed.host.isEmpty) {
    throw const FormatException('Ingresá una URL de backend válida.');
  }
  return url.replaceFirst(RegExp(r'/+$'), '');
}
