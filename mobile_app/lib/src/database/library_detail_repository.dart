import 'package:sqflite/sqflite.dart';

import 'actor_detail.dart';
import 'code_prefix_detail.dart';
import 'indexed_video_detail_row.dart';
import 'video_detail.dart';
import 'video_filter_service.dart';
import 'video_list_item.dart';

class LibraryDetailRepository {
  LibraryDetailRepository({
    required this.databasePath,
  });

  final String databasePath;
  Future<Database>? _databaseFuture;
  Future<VideoFilterService>? _filterServiceFuture;

  static const int defaultRelatedLimit = 40;

  Future<VideoDetail?> fetchVideoDetail(String code) async {
    final database = await _openDatabase();
    final rows = await database.rawQuery(
      '''
      SELECT
        pv.code,
        COALESCE(NULLIF(pv.javtxt_title, ''), NULLIF(pv.title, ''), pv.code) AS display_title,
        COALESCE(NULLIF(pv.author, ''), '') AS author,
        COALESCE(NULLIF(pv.duration, ''), '') AS duration,
        COALESCE(NULLIF(pv.size, ''), '') AS size,
        COALESCE(NULLIF(pv.storage_location, ''), '') AS storage_location,
        COALESCE(NULLIF(pv.javtxt_release_date, ''), NULLIF(pv.release_date, ''), '') AS display_release_date,
        COALESCE(NULLIF(pv.maker, ''), '') AS maker,
        COALESCE(NULLIF(pv.publisher, ''), '') AS publisher,
        COALESCE(NULLIF(pv.video_category, ''), '') AS video_category,
        COALESCE(NULLIF(pv.enrichment_status, ''), '') AS enrichment_status,
        COALESCE(NULLIF(pv.description, ''), '') AS description,
        COALESCE(NULLIF(pv.javtxt_tags, ''), '') AS javtxt_tags,
        COALESCE(
          NULLIF(cpm.prefix, ''),
          CASE
            WHEN INSTR(pv.code, '-') > 0 THEN SUBSTR(pv.code, 1, INSTR(pv.code, '-') - 1)
            ELSE ''
          END
        ) AS code_prefix
      FROM processed_videos pv
      LEFT JOIN code_prefix_movies cpm ON cpm.code = pv.code
      WHERE pv.code = ?
      LIMIT 1
      ''',
      <Object?>[code],
    );

    if (rows.isNotEmpty) {
      final actors = await _fetchVideoActors(database, code, fallbackAuthor: (rows.first['author'] as String? ?? '').trim());
      return VideoDetail.fromMap(
        rows.first,
        actors: actors,
        detailSource: VideoDetailSource.local,
      );
    }

    final actorRows = await database.rawQuery(
      '''
      SELECT
        actor_name,
        code,
        title,
        author,
        release_date,
        javtxt_release_date,
        javtxt_tags,
        video_category
      FROM actor_movies
      WHERE code = ?
      ORDER BY actor_name COLLATE NOCASE ASC
      ''',
      <Object?>[code],
    );
    final prefixRows = await database.rawQuery(
      '''
      SELECT
        prefix,
        code,
        title,
        author,
        release_date,
        javtxt_release_date,
        javtxt_tags,
        video_category
      FROM code_prefix_movies
      WHERE code = ?
      ORDER BY prefix COLLATE NOCASE ASC
      ''',
      <Object?>[code],
    );
    if (actorRows.isEmpty && prefixRows.isEmpty) {
      return null;
    }

    final prefix = prefixRows.isNotEmpty ? (prefixRows.first['prefix'] as String? ?? '').trim() : '';
    Map<String, Object?>? enrichmentRow;
    if (prefix.isNotEmpty) {
      final enrichmentRows = await database.rawQuery(
        '''
        SELECT
          enrichment_status,
          avfan_enrichment_status,
          javtxt_enrichment_status
        FROM code_prefix_enrichments
        WHERE prefix = ?
        LIMIT 1
        ''',
        <Object?>[prefix],
      );
      if (enrichmentRows.isNotEmpty) {
        enrichmentRow = enrichmentRows.first;
      }
    }

    final indexedRow = buildIndexedVideoDetailRow(
      code,
      actorMovieRow: actorRows.isEmpty ? null : actorRows.first,
      codePrefixMovieRow: prefixRows.isEmpty ? null : prefixRows.first,
      codePrefixEnrichmentRow: enrichmentRow,
    );
    if (indexedRow == null) {
      return null;
    }

    final actors = await _fetchVideoActors(
      database,
      code,
      fallbackAuthor: (indexedRow['author'] as String? ?? '').trim(),
    );
    return VideoDetail.fromMap(
      indexedRow,
      actors: actors,
      detailSource: VideoDetailSource.indexed,
    );
  }

  Future<ActorDetail?> fetchActorDetail(
    String actorName, {
    int relatedLimit = defaultRelatedLimit,
  }) async {
    final database = await _openDatabase();
    final filterService = await _loadFilterService();
    final rows = await database.rawQuery(
      '''
      SELECT
        a.name,
        COALESCE(NULLIF(a.birthday, ''), '') AS birthday,
        COALESCE(NULLIF(a.age, ''), '') AS age,
        COALESCE(a.matched, 0) AS matched,
        COUNT(am.code) AS movie_count,
        MAX(COALESCE(NULLIF(am.javtxt_release_date, ''), NULLIF(am.release_date, ''), '')) AS latest_release_date,
        COALESCE(NULLIF(le.tier, ''), '') AS ladder_tier
      FROM actors a
      LEFT JOIN actor_movies am ON am.actor_name = a.name
      LEFT JOIN ladder_entries le
        ON le.board_key = 'actor'
        AND le.entity_type = 'actor'
        AND le.entity_name = a.name
      WHERE a.name = ?
      GROUP BY a.name, a.birthday, a.age, a.matched, le.tier
      LIMIT 1
      ''',
      <Object?>[actorName],
    );

    if (rows.isEmpty) {
      return null;
    }

    final videos = await database.rawQuery(
      '''
      SELECT
        am.code AS code,
        COALESCE(NULLIF(pv.javtxt_title, ''), NULLIF(pv.title, ''), NULLIF(am.title, ''), am.code) AS display_title,
        COALESCE(NULLIF(pv.author, ''), NULLIF(am.author, ''), '') AS author,
        COALESCE(NULLIF(pv.duration, ''), '') AS duration,
        COALESCE(NULLIF(pv.size, ''), '') AS size,
        COALESCE(NULLIF(pv.storage_location, ''), '') AS storage_location,
        COALESCE(
          NULLIF(pv.javtxt_release_date, ''),
          NULLIF(pv.release_date, ''),
          NULLIF(am.javtxt_release_date, ''),
          NULLIF(am.release_date, ''),
          ''
        ) AS display_release_date,
        COALESCE(NULLIF(pv.maker, ''), '') AS maker,
        COALESCE(NULLIF(pv.publisher, ''), '') AS publisher,
        COALESCE(NULLIF(pv.video_category, ''), NULLIF(am.video_category, ''), '') AS video_category,
        COALESCE(NULLIF(pv.enrichment_status, ''), NULLIF(pv.javtxt_enrichment_status, ''), '') AS enrichment_status,
        COALESCE(NULLIF(pv.javtxt_title, ''), NULLIF(am.title, ''), '') AS javtxt_title,
        COALESCE(NULLIF(pv.javtxt_tags, ''), NULLIF(am.javtxt_tags, ''), '') AS javtxt_tags,
        COALESCE(NULLIF(pv.javtxt_enrichment_status, ''), '') AS javtxt_enrichment_status,
        COALESCE(NULLIF(pv.javtxt_movie_id, ''), '') AS javtxt_movie_id,
        COALESCE(NULLIF(pv.javtxt_url, ''), '') AS javtxt_url
      FROM actor_movies am
      LEFT JOIN processed_videos pv ON pv.code = am.code
      WHERE am.actor_name = ?
      GROUP BY am.code
      ORDER BY
        CASE
          WHEN COALESCE(
            NULLIF(pv.javtxt_release_date, ''),
            NULLIF(pv.release_date, ''),
            NULLIF(am.javtxt_release_date, ''),
            NULLIF(am.release_date, ''),
            ''
          ) = '' THEN 1
          ELSE 0
        END,
        COALESCE(
          NULLIF(pv.javtxt_release_date, ''),
          NULLIF(pv.release_date, ''),
          NULLIF(am.javtxt_release_date, ''),
          NULLIF(am.release_date, ''),
          ''
        ) DESC,
        am.code DESC
      LIMIT ?
      ''',
      <Object?>[actorName, relatedLimit],
    );
    final filteredVideos = filterService.filterRows(
      videos.cast<Map<String, Object?>>(),
    );

    return ActorDetail.fromMap(
      rows.first,
      videos: filteredVideos.map(VideoListItem.fromMap).toList(growable: false),
    );
  }

  Future<CodePrefixDetail?> fetchCodePrefixDetail(
    String prefix, {
    int relatedLimit = defaultRelatedLimit,
  }) async {
    final database = await _openDatabase();
    final filterService = await _loadFilterService();
    final rows = await database.rawQuery(
      '''
      SELECT
        c.prefix,
        COUNT(c.code) AS movie_count,
        MAX(COALESCE(NULLIF(c.javtxt_release_date, ''), NULLIF(c.release_date, ''), '')) AS latest_release_date,
        MAX(COALESCE(NULLIF(c.video_category, ''), '')) AS sample_category,
        MAX(
          COALESCE(
            NULLIF(e.javtxt_enrichment_status, ''),
            NULLIF(e.avfan_enrichment_status, ''),
            NULLIF(e.enrichment_status, ''),
            ''
          )
        ) AS enrichment_status,
        MAX(COALESCE(e.javtxt_total_videos, e.avfan_total_videos, 0)) AS indexed_video_count,
        COALESCE(NULLIF(le.tier, ''), '') AS ladder_tier
      FROM code_prefix_movies c
      LEFT JOIN code_prefix_enrichments e ON e.prefix = c.prefix
      LEFT JOIN ladder_entries le
        ON le.board_key = 'code_prefix'
        AND le.entity_type = 'code_prefix'
        AND UPPER(le.entity_name) = UPPER(c.prefix)
      WHERE c.prefix = ?
      GROUP BY c.prefix, le.tier
      LIMIT 1
      ''',
      <Object?>[prefix],
    );

    if (rows.isEmpty) {
      return null;
    }

    final videos = await database.rawQuery(
      '''
      SELECT
        c.code AS code,
        COALESCE(NULLIF(pv.javtxt_title, ''), NULLIF(pv.title, ''), NULLIF(c.title, ''), c.code) AS display_title,
        COALESCE(NULLIF(pv.author, ''), NULLIF(c.author, ''), '') AS author,
        COALESCE(NULLIF(pv.duration, ''), '') AS duration,
        COALESCE(NULLIF(pv.size, ''), '') AS size,
        COALESCE(NULLIF(pv.storage_location, ''), '') AS storage_location,
        COALESCE(
          NULLIF(pv.javtxt_release_date, ''),
          NULLIF(pv.release_date, ''),
          NULLIF(c.javtxt_release_date, ''),
          NULLIF(c.release_date, ''),
          ''
        ) AS display_release_date,
        COALESCE(NULLIF(pv.maker, ''), '') AS maker,
        COALESCE(NULLIF(pv.publisher, ''), '') AS publisher,
        COALESCE(NULLIF(pv.video_category, ''), NULLIF(c.video_category, ''), '') AS video_category,
        COALESCE(NULLIF(pv.enrichment_status, ''), NULLIF(pv.javtxt_enrichment_status, ''), '') AS enrichment_status,
        COALESCE(NULLIF(pv.javtxt_title, ''), NULLIF(c.title, ''), '') AS javtxt_title,
        COALESCE(NULLIF(pv.javtxt_tags, ''), NULLIF(c.javtxt_tags, ''), '') AS javtxt_tags,
        COALESCE(NULLIF(pv.javtxt_enrichment_status, ''), '') AS javtxt_enrichment_status,
        COALESCE(NULLIF(pv.javtxt_movie_id, ''), '') AS javtxt_movie_id,
        COALESCE(NULLIF(pv.javtxt_url, ''), '') AS javtxt_url
      FROM code_prefix_movies c
      LEFT JOIN processed_videos pv ON pv.code = c.code
      WHERE c.prefix = ?
      GROUP BY c.code
      ORDER BY
        CASE
          WHEN COALESCE(
            NULLIF(pv.javtxt_release_date, ''),
            NULLIF(pv.release_date, ''),
            NULLIF(c.javtxt_release_date, ''),
            NULLIF(c.release_date, ''),
            ''
          ) = '' THEN 1
          ELSE 0
        END,
        COALESCE(
          NULLIF(pv.javtxt_release_date, ''),
          NULLIF(pv.release_date, ''),
          NULLIF(c.javtxt_release_date, ''),
          NULLIF(c.release_date, ''),
          ''
        ) DESC,
        c.code DESC
      LIMIT ?
      ''',
      <Object?>[prefix, relatedLimit],
    );
    final filteredVideos = filterService.filterRows(
      videos.cast<Map<String, Object?>>(),
    );

    return CodePrefixDetail.fromMap(
      rows.first,
      videos: filteredVideos.map(VideoListItem.fromMap).toList(growable: false),
    );
  }

  Future<void> dispose() async {
    final future = _databaseFuture;
    _databaseFuture = null;
    if (future == null) {
      return;
    }
    final database = await future;
    await database.close();
  }

  Future<Database> _openDatabase() {
    return _databaseFuture ??= openDatabase(
      databasePath,
      readOnly: true,
      singleInstance: false,
    );
  }

  Future<VideoFilterService> _loadFilterService() {
    return _filterServiceFuture ??= VideoFilterService.loadForDatabasePath(
      databasePath,
    );
  }

  Future<List<String>> _fetchVideoActors(
    Database database,
    String code, {
    required String fallbackAuthor,
  }) async {
    final actorRows = await database.rawQuery(
      '''
      SELECT actor_name
      FROM actor_movies
      WHERE code = ?
      ORDER BY actor_name COLLATE NOCASE ASC
      ''',
      <Object?>[code],
    );

    if (actorRows.isNotEmpty) {
      return actorRows
          .map((row) => (row['actor_name'] as String? ?? '').trim())
          .where((value) => value.isNotEmpty)
          .toList(growable: false);
    }

    return fallbackAuthor
        .split(RegExp(r'[、,，/｜|\s]+'))
        .map((value) => value.trim())
        .where((value) => value.isNotEmpty)
        .toList(growable: false);
  }
}
