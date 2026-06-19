Map<String, Object?>? buildIndexedVideoDetailRow(
  String code, {
  Map<String, Object?>? actorMovieRow,
  Map<String, Object?>? codePrefixMovieRow,
  Map<String, Object?>? codePrefixEnrichmentRow,
}) {
  final actorRow = actorMovieRow ?? const <String, Object?>{};
  final prefixRow = codePrefixMovieRow ?? const <String, Object?>{};
  if (actorRow.isEmpty && prefixRow.isEmpty) {
    return null;
  }

  String readString(Map<String, Object?> row, String key) => '${row[key] ?? ''}'.trim();
  String firstNonEmpty(List<String> values) => values.firstWhere(
        (value) => value.trim().isNotEmpty,
        orElse: () => '',
      );

  final prefix = firstNonEmpty(<String>[
    readString(prefixRow, 'prefix'),
    _extractPrefix(code),
  ]);

  return <String, Object?>{
    'code': code.trim(),
    'display_title': firstNonEmpty(<String>[
      readString(actorRow, 'title'),
      readString(prefixRow, 'title'),
      code,
    ]),
    'author': firstNonEmpty(<String>[
      readString(actorRow, 'author'),
      readString(prefixRow, 'author'),
    ]),
    'duration': '',
    'size': '',
    'storage_location': '',
    'display_release_date': firstNonEmpty(<String>[
      readString(actorRow, 'javtxt_release_date'),
      readString(actorRow, 'release_date'),
      readString(prefixRow, 'javtxt_release_date'),
      readString(prefixRow, 'release_date'),
    ]),
    'maker': '',
    'publisher': '',
    'video_category': firstNonEmpty(<String>[
      readString(actorRow, 'video_category'),
      readString(prefixRow, 'video_category'),
    ]),
    'enrichment_status': firstNonEmpty(<String>[
      '${codePrefixEnrichmentRow?['javtxt_enrichment_status'] ?? ''}'.trim(),
      '${codePrefixEnrichmentRow?['avfan_enrichment_status'] ?? ''}'.trim(),
      '${codePrefixEnrichmentRow?['enrichment_status'] ?? ''}'.trim(),
    ]),
    'description': '',
    'javtxt_tags': firstNonEmpty(<String>[
      readString(actorRow, 'javtxt_tags'),
      readString(prefixRow, 'javtxt_tags'),
    ]),
    'code_prefix': prefix,
  };
}

String _extractPrefix(String code) {
  final normalized = code.trim();
  final divider = normalized.indexOf('-');
  if (divider <= 0) {
    return '';
  }
  return normalized.substring(0, divider);
}
