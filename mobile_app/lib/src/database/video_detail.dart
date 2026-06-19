class VideoDetail {
  const VideoDetail({
    required this.code,
    required this.title,
    required this.author,
    required this.duration,
    required this.size,
    required this.storageLocation,
    required this.releaseDate,
    required this.maker,
    required this.publisher,
    required this.videoCategory,
    required this.enrichmentStatus,
    required this.description,
    required this.tags,
    required this.prefix,
    required this.actors,
  });

  final String code;
  final String title;
  final String author;
  final String duration;
  final String size;
  final String storageLocation;
  final String releaseDate;
  final String maker;
  final String publisher;
  final String videoCategory;
  final String enrichmentStatus;
  final String description;
  final String tags;
  final String prefix;
  final List<String> actors;

  List<String> get tagList => tags
      .split(RegExp(r'[\s,|，]+'))
      .map((value) => value.trim())
      .where((value) => value.isNotEmpty)
      .toList(growable: false);

  factory VideoDetail.fromMap(
    Map<String, Object?> row, {
    required List<String> actors,
  }) {
    String readString(String key) => (row[key] as String? ?? '').trim();

    return VideoDetail(
      code: readString('code'),
      title: readString('display_title'),
      author: readString('author'),
      duration: readString('duration'),
      size: readString('size'),
      storageLocation: readString('storage_location'),
      releaseDate: readString('display_release_date'),
      maker: readString('maker'),
      publisher: readString('publisher'),
      videoCategory: readString('video_category'),
      enrichmentStatus: readString('enrichment_status'),
      description: readString('description'),
      tags: readString('javtxt_tags'),
      prefix: readString('code_prefix'),
      actors: actors,
    );
  }
}
