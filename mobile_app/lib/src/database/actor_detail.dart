import 'video_list_item.dart';

class ActorDetail {
  const ActorDetail({
    required this.name,
    required this.birthday,
    required this.age,
    required this.isMatched,
    required this.movieCount,
    required this.latestReleaseDate,
    required this.ladderTier,
    required this.videos,
  });

  final String name;
  final String birthday;
  final String age;
  final bool isMatched;
  final int movieCount;
  final String latestReleaseDate;
  final String ladderTier;
  final List<VideoListItem> videos;

  factory ActorDetail.fromMap(
    Map<String, Object?> row, {
    required List<VideoListItem> videos,
  }) {
    String readString(String key) => (row[key] as String? ?? '').trim();
    int readInt(String key) => (row[key] as num?)?.toInt() ?? 0;

    return ActorDetail(
      name: readString('name'),
      birthday: readString('birthday'),
      age: readString('age'),
      isMatched: readInt('matched') > 0,
      movieCount: readInt('movie_count'),
      latestReleaseDate: readString('latest_release_date'),
      ladderTier: readString('ladder_tier'),
      videos: videos,
    );
  }
}
