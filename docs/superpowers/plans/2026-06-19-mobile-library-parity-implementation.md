# Mobile Library Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Flutter mobile app match the desktop library's read-only behavior for video detail fallback, actor/code-prefix tiers, and video filter rules.

**Architecture:** Keep Flutter as a direct SQLite reader, add a Dart-side filter-settings and filter-evaluation layer, extend repository models with tier/source metadata, and let the UI render already-shaped read-only view models. Prefer local `processed_videos` rows when available, and synthesize indexed detail records from `actor_movies` and `code_prefix_movies` when a local row does not exist.

**Tech Stack:** Flutter, Dart, sqflite, path_provider, path, flutter_test, sqflite_common_ffi (dev dependency)

---

## File Map

**Create**

- `mobile_app/lib/src/database/filter_settings.dart`
- `mobile_app/lib/src/database/filter_settings_repository.dart`
- `mobile_app/lib/src/database/video_filter_service.dart`
- `mobile_app/test/database/filter_settings_repository_test.dart`
- `mobile_app/test/database/library_detail_repository_test.dart`
- `mobile_app/test/ui/library_parity_widgets_test.dart`

**Modify**

- `mobile_app/pubspec.yaml`
- `mobile_app/lib/src/database/database_storage.dart`
- `mobile_app/lib/src/database/video_detail.dart`
- `mobile_app/lib/src/database/actor_detail.dart`
- `mobile_app/lib/src/database/code_prefix_detail.dart`
- `mobile_app/lib/src/database/actor_list_item.dart`
- `mobile_app/lib/src/database/code_prefix_list_item.dart`
- `mobile_app/lib/src/database/video_library_repository.dart`
- `mobile_app/lib/src/database/actor_library_repository.dart`
- `mobile_app/lib/src/database/code_prefix_library_repository.dart`
- `mobile_app/lib/src/database/library_detail_repository.dart`
- `mobile_app/lib/src/ui/video_detail_screen.dart`
- `mobile_app/lib/src/ui/actor_detail_screen.dart`
- `mobile_app/lib/src/ui/code_prefix_detail_screen.dart`
- `mobile_app/lib/src/ui/actor_library_screen.dart`
- `mobile_app/lib/src/ui/code_prefix_library_screen.dart`

---

### Task 1: Add filter-settings loading and Dart-side filter evaluation

**Files:**

- Create: `mobile_app/lib/src/database/filter_settings.dart`
- Create: `mobile_app/lib/src/database/filter_settings_repository.dart`
- Create: `mobile_app/lib/src/database/video_filter_service.dart`
- Modify: `mobile_app/lib/src/database/database_storage.dart`
- Modify: `mobile_app/pubspec.yaml`
- Test: `mobile_app/test/database/filter_settings_repository_test.dart`

- [ ] **Step 1: Write the failing tests for filter-settings loading and rule evaluation**

```dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/src/database/filter_settings.dart';
import 'package:mobile_app/src/database/filter_settings_repository.dart';
import 'package:mobile_app/src/database/video_filter_service.dart';

void main() {
  group('FilterSettingsRepository', () {
    test('falls back to defaults when the settings file is missing', () async {
      final tempDir = await Directory.systemTemp.createTemp('filter-settings-missing');
      final repository = FilterSettingsRepository(
        settingsFilePath: '${tempDir.path}/video_filter_settings.json',
      );

      final settings = await repository.load();

      expect(settings.codeKeywords, isNotEmpty);
      expect(settings.titleKeywords, isNotEmpty);
      expect(settings.javtxtTagKeywords, isNotEmpty);
    });

    test('falls back to defaults when the settings file is invalid json', () async {
      final tempDir = await Directory.systemTemp.createTemp('filter-settings-invalid');
      final file = File('${tempDir.path}/video_filter_settings.json');
      await file.writeAsString('{ invalid json');

      final repository = FilterSettingsRepository(settingsFilePath: file.path);
      final settings = await repository.load();

      expect(settings.codeKeywords, isNotEmpty);
      expect(settings.titleKeywords, isNotEmpty);
      expect(settings.javtxtTagKeywords, isNotEmpty);
    });
  });

  group('VideoFilterService', () {
    const settings = FilterSettings(
      codeKeywords: ['FC2'],
      titleKeywords: ['VR'],
      javtxtTagKeywords: ['3D'],
    );

    test('hides rows that match code title or tag filters', () {
      final service = VideoFilterService(settings);
      final visible = service.filterRows([
        {
          'code': 'ABP-123',
          'display_title': 'Normal title',
          'javtxt_tags': 'Drama|Story',
        },
        {
          'code': 'FC2-999',
          'display_title': 'Normal title',
          'javtxt_tags': 'Drama|Story',
        },
        {
          'code': 'IPX-001',
          'display_title': 'VR sample title',
          'javtxt_tags': 'Drama|Story',
        },
        {
          'code': 'SSIS-002',
          'display_title': 'Normal title',
          'javtxt_tags': '3D|Fantasy',
        },
      ]);

      expect(visible, hasLength(1));
      expect(visible.single['code'], 'ABP-123');
    });
  });
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `flutter test test/database/filter_settings_repository_test.dart`

Expected: FAIL because `FilterSettings`, `FilterSettingsRepository`, and `VideoFilterService` do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

```dart
class FilterSettings {
  const FilterSettings({
    required this.codeKeywords,
    required this.titleKeywords,
    required this.javtxtTagKeywords,
  });

  final List<String> codeKeywords;
  final List<String> titleKeywords;
  final List<String> javtxtTagKeywords;

  static const defaults = FilterSettings(
    codeKeywords: ['FC2'],
    titleKeywords: ['VR'],
    javtxtTagKeywords: ['VR'],
  );
}
```

```dart
class FilterSettingsRepository {
  const FilterSettingsRepository({required this.settingsFilePath});

  final String settingsFilePath;

  Future<FilterSettings> load() async {
    final file = File(settingsFilePath);
    if (!await file.exists()) {
      return FilterSettings.defaults;
    }

    try {
      final json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      final rules = (json['rules'] as Map<String, dynamic>? ?? const {});
      return FilterSettings(
        codeKeywords: _normalize(rules['code']),
        titleKeywords: _normalize(rules['title']),
        javtxtTagKeywords: _normalize(rules['javtxt_tags']),
      );
    } catch (_) {
      return FilterSettings.defaults;
    }
  }
}
```

```dart
class VideoFilterService {
  const VideoFilterService(this.settings);

  final FilterSettings settings;

  List<Map<String, Object?>> filterRows(Iterable<Map<String, Object?>> rows) {
    return rows.where(isVisible).map((row) => Map<String, Object?>.from(row)).toList(growable: false);
  }

  bool isVisible(Map<String, Object?> row) {
    final code = '${row['code'] ?? ''}'.toLowerCase();
    final title = '${row['display_title'] ?? row['title'] ?? ''}'.toLowerCase();
    final tags = '${row['javtxt_tags'] ?? ''}'.toLowerCase();

    return !_matchesAny(code, settings.codeKeywords) &&
        !_matchesAny(title, settings.titleKeywords) &&
        !_matchesAny(tags, settings.javtxtTagKeywords);
  }
}
```

```dart
class DatabaseStorage {
  static const String databaseFileName = 'video_database.db';
  static const String filterSettingsFileName = 'video_filter_settings.json';

  Future<String> resolveFilterSettingsPath() async {
    final location = await _resolvePreferredDirectory();
    return p.join(location.directory.path, filterSettingsFileName);
  }
}
```

Add dev dependency:

```yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^6.0.0
  sqflite_common_ffi: ^2.3.4+4
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `flutter test test/database/filter_settings_repository_test.dart`

Expected: PASS with 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mobile_app/pubspec.yaml mobile_app/lib/src/database/database_storage.dart mobile_app/lib/src/database/filter_settings.dart mobile_app/lib/src/database/filter_settings_repository.dart mobile_app/lib/src/database/video_filter_service.dart mobile_app/test/database/filter_settings_repository_test.dart
git commit -m "feat: add mobile filter settings support"
```

### Task 2: Add ladder-tier metadata to list and detail models

**Files:**

- Modify: `mobile_app/lib/src/database/actor_detail.dart`
- Modify: `mobile_app/lib/src/database/code_prefix_detail.dart`
- Modify: `mobile_app/lib/src/database/actor_list_item.dart`
- Modify: `mobile_app/lib/src/database/code_prefix_list_item.dart`
- Modify: `mobile_app/lib/src/database/actor_library_repository.dart`
- Modify: `mobile_app/lib/src/database/code_prefix_library_repository.dart`
- Modify: `mobile_app/lib/src/database/library_detail_repository.dart`
- Test: `mobile_app/test/database/library_detail_repository_test.dart`

- [ ] **Step 1: Write the failing repository tests for ladder tiers**

```dart
test('fetchActorDetail includes ladder tier from ladder_entries', () async {
  final repository = await buildRepositoryWithFixtureDb({
    'actors': [
      {'name': 'Alice', 'birthday': '2000-01-01', 'age': '24', 'matched': 1},
    ],
    'actor_movies': [
      {'actor_name': 'Alice', 'code': 'ABP-123', 'title': 'Sample'},
    ],
    'ladder_entries': [
      {'board_key': 'actor', 'entity_type': 'actor', 'entity_name': 'Alice', 'tier': 'S'},
    ],
  });

  final detail = await repository.fetchActorDetail('Alice');

  expect(detail?.ladderTier, 'S');
});

test('searchPrefixes maps ladder tier onto list items', () async {
  final repository = await buildCodePrefixRepositoryWithFixtureDb({
    'code_prefix_movies': [
      {'prefix': 'IPX', 'code': 'IPX-001', 'title': 'Sample'},
    ],
    'ladder_entries': [
      {'board_key': 'code_prefix', 'entity_type': 'code_prefix', 'entity_name': 'IPX', 'tier': 'A'},
    ],
  });

  final result = await repository.searchPrefixes();

  expect(result.items.single.ladderTier, 'A');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `flutter test test/database/library_detail_repository_test.dart`

Expected: FAIL because ladder-tier fields are not present in models or queries.

- [ ] **Step 3: Write the minimal implementation**

```dart
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

  final String ladderTier;
}
```

```dart
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

  final String ladderTier;
}
```

```sql
LEFT JOIN ladder_entries le
  ON le.board_key = 'actor'
 AND le.entity_type = 'actor'
 AND le.entity_name = a.name
```

```sql
LEFT JOIN ladder_entries le
  ON le.board_key = 'code_prefix'
 AND le.entity_type = 'code_prefix'
 AND UPPER(le.entity_name) = UPPER(c.prefix)
```

```dart
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `flutter test test/database/library_detail_repository_test.dart`

Expected: PASS with ladder-tier assertions succeeding.

- [ ] **Step 5: Commit**

```bash
git add mobile_app/lib/src/database/actor_detail.dart mobile_app/lib/src/database/code_prefix_detail.dart mobile_app/lib/src/database/actor_list_item.dart mobile_app/lib/src/database/code_prefix_list_item.dart mobile_app/lib/src/database/actor_library_repository.dart mobile_app/lib/src/database/code_prefix_library_repository.dart mobile_app/lib/src/database/library_detail_repository.dart mobile_app/test/database/library_detail_repository_test.dart
git commit -m "feat: surface ladder tiers in mobile library data"
```

### Task 3: Implement local-first video detail fallback and filtered related-video lists

**Files:**

- Modify: `mobile_app/lib/src/database/video_detail.dart`
- Modify: `mobile_app/lib/src/database/video_library_repository.dart`
- Modify: `mobile_app/lib/src/database/actor_library_repository.dart`
- Modify: `mobile_app/lib/src/database/code_prefix_library_repository.dart`
- Modify: `mobile_app/lib/src/database/library_detail_repository.dart`
- Modify: `mobile_app/lib/src/database/filter_settings_repository.dart`
- Modify: `mobile_app/lib/src/database/video_filter_service.dart`
- Test: `mobile_app/test/database/library_detail_repository_test.dart`

- [ ] **Step 1: Write the failing tests for indexed-detail fallback and filtering-before-pagination**

```dart
test('fetchVideoDetail falls back to indexed rows when processed_videos is missing', () async {
  final repository = await buildRepositoryWithFixtureDb({
    'actor_movies': [
      {
        'actor_name': 'Alice',
        'code': 'IPX-001',
        'title': 'Indexed title',
        'author': 'Alice',
        'javtxt_release_date': '2024-01-02',
        'video_category': 'Drama',
      },
    ],
    'code_prefix_movies': [
      {
        'prefix': 'IPX',
        'code': 'IPX-001',
        'title': 'Indexed title',
        'author': 'Alice',
      },
    ],
  });

  final detail = await repository.fetchVideoDetail('IPX-001');

  expect(detail, isNotNull);
  expect(detail?.detailSource, VideoDetailSource.indexed);
  expect(detail?.storageLocation, isEmpty);
  expect(detail?.prefix, 'IPX');
});

test('searchVideos paginates visible rows after filter rules are applied', () async {
  final repository = await buildVideoRepositoryWithFixtureDbAndRules(
    rows: [
      {'code': 'FC2-001', 'title': 'Hidden'},
      {'code': 'ABP-001', 'title': 'Visible 1'},
      {'code': 'ABP-002', 'title': 'Visible 2'},
    ],
    rules: const FilterSettings(
      codeKeywords: ['FC2'],
      titleKeywords: [],
      javtxtTagKeywords: [],
    ),
  );

  final result = await repository.searchVideos(limit: 2, offset: 0);

  expect(result.totalCount, 2);
  expect(result.items.map((item) => item.code), ['ABP-001', 'ABP-002']);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `flutter test test/database/library_detail_repository_test.dart`

Expected: FAIL because `fetchVideoDetail()` only reads `processed_videos` and repositories paginate before applying any mobile filter rules.

- [ ] **Step 3: Write the minimal implementation**

```dart
enum VideoDetailSource {
  local,
  indexed,
}
```

```dart
Future<VideoDetail?> fetchVideoDetail(String code) async {
  final database = await _openDatabase();
  final localRow = await _fetchLocalVideoRow(database, code);
  if (localRow != null) {
    final actors = await _fetchVideoActors(database, code, fallbackAuthor: _read(localRow, 'author'));
    return VideoDetail.fromMap(localRow, actors: actors, detailSource: VideoDetailSource.local);
  }

  final indexedRow = await _fetchIndexedVideoRow(database, code);
  if (indexedRow == null) {
    return null;
  }

  final actors = await _fetchVideoActors(database, code, fallbackAuthor: _read(indexedRow, 'author'));
  return VideoDetail.fromMap(indexedRow, actors: actors, detailSource: VideoDetailSource.indexed);
}
```

```dart
final filteredRows = _videoFilterService.filterRows(itemRows.cast<Map<String, Object?>>());
final pageRows = filteredRows.skip(offset).take(limit).toList(growable: false);
```

```dart
final filteredVideos = _videoFilterService.filterRows(
  videos.map((item) => item.toMap()),
);
```

Implementation note:

- when building indexed fallback rows, normalize fields to the same keys used by `VideoDetail.fromMap`
- apply filtering to actor detail and code-prefix detail related video rows before mapping into `VideoListItem`
- compute `totalCount` from filtered rows, not raw SQL row count

- [ ] **Step 4: Run the test to verify it passes**

Run: `flutter test test/database/library_detail_repository_test.dart`

Expected: PASS with indexed fallback and filtered pagination assertions succeeding.

- [ ] **Step 5: Commit**

```bash
git add mobile_app/lib/src/database/video_detail.dart mobile_app/lib/src/database/video_library_repository.dart mobile_app/lib/src/database/actor_library_repository.dart mobile_app/lib/src/database/code_prefix_library_repository.dart mobile_app/lib/src/database/library_detail_repository.dart mobile_app/lib/src/database/filter_settings_repository.dart mobile_app/lib/src/database/video_filter_service.dart mobile_app/test/database/library_detail_repository_test.dart
git commit -m "feat: align mobile detail fallback and filtering"
```

### Task 4: Render source badges and ladder tiers in Flutter UI

**Files:**

- Modify: `mobile_app/lib/src/ui/video_detail_screen.dart`
- Modify: `mobile_app/lib/src/ui/actor_detail_screen.dart`
- Modify: `mobile_app/lib/src/ui/code_prefix_detail_screen.dart`
- Modify: `mobile_app/lib/src/ui/actor_library_screen.dart`
- Modify: `mobile_app/lib/src/ui/code_prefix_library_screen.dart`
- Test: `mobile_app/test/ui/library_parity_widgets_test.dart`

- [ ] **Step 1: Write the failing widget tests for source/tier badges**

```dart
testWidgets('video detail screen shows an Indexed badge for indexed-only records', (tester) async {
  await tester.pumpWidget(buildVideoDetailScreenFixture(detailSource: VideoDetailSource.indexed));

  expect(find.text('Indexed'), findsOneWidget);
  expect(find.textContaining('storage'), findsNothing);
});

testWidgets('actor library card shows ladder tier when present', (tester) async {
  await tester.pumpWidget(buildActorCardFixture(ladderTier: 'S'));

  expect(find.text('S'), findsOneWidget);
});

testWidgets('code prefix detail hero shows ladder tier when present', (tester) async {
  await tester.pumpWidget(buildCodePrefixDetailFixture(ladderTier: 'A'));

  expect(find.text('A'), findsOneWidget);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `flutter test test/ui/library_parity_widgets_test.dart`

Expected: FAIL because the current UI does not render detail-source or ladder-tier badges.

- [ ] **Step 3: Write the minimal implementation**

```dart
if (detail.detailSource == VideoDetailSource.indexed)
  _InfoBadge(
    icon: LucideIcons.database,
    label: 'Indexed',
  )
else
  _InfoBadge(
    icon: LucideIcons.folderOpen,
    label: 'Local',
  )
```

```dart
if (detail.ladderTier.isNotEmpty)
  _ActorFactChip(
    label: 'Tier',
    value: detail.ladderTier,
  )
```

```dart
if (item.ladderTier.isNotEmpty)
  _ActorBadge(
    text: item.ladderTier,
    foreground: const Color(0xFF5A382F),
    background: const Color(0xFFEAD8CC),
  )
```

```dart
if (detail.detailSource == VideoDetailSource.local && detail.storageLocation.isNotEmpty) ...[
  // existing storage card
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `flutter test test/ui/library_parity_widgets_test.dart`

Expected: PASS with all source/tier badge assertions succeeding.

- [ ] **Step 5: Run full verification**

Run:

```bash
flutter test
flutter analyze
```

Expected:

- `flutter test` reports all tests passed
- `flutter analyze` reports no issues found

- [ ] **Step 6: Commit**

```bash
git add mobile_app/lib/src/ui/video_detail_screen.dart mobile_app/lib/src/ui/actor_detail_screen.dart mobile_app/lib/src/ui/code_prefix_detail_screen.dart mobile_app/lib/src/ui/actor_library_screen.dart mobile_app/lib/src/ui/code_prefix_library_screen.dart mobile_app/test/ui/library_parity_widgets_test.dart mobile_app/test/widget_test.dart
git commit -m "feat: render mobile parity metadata in library ui"
```

## Self-Review

Spec coverage check:

- non-local video detail fallback is covered in Task 3
- actor/code-prefix ladder tiers are covered in Tasks 2 and 4
- desktop-aligned filter settings loading and evaluation are covered in Tasks 1 and 3
- filtered related-video lists and filtered pagination are covered in Task 3
- UI surfacing of source/tier metadata is covered in Task 4

Placeholder scan:

- no TBD/TODO placeholders remain
- every task includes concrete files, commands, and implementation snippets

Type consistency check:

- filter settings use `codeKeywords`, `titleKeywords`, `javtxtTagKeywords` consistently
- detail-source metadata uses `VideoDetailSource`
- ladder-tier metadata uses `ladderTier` consistently across models and UI
