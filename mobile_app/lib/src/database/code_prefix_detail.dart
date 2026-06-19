import 'video_list_item.dart';

class CodePrefixDetail {
  const CodePrefixDetail({
    required this.prefix,
    required this.movieCount,
    required this.latestReleaseDate,
    required this.sampleCategory,
    required this.enrichmentStatus,
    required this.indexedVideoCount,
    required this.ladderTier,
    required this.videos,
  });

  final String prefix;
  final int movieCount;
  final String latestReleaseDate;
  final String sampleCategory;
  final String enrichmentStatus;
  final int indexedVideoCount;
  final String ladderTier;
  final List<VideoListItem> videos;

  factory CodePrefixDetail.fromMap(
    Map<String, Object?> row, {
    required List<VideoListItem> videos,
  }) {
    String readString(String key) => (row[key] as String? ?? '').trim();
    int readInt(String key) => (row[key] as num?)?.toInt() ?? 0;

    return CodePrefixDetail(
      prefix: readString('prefix'),
      movieCount: readInt('movie_count'),
      latestReleaseDate: readString('latest_release_date'),
      sampleCategory: readString('sample_category'),
      enrichmentStatus: readString('enrichment_status'),
      indexedVideoCount: readInt('indexed_video_count'),
      ladderTier: readString('ladder_tier'),
      videos: videos,
    );
  }
}
