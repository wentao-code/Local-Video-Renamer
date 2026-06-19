import 'code_prefix_list_item.dart';

class CodePrefixSearchResult {
  const CodePrefixSearchResult({
    required this.items,
    required this.totalCount,
    required this.limit,
  });

  final List<CodePrefixListItem> items;
  final int totalCount;
  final int limit;

  bool get hasMore => totalCount > items.length;
}
