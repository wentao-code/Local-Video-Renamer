class FilterSettings {
  const FilterSettings({
    required this.codeKeywords,
    required this.titleKeywords,
    required this.javtxtTagKeywords,
  });

  final List<String> codeKeywords;
  final List<String> titleKeywords;
  final List<String> javtxtTagKeywords;

  static const FilterSettings defaults = FilterSettings(
    codeKeywords: <String>[],
    titleKeywords: <String>[
      'VR',
      '\u5408\u96c6',
      '\u7cbe\u9009\u5408\u96c6',
      '\u56db\u5c0f\u65f6\u4ee5\u4e0a\u4f5c\u54c1',
      '16\u6642\u9593\u4ee5\u4e0a',
      '16\u6642\u9593\u4ee5\u4e0a\u4f5c\u54c1',
      '16\u65f6\u95f4\u4ee5\u4e0a',
      '16\u65f6\u95f4\u4ee5\u4e0a\u4f5c\u54c1',
      '16\u5c0f\u65f6\u4ee5\u4e0a',
      '16\u5c0f\u65f6\u4ee5\u4e0a\u4f5c\u54c1',
      '\u798f\u888b',
    ],
    javtxtTagKeywords: <String>[
      'VR',
      '\u5408\u96c6',
      '\u7cbe\u9009\u5408\u96c6',
      '\u56db\u5c0f\u65f6\u4ee5\u4e0a\u4f5c\u54c1',
      '16\u6642\u9593\u4ee5\u4e0a',
      '16\u6642\u9593\u4ee5\u4e0a\u4f5c\u54c1',
      '16\u65f6\u95f4\u4ee5\u4e0a',
      '16\u65f6\u95f4\u4ee5\u4e0a\u4f5c\u54c1',
      '16\u5c0f\u65f6\u4ee5\u4e0a',
      '16\u5c0f\u65f6\u4ee5\u4e0a\u4f5c\u54c1',
      '\u798f\u888b',
    ],
  );
}
