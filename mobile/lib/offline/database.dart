import 'package:path/path.dart' as path;
import 'package:sqflite/sqflite.dart';

const databaseVersion = 1;

Future<Database> openOfflineDatabase({
  String? databasePath,
  DatabaseFactory? factory,
}) async {
  final selectedFactory = factory ?? databaseFactory;
  final file =
      databasePath ?? path.join(await getDatabasesPath(), 'uap_offline.db');
  return selectedFactory.openDatabase(
    file,
    options: OpenDatabaseOptions(
      version: databaseVersion,
      onConfigure: (db) async => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, version) async => _createSchema(db),
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 1) await _createSchema(db);
      },
    ),
  );
}

Future<void> _createSchema(Database db) async {
  await db.execute('''CREATE TABLE local_records (
    entity TEXT NOT NULL, record_id TEXT NOT NULL, data_json TEXT NOT NULL,
    server_version INTEGER, updated_at TEXT NOT NULL, deleted_at TEXT,
    sync_state TEXT NOT NULL DEFAULT 'synced', PRIMARY KEY(entity, record_id)
  )''');
  await db.execute('''CREATE TABLE sync_outbox (
    operation_id TEXT PRIMARY KEY, entity TEXT NOT NULL, record_id TEXT NOT NULL,
    operation TEXT NOT NULL, payload_json TEXT NOT NULL, base_version INTEGER,
    created_at TEXT NOT NULL, status TEXT NOT NULL, last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0
  )''');
  await db.execute('''CREATE TABLE sync_metadata (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
  )''');
}
