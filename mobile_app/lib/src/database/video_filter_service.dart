import 'package:path/path.dart' as p;

import 'database_storage.dart';
import 'filter_settings.dart';
import 'filter_settings_repository.dart';

class VideoFilterService {
  const VideoFilterService(this.settings);

  final FilterSettings settings;

  static Future<VideoFilterService> loadForDatabasePath(String databasePath) async {
    final settingsPath = p.join(
      p.dirname(databasePath),
      DatabaseStorage.filterSettingsFileName,
    );
    final settings = await FilterSettingsRepository(
      settingsFilePath: settingsPath,
    ).load();
    return VideoFilterService(settings);
  }

  List<Map<String, Object?>> filterRows(Iterable<Map<String, Object?>> rows) {
    return rows
        .where(isVisible)
        .map((row) => Map<String, Object?>.from(row))
        .toList(growable: false);
  }

  bool isVisible(Map<String, Object?> row) {
    if (!_isPostEnrichmentVideo(row)) {
      return true;
    }

    return !_matchesAny(_read(row, 'code'), settings.codeKeywords) &&
        !_matchesAny(_read(row, 'display_title', fallbackKey: 'title'), settings.titleKeywords) &&
        !_matchesAny(_read(row, 'javtxt_tags'), settings.javtxtTagKeywords);
  }

  String _read(
    Map<String, Object?> row,
    String key, {
    String? fallbackKey,
  }) {
    final primary = '${row[key] ?? ''}'.trim();
    if (primary.isNotEmpty || fallbackKey == null) {
      return primary;
    }
    return '${row[fallbackKey] ?? ''}'.trim();
  }

  bool _matchesAny(String value, List<String> keywords) {
    final rawValue = value.trim();
    if (rawValue.isEmpty) {
      return false;
    }

    final normalizedValue = rawValue.toLowerCase();
    for (final keyword in keywords) {
      final normalizedKeyword = keyword.trim().toLowerCase();
      if (normalizedKeyword.isEmpty) {
        continue;
      }
      if (normalizedKeyword == 'vr') {
        final normalizedVrText = rawValue.replaceAll('\uff36', 'V').replaceAll('\uff32', 'R');
        if (_vrPattern.hasMatch(normalizedVrText)) {
          return true;
        }
        continue;
      }
      if (normalizedValue.contains(normalizedKeyword)) {
        return true;
      }
    }
    return false;
  }

  bool _isPostEnrichmentVideo(Map<String, Object?> row) {
    if ('${row['manual_tier'] ?? ''}'.trim().isNotEmpty) {
      return true;
    }

    for (final key in const <String>[
      'javtxt_movie_id',
      'javtxt_url',
      'javtxt_title',
      'javtxt_actors',
      'javtxt_tags',
    ]) {
      if ('${row[key] ?? ''}'.trim().isNotEmpty) {
        return true;
      }
    }

    final status = '${row['javtxt_enrichment_status'] ?? ''}'.trim();
    return status.isNotEmpty && status != '\u672a\u8865\u5168';
  }
}

final RegExp _vrPattern = RegExp(
  r'(?<![A-Z0-9])V\s*R(?![A-Z0-9])',
  caseSensitive: false,
);
