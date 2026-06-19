class CodePrefixListItem {
  const CodePrefixListItem({
    required this.prefix,
    required this.movieCount,
    required this.latestReleaseDate,
    required this.sampleCategory,
    required this.sampleCode,
    required this.sampleTitle,
    required this.sampleAuthor,
    required this.enrichmentStatus,
    required this.indexedVideoCount,
    required this.ladderTier,
  });

  final String prefix;
  final int movieCount;
  final String latestReleaseDate;
  final String sampleCategory;
  final String sampleCode;
  final String sampleTitle;
  final String sampleAuthor;
  final String enrichmentStatus;
  final int indexedVideoCount;
  final String ladderTier;

  factory CodePrefixListItem.fromMap(Map<String, Object?> row) {
    String readString(String key) => (row[key] as String? ?? '').trim();
    int readInt(String key) => (row[key] as num?)?.toInt() ?? 0;

    return CodePrefixListItem(
      prefix: readString('prefix'),
      movieCount: readInt('movie_count'),
      latestReleaseDate: readString('latest_release_date'),
      sampleCategory: readString('sample_category'),
      sampleCode: readString('sample_code'),
      sampleTitle: readString('sample_title'),
      sampleAuthor: readString('sample_author'),
      enrichmentStatus: readString('enrichment_status'),
      indexedVideoCount: readInt('indexed_video_count'),
      ladderTier: readString('ladder_tier'),
    );
  }
}
