import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/src/database/filter_settings.dart';
import 'package:mobile_app/src/database/filter_settings_repository.dart';
import 'package:mobile_app/src/database/video_filter_service.dart';

void main() {
  group('FilterSettingsRepository', () {
    test('falls back to desktop defaults when the settings file is missing', () async {
      final tempDir = await Directory.systemTemp.createTemp('filter-settings-missing');
      final repository = FilterSettingsRepository(
        settingsFilePath: '${tempDir.path}/video_filter_settings.json',
      );

      final settings = await repository.load();

      expect(settings.codeKeywords, isEmpty);
      expect(settings.titleKeywords, contains('VR'));
      expect(settings.javtxtTagKeywords, contains('VR'));
    });

    test('falls back to desktop defaults when the settings file is invalid json', () async {
      final tempDir = await Directory.systemTemp.createTemp('filter-settings-invalid');
      final file = File('${tempDir.path}/video_filter_settings.json');
      await file.writeAsString('{ invalid json');

      final repository = FilterSettingsRepository(settingsFilePath: file.path);
      final settings = await repository.load();

      expect(settings.codeKeywords, isEmpty);
      expect(settings.titleKeywords, contains('VR'));
      expect(settings.javtxtTagKeywords, contains('VR'));
    });

    test('normalizes duplicate values loaded from the settings file', () async {
      final tempDir = await Directory.systemTemp.createTemp('filter-settings-duplicate');
      final file = File('${tempDir.path}/video_filter_settings.json');
      await file.writeAsString('''
{
  "rules": {
    "code": ["FC2", "fc2", ""],
    "title": ["VR", "vr", "合集"],
    "javtxt_tags": ["3D", "3d"]
  }
}
''');

      final repository = FilterSettingsRepository(settingsFilePath: file.path);
      final settings = await repository.load();

      expect(settings.codeKeywords, <String>['FC2']);
      expect(settings.titleKeywords, <String>['VR', '合集']);
      expect(settings.javtxtTagKeywords, <String>['3D']);
    });
  });

  group('VideoFilterService', () {
    const settings = FilterSettings(
      codeKeywords: <String>['FC2'],
      titleKeywords: <String>['VR'],
      javtxtTagKeywords: <String>['3D'],
    );

    test('hides rows that match code title or tag filters', () {
      const service = VideoFilterService(settings);
      final visible = service.filterRows([
        <String, Object?>{
          'code': 'ABP-123',
          'display_title': 'Normal title',
          'javtxt_tags': 'Drama|Story',
          'javtxt_title': 'Normal title',
        },
        <String, Object?>{
          'code': 'FC2-999',
          'display_title': 'Normal title',
          'javtxt_tags': 'Drama|Story',
          'javtxt_title': 'Normal title',
        },
        <String, Object?>{
          'code': 'IPX-001',
          'display_title': 'VR sample title',
          'javtxt_tags': 'Drama|Story',
          'javtxt_title': 'VR sample title',
        },
        <String, Object?>{
          'code': 'SSIS-002',
          'display_title': 'Normal title',
          'javtxt_tags': '3D|Fantasy',
          'javtxt_title': 'Normal title',
        },
      ]);

      expect(visible, hasLength(1));
      expect(visible.single['code'], 'ABP-123');
    });

    test('keeps pre-enrichment rows visible even when title keywords match', () {
      const service = VideoFilterService(settings);

      expect(
        service.isVisible(<String, Object?>{
          'code': 'IPX-003',
          'title': 'VR sample title',
          'javtxt_tags': '',
          'javtxt_enrichment_status': '',
        }),
        isTrue,
      );
    });
  });
}
