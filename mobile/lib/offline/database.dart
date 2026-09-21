import 'package:path/path.dart' as path;
import 'package:sqflite/sqflite.dart';

const databaseVersion = 3;

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
        if (oldVersion < 3) await _migrateIdentitySchema(db);
      },
    ),
  );
}

Future<void> _createSchema(Database db) async {
  await db.execute('''CREATE TABLE local_records (
    local_id TEXT NOT NULL, entity TEXT NOT NULL, server_id TEXT, data_json TEXT NOT NULL,
    server_version INTEGER, updated_at TEXT NOT NULL, deleted_at TEXT,
    sync_state TEXT NOT NULL DEFAULT 'synced', PRIMARY KEY(local_id)
  )''');
  await db.execute(
    'CREATE UNIQUE INDEX local_records_server_identity ON local_records(entity, server_id) WHERE server_id IS NOT NULL',
  );
  await db.execute('''CREATE TABLE identity_map (
    entity TEXT NOT NULL, local_id TEXT NOT NULL, server_id TEXT NOT NULL,
    PRIMARY KEY(entity, local_id), UNIQUE(entity, server_id)
  )''');
  await db.execute('''CREATE TABLE sync_outbox (
    operation_id TEXT PRIMARY KEY, entity TEXT NOT NULL, record_id TEXT, local_id TEXT NOT NULL, server_id TEXT,
    client_record_id TEXT NOT NULL,
    operation TEXT NOT NULL, payload_json TEXT NOT NULL, base_version INTEGER,
    created_at TEXT NOT NULL, status TEXT NOT NULL, last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0
  )''');
  await db.execute(
    'CREATE INDEX sync_outbox_local_identity ON sync_outbox(entity, local_id, created_at)',
  );
  await db.execute('''CREATE TABLE sync_metadata (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
  )''');
}

Future<void> _migrateIdentitySchema(Database db) async {
  await db.transaction((txn) async {
    await txn.execute('''CREATE TABLE local_records_v3 (
      local_id TEXT NOT NULL PRIMARY KEY, entity TEXT NOT NULL, server_id TEXT,
      data_json TEXT NOT NULL, server_version INTEGER, updated_at TEXT NOT NULL,
      deleted_at TEXT, sync_state TEXT NOT NULL DEFAULT 'synced')''');
    final records = await txn.query('local_records');
    for (final row in records) {
      final serverId = row['record_id']?.toString();
      final localId = 'legacy-${row['entity']}-${serverId ?? 'unknown'}';
      await txn.insert('local_records_v3', {
        'local_id': localId,
        'entity': row['entity'],
        'server_id': serverId,
        'data_json': row['data_json'],
        'server_version': row['server_version'],
        'updated_at': row['updated_at'],
        'deleted_at': row['deleted_at'],
        'sync_state': row['sync_state'],
      });
    }
    await txn.execute('DROP TABLE local_records');
    await txn.execute('ALTER TABLE local_records_v3 RENAME TO local_records');
    await txn.execute(
      'CREATE UNIQUE INDEX local_records_server_identity ON local_records(entity, server_id) WHERE server_id IS NOT NULL',
    );
    await txn.execute('''CREATE TABLE identity_map (
      entity TEXT NOT NULL, local_id TEXT NOT NULL, server_id TEXT NOT NULL,
      PRIMARY KEY(entity, local_id), UNIQUE(entity, server_id)
    )''');
    for (final row in records) {
      await txn.insert('identity_map', {
        'entity': row['entity'],
        'local_id': 'legacy-${row['entity']}-${row['record_id']}',
        'server_id': row['record_id'],
      });
    }
    await txn.execute('ALTER TABLE sync_outbox ADD COLUMN local_id TEXT');
    await txn.execute('ALTER TABLE sync_outbox ADD COLUMN server_id TEXT');
    await txn.execute(
      'ALTER TABLE sync_outbox ADD COLUMN client_record_id TEXT',
    );
    await txn.execute('''UPDATE sync_outbox SET local_id = (
      SELECT local_id FROM local_records WHERE local_records.entity = sync_outbox.entity
      AND local_records.server_id = sync_outbox.record_id LIMIT 1),
      server_id = record_id, client_record_id = operation_id
      WHERE local_id IS NULL''');
    await txn.execute(
      'UPDATE sync_outbox SET local_id = operation_id WHERE local_id IS NULL',
    );
    await txn.execute(
      'UPDATE sync_outbox SET client_record_id = local_id WHERE client_record_id IS NULL',
    );
    await txn.execute(
      'CREATE INDEX sync_outbox_local_identity ON sync_outbox(entity, local_id, created_at)',
    );
  });
}
