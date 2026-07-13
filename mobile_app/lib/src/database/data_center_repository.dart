import 'package:sqflite/sqflite.dart';

import 'insight_models.dart';

class DataCenterRepository {
  DataCenterRepository({required this.databasePath});

  final String databasePath;
  Future<Database>? _databaseFuture;

  Future<DataCenterSnapshot> load() async {
    final database = await _openDatabase();
    final videoCount = await _count(database, 'SELECT COUNT(*) FROM processed_videos');
    final actorCount = await _count(database, 'SELECT COUNT(*) FROM actors');
    final codePrefixCount = await _count(
      database,
      "SELECT COUNT(DISTINCT prefix) FROM code_prefix_movies WHERE TRIM(COALESCE(prefix, '')) <> ''",
    );

    final ageRows = await database.rawQuery('SELECT age FROM actors');
    final ageBuckets = <String, int>{
      '无年龄': 0,
      '40岁及以下': 0,
      '41-50岁': 0,
      '51岁以上': 0,
    };
    for (final row in ageRows) {
      final age = _parseAge(row['age']);
      if (age == null) {
        ageBuckets['无年龄'] = ageBuckets['无年龄']! + 1;
      } else if (age <= 40) {
        ageBuckets['40岁及以下'] = ageBuckets['40岁及以下']! + 1;
      } else if (age <= 50) {
        ageBuckets['41-50岁'] = ageBuckets['41-50岁']! + 1;
      } else {
        ageBuckets['51岁以上'] = ageBuckets['51岁以上']! + 1;
      }
    }

    final sourceRows = await database.rawQuery(
      '''
      SELECT
        CASE
          WHEN TRIM(COALESCE(avfan_movie_id, '')) <> '' AND TRIM(COALESCE(javtxt_movie_id, '')) <> '' THEN '双来源'
          WHEN TRIM(COALESCE(avfan_movie_id, '')) <> '' THEN 'AVFan'
          WHEN TRIM(COALESCE(javtxt_movie_id, '')) <> '' THEN 'JAVTXT'
          ELSE '暂无来源'
        END AS source_label,
        COUNT(*) AS item_count
      FROM processed_videos
      GROUP BY source_label
      ORDER BY item_count DESC, source_label ASC
      ''',
    );

    final quantityRows = await database.rawQuery(
      '''
      SELECT actor_name, COUNT(DISTINCT code) AS movie_count
      FROM actor_movies
      WHERE TRIM(COALESCE(actor_name, '')) <> ''
      GROUP BY actor_name
      ''',
    );
    final quantityBuckets = <String, int>{
      '1-5部': 0,
      '6-20部': 0,
      '21-50部': 0,
      '51部以上': 0,
    };
    for (final row in quantityRows) {
      final count = _asInt(row['movie_count']);
      if (count <= 5) {
        quantityBuckets['1-5部'] = quantityBuckets['1-5部']! + 1;
      } else if (count <= 20) {
        quantityBuckets['6-20部'] = quantityBuckets['6-20部']! + 1;
      } else if (count <= 50) {
        quantityBuckets['21-50部'] = quantityBuckets['21-50部']! + 1;
      } else {
        quantityBuckets['51部以上'] = quantityBuckets['51部以上']! + 1;
      }
    }

    return DataCenterSnapshot(
      videoCount: videoCount,
      actorCount: actorCount,
      codePrefixCount: codePrefixCount,
      ageDistribution: _items(ageBuckets),
      sourceDistribution: sourceRows
          .map((row) => DistributionItem(
                label: '${row['source_label'] ?? ''}',
                count: _asInt(row['item_count']),
              ))
          .toList(growable: false),
      quantityDistribution: _items(quantityBuckets),
    );
  }

  Future<void> dispose() async {
    final future = _databaseFuture;
    _databaseFuture = null;
    if (future != null) {
      await (await future).close();
    }
  }

  Future<Database> _openDatabase() {
    return _databaseFuture ??= openDatabase(
      databasePath,
      readOnly: true,
      singleInstance: false,
    );
  }

  static Future<int> _count(Database database, String sql) async {
    final rows = await database.rawQuery(sql);
    if (rows.isEmpty) return 0;
    return _asInt(rows.first.values.first);
  }

  static List<DistributionItem> _items(Map<String, int> values) => values.entries
      .map((entry) => DistributionItem(label: entry.key, count: entry.value))
      .toList(growable: false);

  static int _asInt(Object? value) => int.tryParse('${value ?? 0}') ?? 0;

  static int? _parseAge(Object? value) {
    final match = RegExp(r'\d+').firstMatch('${value ?? ''}');
    return match == null ? null : int.tryParse(match.group(0)!);
  }
}
