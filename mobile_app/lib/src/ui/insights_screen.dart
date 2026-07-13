import 'package:flutter/material.dart';

import '../database/data_center_repository.dart';
import '../database/insight_models.dart';
import '../database/ladder_repository.dart';
import '../database/masterpiece_repository.dart';
import 'theme/app_design.dart';
import 'theme/app_icons.dart';

class InsightsScreen extends StatefulWidget {
  const InsightsScreen({super.key, required this.databasePath});

  final String databasePath;

  @override
  State<InsightsScreen> createState() => _InsightsScreenState();
}

class _InsightsScreenState extends State<InsightsScreen> {
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Column(
        children: [
          Material(
            color: AppDesign.surface.withValues(alpha: 0.9),
            child: const TabBar(
              tabs: [
                Tab(text: '数据中心', icon: Icon(LucideIcons.chartNoAxesCombined, size: 18)),
                Tab(text: '天梯榜', icon: Icon(LucideIcons.trophy, size: 18)),
                Tab(text: '名作堂', icon: Icon(LucideIcons.medal, size: 18)),
              ],
            ),
          ),
          Expanded(
            child: TabBarView(
              children: [
                DataCenterView(databasePath: widget.databasePath),
                LadderReadOnlyView(databasePath: widget.databasePath),
                MasterpieceReadOnlyView(databasePath: widget.databasePath),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class DataCenterView extends StatefulWidget {
  const DataCenterView({super.key, required this.databasePath});

  final String databasePath;

  @override
  State<DataCenterView> createState() => _DataCenterViewState();
}

class _DataCenterViewState extends State<DataCenterView> {
  late final DataCenterRepository _repository;
  late Future<DataCenterSnapshot> _future;

  @override
  void initState() {
    super.initState();
    _repository = DataCenterRepository(databasePath: widget.databasePath);
    _future = _repository.load();
  }

  void _reload() {
    setState(() {
      _future = _repository.load();
    });
  }

  @override
  void dispose() {
    _repository.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<DataCenterSnapshot>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return _ReadOnlyError(message: '${snapshot.error}', onRetry: _reload);
        }
        final data = snapshot.data!;
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
            children: [
              _SectionHeader(title: '本地数据概览', onRefresh: _reload),
              const SizedBox(height: 12),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  _MetricCard(label: '视频', value: data.videoCount),
                  _MetricCard(label: '演员', value: data.actorCount),
                  _MetricCard(label: '番号前缀', value: data.codePrefixCount),
                ],
              ),
              const SizedBox(height: 24),
              _DistributionSection(title: '演员年龄分布', items: data.ageDistribution),
              const SizedBox(height: 20),
              _DistributionSection(title: '视频来源分布', items: data.sourceDistribution),
              const SizedBox(height: 20),
              _DistributionSection(title: '演员作品数量分布', items: data.quantityDistribution),
            ],
          ),
        );
      },
    );
  }
}

class LadderReadOnlyView extends StatefulWidget {
  const LadderReadOnlyView({super.key, required this.databasePath});

  final String databasePath;

  @override
  State<LadderReadOnlyView> createState() => _LadderReadOnlyViewState();
}

class _LadderReadOnlyViewState extends State<LadderReadOnlyView> {
  late final LadderRepository _repository;
  late Future<LadderBoardSnapshot> _future;

  @override
  void initState() {
    super.initState();
    _repository = LadderRepository(databasePath: widget.databasePath);
    _future = _repository.loadActorBoard();
  }

  void _reload() {
    setState(() {
      _future = _repository.loadActorBoard();
    });
  }

  @override
  void dispose() {
    _repository.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<LadderBoardSnapshot>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return _ReadOnlyError(message: '${snapshot.error}', onRetry: _reload);
        }
        final data = snapshot.data!;
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
            children: [
              _SectionHeader(title: '演员天梯榜', onRefresh: _reload),
              const SizedBox(height: 8),
              Text('候选 ${data.candidates.length} 人 · 已入榜 ${data.selected.length} 人', style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 14),
              _LadderSection(title: '候选演员', items: data.candidates),
              const SizedBox(height: 20),
              _LadderSection(title: '已入榜演员', items: data.selected),
            ],
          ),
        );
      },
    );
  }
}

class MasterpieceReadOnlyView extends StatefulWidget {
  const MasterpieceReadOnlyView({super.key, required this.databasePath});

  final String databasePath;

  @override
  State<MasterpieceReadOnlyView> createState() => _MasterpieceReadOnlyViewState();
}

class _MasterpieceReadOnlyViewState extends State<MasterpieceReadOnlyView> {
  late final MasterpieceRepository _repository;
  late Future<List<MasterpieceEntry>> _future;

  @override
  void initState() {
    super.initState();
    _repository = MasterpieceRepository(databasePath: widget.databasePath);
    _future = _repository.listEntries();
  }

  void _reload() {
    setState(() {
      _future = _repository.listEntries();
    });
  }

  @override
  void dispose() {
    _repository.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<MasterpieceEntry>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return _ReadOnlyError(message: '${snapshot.error}', onRetry: _reload);
        }
        final entries = snapshot.data!;
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView.builder(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
            itemCount: entries.length + 1,
            itemBuilder: (context, index) {
              if (index == 0) {
                return _SectionHeader(title: '名作堂', onRefresh: _reload);
              }
              final entry = entries[index - 1];
              return Card(
                margin: const EdgeInsets.only(top: 12),
                child: ListTile(
                  title: Text(entry.code, style: const TextStyle(fontWeight: FontWeight.w800)),
                  subtitle: Text('${entry.title}\n${entry.author}'),
                  isThreeLine: true,
                  trailing: const Icon(LucideIcons.chevronRight),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => MasterpieceDetailReadOnlyScreen(
                        databasePath: widget.databasePath,
                        code: entry.code,
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        );
      },
    );
  }
}

class MasterpieceDetailReadOnlyScreen extends StatefulWidget {
  const MasterpieceDetailReadOnlyScreen({super.key, required this.databasePath, required this.code});

  final String databasePath;
  final String code;

  @override
  State<MasterpieceDetailReadOnlyScreen> createState() => _MasterpieceDetailReadOnlyScreenState();
}

class _MasterpieceDetailReadOnlyScreenState extends State<MasterpieceDetailReadOnlyScreen> {
  late final MasterpieceRepository _repository;
  late Future<MasterpieceDetail?> _future;

  @override
  void initState() {
    super.initState();
    _repository = MasterpieceRepository(databasePath: widget.databasePath);
    _future = _repository.fetchDetail(widget.code);
  }

  void _reload() {
    setState(() {
      _future = _repository.fetchDetail(widget.code);
    });
  }

  @override
  void dispose() {
    _repository.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.code)),
      body: FutureBuilder<MasterpieceDetail?>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
          if (snapshot.hasError) return _ReadOnlyError(message: '${snapshot.error}', onRetry: _reload);
          final detail = snapshot.data;
          if (detail == null) return const Center(child: Text('没有找到名作详情'));
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
            children: [
              Text(detail.entry.title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              Text('${detail.entry.code} · ${detail.entry.author}'),
              const SizedBox(height: 24),
              _DetailGroup(title: '出演演员', children: detail.actors.map((actor) => ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(actor.name),
                    subtitle: Text([actor.birthday, actor.currentAge, actor.appearanceAge, actor.measurements]
                        .where((value) => value.trim().isNotEmpty)
                        .join(' · ')),
                  )).toList()),
              const SizedBox(height: 16),
              _DetailGroup(title: '相关作品记录', children: detail.references.map((reference) => ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(reference.code),
                    subtitle: Text('${reference.title}\n${reference.author} · ${reference.releaseDate}'),
                    isThreeLine: true,
                  )).toList()),
            ],
          );
        },
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.onRefresh});

  final String title;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) => Row(
        children: [
          Expanded(child: Text(title, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800))),
          IconButton(onPressed: onRefresh, tooltip: '刷新', icon: const Icon(LucideIcons.refreshCw, size: 19)),
        ],
      );
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.label, required this.value});

  final String label;
  final int value;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 108,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: Theme.of(context).textTheme.labelMedium),
              const SizedBox(height: 5),
              Text('$value', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, color: AppDesign.indigo)),
            ]),
          ),
        ),
      );
}

class _DistributionSection extends StatelessWidget {
  const _DistributionSection({required this.title, required this.items});

  final String title;
  final List<DistributionItem> items;

  @override
  Widget build(BuildContext context) {
    final maxValue = items.fold<int>(0, (max, item) => item.count > max ? item.count : max);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: 12),
          if (items.isEmpty) const Text('暂无数据')
          else ...items.map((item) => Padding(
                padding: const EdgeInsets.only(bottom: 11),
                child: Row(children: [
                  SizedBox(width: 82, child: Text(item.label, style: Theme.of(context).textTheme.bodySmall)),
                  Expanded(child: LinearProgressIndicator(value: maxValue == 0 ? 0 : item.count / maxValue, minHeight: 8, borderRadius: BorderRadius.circular(8))),
                  const SizedBox(width: 10),
                  SizedBox(width: 38, child: Text('${item.count}', textAlign: TextAlign.right)),
                ]),
              )),
        ]),
      ),
    );
  }
}

class _LadderSection extends StatelessWidget {
  const _LadderSection({required this.title, required this.items});

  final String title;
  final List<LadderItem> items;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.all(4), child: Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800))),
            if (items.isEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('暂无数据'))
            else ...items.asMap().entries.map((entry) => ListTile(
                  dense: true,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                  leading: CircleAvatar(radius: 16, child: Text('${entry.key + 1}')),
                  title: Text(entry.value.name),
                  subtitle: Text(entry.value.isMasterpieceCandidate ? '名作堂出演 · 优先候选' : (entry.value.age == null ? '年龄未知' : '${entry.value.age}岁')),
                  trailing: Text('${entry.value.movieCount}部'),
                )),
          ]),
        ),
      );
}

class _DetailGroup extends StatelessWidget {
  const _DetailGroup({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            ...children,
          ]),
        ),
      );
}

class _ReadOnlyError extends StatelessWidget {
  const _ReadOnlyError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(LucideIcons.circleAlert, size: 36),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton.icon(onPressed: onRetry, icon: const Icon(LucideIcons.refreshCw, size: 17), label: const Text('重试')),
          ]),
        ),
      );
}
