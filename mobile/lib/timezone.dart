/// Bolivia uses America/La_Paz (UTC-04:00) without DST.
/// SQLite keeps instants in UTC; this conversion is presentation-only.
String boliviaTime(DateTime instant) {
  final value = instant.toUtc().subtract(const Duration(hours: 4));
  return '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
}
