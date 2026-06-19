import 'actor_list_item.dart';

class ActorSearchResult {
  const ActorSearchResult({
    required this.items,
    required this.totalCount,
    required this.limit,
  });

  final List<ActorListItem> items;
  final int totalCount;
  final int limit;

  bool get hasMore => totalCount > items.length;
}
