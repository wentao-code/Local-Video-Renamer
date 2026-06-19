import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../database/code_prefix_library_repository.dart';
import '../database/code_prefix_list_item.dart';
import '../database/code_prefix_search_result.dart';
import '../database/database_status.dart';
import 'detail_routes.dart';
import 'widgets/animated_reveal.dart';

class CodePrefixLibraryScreen extends StatefulWidget {
  const CodePrefixLibraryScreen({
    super.key,
    required this.databaseStatus,
    required this.onRefreshDatabaseStatus,
  });

  final DatabaseStatus databaseStatus;
  final VoidCallback onRefreshDatabaseStatus;

  @override
  State<CodePrefixLibraryScreen> createState() => _CodePrefixLibraryScreenState();
}

class _CodePrefixLibraryScreenState extends State<CodePrefixLibraryScreen> {
  late final CodePrefixLibraryRepository _repository;
  final TextEditingController _searchController = TextEditingController();
  Timer? _searchDebounce;
  late Future<CodePrefixSearchResult> _resultFuture;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _repository = CodePrefixLibraryRepository(
      databasePath: widget.databaseStatus.databasePath,
    );
    _resultFuture = _repository.searchPrefixes();
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    unawaited(_repository.dispose());
    super.dispose();
  }

  Future<void> _reload() async {
    widget.onRefreshDatabaseStatus();
    setState(() {
      _resultFuture = _repository.searchPrefixes(query: _query);
    });
    await _resultFuture;
  }

  void _handleSearchChanged(String value) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 280), () {
      if (!mounted) {
        return;
      }
      final normalized = value.trim();
      if (normalized == _query) {
        return;
      }
      setState(() {
        _query = normalized;
        _resultFuture = _repository.searchPrefixes(query: _query);
      });
    });
  }

  void _clearSearch() {
    _searchDebounce?.cancel();
    _searchController.clear();
    if (_query.isEmpty) {
      return;
    }
    setState(() {
      _query = '';
      _resultFuture = _repository.searchPrefixes();
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
        children: [
          AnimatedReveal(
            child: Container(
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(28),
                gradient: const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [Color(0xFF2B233A), Color(0xFF705C8D)],
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '本地番号库',
                    style: theme.textTheme.headlineMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    '直接读取 code_prefix_movies 与 code_prefix_enrichments。支持前缀、番号、标题、演员和分类搜索。',
                    style: theme.textTheme.bodyLarge?.copyWith(
                      color: Colors.white.withValues(alpha: 0.9),
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 18),
                  TextField(
                    controller: _searchController,
                    onChanged: _handleSearchChanged,
                    textInputAction: TextInputAction.search,
                    decoration: InputDecoration(
                      hintText: '搜索前缀、番号、标题、演员、分类',
                      prefixIcon: const Icon(LucideIcons.search, size: 18),
                      suffixIcon: _query.isEmpty
                          ? null
                          : IconButton(
                              onPressed: _clearSearch,
                              icon: const Icon(LucideIcons.x, size: 18),
                            ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          AnimatedReveal(
            delay: const Duration(milliseconds: 80),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Wrap(
                  runSpacing: 10,
                  spacing: 10,
                  children: [
                    _PrefixInfoChip(
                      icon: LucideIcons.database,
                      label: '数据库状态',
                      value: '已连接',
                    ),
                    _PrefixInfoChip(
                      icon: LucideIcons.search,
                      label: '当前搜索',
                      value: _query.isEmpty ? '全部前缀' : _query,
                    ),
                    _PrefixInfoChip(
                      icon: LucideIcons.layoutGrid,
                      label: '数据来源',
                      value: 'code_prefix_*',
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 280),
            switchInCurve: Curves.easeOutCubic,
            switchOutCurve: Curves.easeInCubic,
            transitionBuilder: (child, animation) {
              return FadeTransition(
                opacity: animation,
                child: SlideTransition(
                  position: Tween<Offset>(
                    begin: const Offset(0, 0.04),
                    end: Offset.zero,
                  ).animate(animation),
                  child: child,
                ),
              );
            },
            child: FutureBuilder<CodePrefixSearchResult>(
              key: ValueKey<String>(_query),
              future: _resultFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: 48),
                    child: Center(child: CircularProgressIndicator()),
                  );
                }
                if (snapshot.hasError) {
                  return _PrefixLoadError(
                    errorText: snapshot.error.toString(),
                    onRetry: () {
                      setState(() {
                        _resultFuture = _repository.searchPrefixes(query: _query);
                      });
                    },
                  );
                }

                final result = snapshot.data!;
                return Column(
                  key: ValueKey<String>('prefix-result-$_query-${result.totalCount}'),
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: AnimatedSwitcher(
                        duration: const Duration(milliseconds: 220),
                        child: Text(
                          result.hasMore
                              ? '共 ${result.totalCount} 个前缀，当前展示前 ${result.items.length} 个'
                              : '共 ${result.totalCount} 个前缀',
                          key: ValueKey<String>('prefix-count-${result.totalCount}-${result.items.length}'),
                          style: theme.textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ),
                    if (result.items.isEmpty)
                      const _EmptyPrefixState()
                    else
                      for (var index = 0; index < result.items.length; index++) ...[
                        AnimatedReveal(
                          delay: Duration(milliseconds: 30 * (index.clamp(0, 8))),
                          child: _PrefixCard(
                            item: result.items[index],
                            onTap: () {
                              openCodePrefixDetail(
                                context,
                                databasePath: widget.databaseStatus.databasePath,
                                prefix: result.items[index].prefix,
                              );
                            },
                          ),
                        ),
                        const SizedBox(height: 12),
                      ],
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _PrefixInfoChip extends StatelessWidget {
  const _PrefixInfoChip({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0xFFEEE6F6),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18, color: const Color(0xFF5A3B84)),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: const Color(0xFF5A3B84),
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 2),
              Text(value),
            ],
          ),
        ],
      ),
    );
  }
}

class _PrefixCard extends StatelessWidget {
  const _PrefixCard({
    required this.item,
    required this.onTap,
  });

  final CodePrefixListItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final metaValues = <String>[
      '作品 ${item.movieCount}',
      if (item.indexedVideoCount > 0) '索引 ${item.indexedVideoCount}',
      if (item.latestReleaseDate.isNotEmpty) '最近 ${item.latestReleaseDate}',
    ];

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Wrap(
                      spacing: 10,
                      runSpacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          item.prefix.isEmpty ? '未命名前缀' : item.prefix,
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.6,
                          ),
                        ),
                        if (item.enrichmentStatus.isNotEmpty)
                          _PrefixBadge(
                            text: item.enrichmentStatus,
                            foreground: const Color(0xFF5A3B84),
                            background: const Color(0xFFE6DAF2),
                          ),
                        if (item.sampleCategory.isNotEmpty)
                          _PrefixBadge(
                            text: item.sampleCategory,
                            foreground: const Color(0xFF2D5F50),
                            background: const Color(0xFFDCEFE9),
                          ),
                      ],
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.only(left: 12, top: 2),
                    child: Icon(
                      LucideIcons.chevronRight,
                      color: Color(0xFF9F8AB8),
                      size: 18,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                metaValues.join('  ·  '),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF6A625C),
                ),
              ),
              if (item.sampleCode.isNotEmpty) ...[
                const SizedBox(height: 14),
                _PrefixDetailLine(
                  label: '代表番号',
                  value: item.sampleCode,
                  highlight: true,
                ),
              ],
              if (item.sampleTitle.isNotEmpty) ...[
                const SizedBox(height: 8),
                _PrefixDetailLine(label: '代表标题', value: item.sampleTitle),
              ],
              if (item.sampleAuthor.isNotEmpty) ...[
                const SizedBox(height: 8),
                _PrefixDetailLine(label: '代表演员', value: item.sampleAuthor),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _PrefixDetailLine extends StatelessWidget {
  const _PrefixDetailLine({
    required this.label,
    required this.value,
    this.highlight = false,
  });

  final String label;
  final String value;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final valueColor = highlight ? const Color(0xFF5A3B84) : const Color(0xFF3E3935);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 66,
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: const Color(0xFF8A7E75),
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: valueColor,
                  fontWeight: highlight ? FontWeight.w700 : FontWeight.w500,
                ),
          ),
        ),
      ],
    );
  }
}

class _PrefixBadge extends StatelessWidget {
  const _PrefixBadge({
    required this.text,
    required this.foreground,
    required this.background,
  });

  final String text;
  final Color foreground;
  final Color background;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: foreground,
              fontWeight: FontWeight.w700,
            ),
      ),
    );
  }
}

class _EmptyPrefixState extends StatelessWidget {
  const _EmptyPrefixState();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            const Icon(LucideIcons.searchX, size: 30),
            const SizedBox(height: 12),
            Text(
              '没有找到匹配的番号前缀',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 8),
            const Text(
              '可以尝试输入前缀、完整番号、作品标题、演员名或分类关键字。',
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

class _PrefixLoadError extends StatelessWidget {
  const _PrefixLoadError({
    required this.errorText,
    required this.onRetry,
  });

  final String errorText;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '番号库读取失败',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 10),
            Text(errorText),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(LucideIcons.refreshCw, size: 18),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}
