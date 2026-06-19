import 'dart:convert';
import 'dart:io';

import 'filter_settings.dart';

class FilterSettingsRepository {
  const FilterSettingsRepository({
    required this.settingsFilePath,
  });

  final String settingsFilePath;

  Future<FilterSettings> load() async {
    final file = File(settingsFilePath);
    if (!await file.exists()) {
      return FilterSettings.defaults;
    }

    try {
      final payload = jsonDecode(await file.readAsString());
      if (payload is! Map<String, dynamic>) {
        return FilterSettings.defaults;
      }
      final rules = payload['rules'];
      if (rules is! Map<String, dynamic>) {
        return FilterSettings.defaults;
      }
      return FilterSettings(
        codeKeywords: _normalize(rules['code']),
        titleKeywords: _normalize(rules['title']),
        javtxtTagKeywords: _normalize(rules['javtxt_tags']),
      );
    } catch (_) {
      return FilterSettings.defaults;
    }
  }

  List<String> _normalize(Object? values) {
    final source = switch (values) {
      String single => <Object?>[single],
      List<Object?> list => list,
      _ => const <Object?>[],
    };

    final normalized = <String>[];
    final seen = <String>{};
    for (final value in source) {
      final keyword = '$value'.trim();
      if (keyword.isEmpty) {
        continue;
      }
      final lowered = keyword.toLowerCase();
      if (!seen.add(lowered)) {
        continue;
      }
      normalized.add(keyword);
    }
    return normalized;
  }
}
