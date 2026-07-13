import 'package:sqflite/sqflite.dart';

import 'insight_models.dart';

class LadderRepository {
  LadderRepository({required this.databasePath});

  final String databasePath;
  Future<Database>? _databaseFuture;

  Future<LadderBoardSnapshot> loadActorBoard() async {
    final database = await _openDatabase();
    final hiddenNames = await _loadHiddenNames(database);
    final selectedRows = await database.rawQuery(
      '''
      SELECT entity_name, tier, medal
      FROM ladder_entries
      WHERE board_key = 'actor' AND entity_type = 'actor' AND COALESCE(tier, '') <> 'D'
      ORDER BY CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 ELSE 3 END,
               UPPER(entity_name)
      ''',
    );
    final selectedNames = selectedRows.map((row) => '${row['entity_name'] ?? ''}').toSet();

    final countRows = await database.rawQuery(
      '''
      SELECT actor_name, COUNT(DISTINCT code) AS movie_count
      FROM actor_movies
      WHERE TRIM(COALESCE(actor_name, '')) <> ''
      GROUP BY actor_name
      ''',
    );
    final counts = <String, int>{
      for (final row in countRows) '${row['actor_name'] ?? ''}'.trim(): _asInt(row['movie_count']),
    };
    final profileRows = await database.rawQuery('SELECT name, age FROM actors');
    final profiles = <String, _ActorProfile>{};
    for (final row in profileRows) {
      final name = '${row['name'] ?? ''}'.trim();
      if (name.isNotEmpty && !_isHiddenOrIgnored(name, hiddenNames)) {
        profiles[name] = _ActorProfile(name, _parseAge(row['age']), counts[name] ?? 0);
      }
    }
    for (final entry in counts.entries) {
      if (entry.key.isNotEmpty && !_isHiddenOrIgnored(entry.key, hiddenNames)) {
        profiles.putIfAbsent(entry.key, () => _ActorProfile(entry.key, null, entry.value));
      }
    }

    final hasMasterpieceDetails = await _tableExists(database, 'masterpiece_actor_details');
    final hasMasterpieceBasicInfos = await _tableExists(database, 'masterpiece_actor_basic_infos');
    final hasMasterpieceActors = await _tableExists(database, 'masterpiece_actors');
    if (hasMasterpieceDetails && hasMasterpieceBasicInfos && hasMasterpieceActors) {
      final masterpieceRows = await database.rawQuery(
        '''
        SELECT DISTINCT d.actor_name
        FROM (
          SELECT actor_name FROM masterpiece_actor_details
          UNION
          SELECT actor_name FROM masterpiece_actor_basic_infos
        ) d
        LEFT JOIN masterpiece_actors ma ON ma.actor_name = d.actor_name
        LEFT JOIN ladder_entries le
          ON le.board_key = 'actor' AND le.entity_type = 'actor' AND le.entity_name = d.actor_name
        WHERE TRIM(COALESCE(d.actor_name, '')) <> ''
          AND COALESCE(ma.handle_mark, 0) <> 2
          AND COALESCE(le.tier, '') = ''
        ''',
      );
      for (final row in masterpieceRows) {
        final name = '${row['actor_name'] ?? ''}'.trim();
        if (name.isNotEmpty && !_isHiddenOrIgnored(name, hiddenNames)) {
          final current = profiles[name] ?? _ActorProfile(name, null, counts[name] ?? 0);
          profiles[name] = current.copyWith(masterpieceCandidate: true);
        }
      }
    }

    final candidates = profiles.values
        .where((profile) => !selectedNames.contains(profile.name))
        .toList()
      ..sort(_compareProfiles);
    final selected = selectedRows
        .map((row) => LadderItem(
              name: '${row['entity_name'] ?? ''}',
              tier: '${row['tier'] ?? ''}',
              medal: '${row['medal'] ?? ''}',
              movieCount: counts['${row['entity_name'] ?? ''}'] ?? 0,
            ))
        .toList(growable: false);

    return LadderBoardSnapshot(
      candidates: candidates.take(188).map((profile) => profile.toItem()).toList(growable: false),
      selected: selected,
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
    return _databaseFuture ??= openDatabase(databasePath, readOnly: true, singleInstance: false);
  }

  static int _compareProfiles(_ActorProfile a, _ActorProfile b) {
    int group(_ActorProfile profile) {
      if (profile.masterpieceCandidate) return 0;
      if (profile.age != null && profile.age! > 40 && profile.movieCount > 0) return 1;
      if (profile.age != null && profile.age! > 40) return 2;
      if (profile.age == null) return 3;
      if (profile.movieCount > 0) return 4;
      return 5;
    }

    final groupCompare = group(a).compareTo(group(b));
    if (groupCompare != 0) return groupCompare;
    if ((group(a) == 1 || group(a) == 4) && a.movieCount != b.movieCount) {
      return b.movieCount.compareTo(a.movieCount);
    }
    if ((group(a) == 2 || group(a) == 5) && a.age != b.age) {
      return (b.age ?? -1).compareTo(a.age ?? -1);
    }
    return a.name.toUpperCase().compareTo(b.name.toUpperCase());
  }

  static Future<bool> _tableExists(Database database, String name) async {
    final rows = await database.rawQuery(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
      [name],
    );
    return rows.isNotEmpty;
  }

  static Future<Set<String>> _loadHiddenNames(Database database) async {
    if (!await _tableExists(database, 'hidden_actors')) return const {};
    final rows = await database.rawQuery('SELECT name FROM hidden_actors');
    return rows
        .map((row) => '${row['name'] ?? ''}'.trim())
        .where((name) => name.isNotEmpty)
        .toSet();
  }

  static bool _isHiddenOrIgnored(String name, Set<String> hiddenNames) {
    return name.isEmpty ||
        hiddenNames.contains(name) ||
        const {'无', '暂无', '未知', '无记录', 'none', 'null', 'n/a', 'na', '-'}.contains(name.toLowerCase());
  }

  static int _asInt(Object? value) => int.tryParse('${value ?? 0}') ?? 0;

  static int? _parseAge(Object? value) {
    final match = RegExp(r'\d+').firstMatch('${value ?? ''}');
    return match == null ? null : int.tryParse(match.group(0)!);
  }
}

class _ActorProfile {
  const _ActorProfile(
    this.name,
    this.age,
    this.movieCount, {
    this.masterpieceCandidate = false,
  });

  final String name;
  final int? age;
  final int movieCount;
  final bool masterpieceCandidate;

  _ActorProfile copyWith({bool? masterpieceCandidate}) => _ActorProfile(
        name,
        age,
        movieCount,
        masterpieceCandidate: masterpieceCandidate ?? this.masterpieceCandidate,
      );

  LadderItem toItem() => LadderItem(
        name: name,
        tier: '',
        age: age,
        movieCount: movieCount,
        isMasterpieceCandidate: masterpieceCandidate,
      );
}
