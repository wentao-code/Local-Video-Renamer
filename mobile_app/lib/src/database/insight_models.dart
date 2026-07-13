class DistributionItem {
  const DistributionItem({
    required this.label,
    required this.count,
  });

  final String label;
  final int count;
}

class DataCenterSnapshot {
  const DataCenterSnapshot({
    required this.videoCount,
    required this.actorCount,
    required this.codePrefixCount,
    required this.ageDistribution,
    required this.sourceDistribution,
    required this.quantityDistribution,
  });

  final int videoCount;
  final int actorCount;
  final int codePrefixCount;
  final List<DistributionItem> ageDistribution;
  final List<DistributionItem> sourceDistribution;
  final List<DistributionItem> quantityDistribution;
}

class LadderItem {
  const LadderItem({
    required this.name,
    required this.tier,
    required this.movieCount,
    this.age,
    this.isMasterpieceCandidate = false,
    this.medal = '',
  });

  final String name;
  final String tier;
  final int movieCount;
  final int? age;
  final bool isMasterpieceCandidate;
  final String medal;
}

class LadderBoardSnapshot {
  const LadderBoardSnapshot({
    required this.candidates,
    required this.selected,
  });

  final List<LadderItem> candidates;
  final List<LadderItem> selected;
}

class MasterpieceEntry {
  const MasterpieceEntry({
    required this.code,
    required this.title,
    required this.author,
    required this.primarySource,
    required this.medal,
  });

  final String code;
  final String title;
  final String author;
  final String primarySource;
  final String medal;
}

class MasterpieceActor {
  const MasterpieceActor({
    required this.name,
    this.birthday = '',
    this.currentAge = '',
    this.appearanceAge = '',
    this.measurements = '',
  });

  final String name;
  final String birthday;
  final String currentAge;
  final String appearanceAge;
  final String measurements;
}

class MasterpieceReference {
  const MasterpieceReference({
    required this.code,
    required this.title,
    required this.author,
    required this.releaseDate,
    required this.source,
  });

  final String code;
  final String title;
  final String author;
  final String releaseDate;
  final String source;
}

class MasterpieceDetail {
  const MasterpieceDetail({
    required this.entry,
    required this.references,
    required this.actors,
  });

  final MasterpieceEntry entry;
  final List<MasterpieceReference> references;
  final List<MasterpieceActor> actors;
}
