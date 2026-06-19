class ActorListItem {
  const ActorListItem({
    required this.name,
    required this.birthday,
    required this.age,
    required this.isMatched,
    required this.movieCount,
    required this.latestReleaseDate,
    required this.sampleCategory,
    required this.sampleCode,
    required this.sampleTitle,
  });

  final String name;
  final String birthday;
  final String age;
  final bool isMatched;
  final int movieCount;
  final String latestReleaseDate;
  final String sampleCategory;
  final String sampleCode;
  final String sampleTitle;

  factory ActorListItem.fromMap(Map<String, Object?> row) {
    String readString(String key) => (row[key] as String? ?? '').trim();
    int readInt(String key) => (row[key] as num?)?.toInt() ?? 0;

    return ActorListItem(
      name: readString('name'),
      birthday: readString('birthday'),
      age: readString('age'),
      isMatched: readInt('matched') > 0,
      movieCount: readInt('movie_count'),
      latestReleaseDate: readString('latest_release_date'),
      sampleCategory: readString('sample_category'),
      sampleCode: readString('sample_code'),
      sampleTitle: readString('sample_title'),
    );
  }
}
