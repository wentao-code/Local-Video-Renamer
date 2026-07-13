import 'package:sqflite/sqflite.dart';

import 'insight_models.dart';

class MasterpieceRepository {
  MasterpieceRepository({required this.databasePath});

  final String databasePath;
  Future<Database>? _databaseFuture;

  Future<List<MasterpieceEntry>> listEntries() async {
    final database = await _openDatabase();
    if (!await _tableExists(database, 'masterpiece_entries')) return const [];
    final rows = await database.rawQuery(
      '''
      SELECT m.code,
             COALESCE(NULLIF(m.display_title, ''), NULLIF(p.javtxt_title, ''), NULLIF(p.title, ''), m.code) AS title,
             COALESCE(NULLIF(m.display_author, ''), NULLIF(p.javtxt_actors, ''), NULLIF(p.author, ''), '') AS author,
             COALESCE(NULLIF(m.primary_source, ''), '') AS primary_source,
             COALESCE(m.medal, '') AS medal
      FROM masterpiece_entries m
      LEFT JOIN processed_videos p ON p.code = m.code
      ORDER BY COALESCE(m.created_at, ''), UPPER(m.code)
      ''',
    );
    return rows.map(_entryFromRow).toList(growable: false);
  }

  Future<MasterpieceDetail?> fetchDetail(String code) async {
    final database = await _openDatabase();
    if (!await _tableExists(database, 'masterpiece_entries')) return null;
    final entries = await database.rawQuery(
      '''
      SELECT m.code,
             COALESCE(NULLIF(m.display_title, ''), NULLIF(p.javtxt_title, ''), NULLIF(p.title, ''), m.code) AS title,
             COALESCE(NULLIF(m.display_author, ''), NULLIF(p.javtxt_actors, ''), NULLIF(p.author, ''), '') AS author,
             COALESCE(NULLIF(m.primary_source, ''), '') AS primary_source,
             COALESCE(m.medal, '') AS medal
      FROM masterpiece_entries m
      LEFT JOIN processed_videos p ON p.code = m.code
      WHERE m.code = ?
      LIMIT 1
      ''',
      [code],
    );
    if (entries.isEmpty) return null;

    final references = await _tableExists(database, 'masterpiece_references')
        ? await database.rawQuery(
            '''
            SELECT matched_code, title, author, release_date, reference_source
            FROM masterpiece_references
            WHERE masterpiece_code = ?
            ORDER BY release_date DESC, reference_source, matched_code
            ''',
            [code],
          )
        : const <Map<String, Object?>>[];
    final actorRows = await _tableExists(database, 'masterpiece_actor_details')
        ? await database.rawQuery(
            '''
            SELECT actor_name, birthday, current_age, appearance_age,
                   height, bust, waist, hip, cup
            FROM masterpiece_actor_details
            WHERE masterpiece_code = ?
            ORDER BY actor_order, actor_name
            ''',
            [code],
          )
        : const <Map<String, Object?>>[];
    return MasterpieceDetail(
      entry: _entryFromRow(entries.first),
      references: references
          .map((row) => MasterpieceReference(
                code: '${row['matched_code'] ?? ''}',
                title: '${row['title'] ?? ''}',
                author: '${row['author'] ?? ''}',
                releaseDate: '${row['release_date'] ?? ''}',
                source: '${row['reference_source'] ?? ''}',
              ))
          .toList(growable: false),
      actors: actorRows
          .map((row) => MasterpieceActor(
                name: '${row['actor_name'] ?? ''}',
                birthday: '${row['birthday'] ?? ''}',
                currentAge: '${row['current_age'] ?? ''}',
                appearanceAge: '${row['appearance_age'] ?? ''}',
                measurements: _measurements(row),
              ))
          .toList(growable: false),
    );
  }

  Future<void> dispose() async {
    final future = _databaseFuture;
    _databaseFuture = null;
    if (future != null) await (await future).close();
  }

  Future<Database> _openDatabase() {
    return _databaseFuture ??= openDatabase(databasePath, readOnly: true, singleInstance: false);
  }

  static MasterpieceEntry _entryFromRow(Map<String, Object?> row) => MasterpieceEntry(
        code: '${row['code'] ?? ''}',
        title: '${row['title'] ?? ''}',
        author: '${row['author'] ?? ''}',
        primarySource: '${row['primary_source'] ?? ''}',
        medal: '${row['medal'] ?? ''}',
      );

  static String _measurements(Map<String, Object?> row) {
    final values = <String>[];
    const labels = {
      'height': '身高',
      'bust': '胸围',
      'waist': '腰围',
      'hip': '臀围',
      'cup': '罩杯',
    };
    for (final key in labels.keys) {
      final value = '${row[key] ?? ''}'.trim();
      if (value.isNotEmpty) values.add('${labels[key]} $value');
    }
    return values.join(' / ');
  }

  static Future<bool> _tableExists(Database database, String name) async {
    final rows = await database.rawQuery(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
      [name],
    );
    return rows.isNotEmpty;
  }
}
