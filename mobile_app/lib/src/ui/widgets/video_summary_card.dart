import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../../database/video_list_item.dart';
import 'video_cover_thumbnail.dart';

class VideoSummaryCard extends StatelessWidget {
  const VideoSummaryCard({
    super.key,
    required this.item,
    this.onTap,
  });

  final VideoListItem item;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final metaValues = <String>[
      if (item.releaseDate.isNotEmpty) '日期 ${item.releaseDate}',
      if (item.duration.isNotEmpty) '时长 ${item.duration}',
      if (item.size.isNotEmpty) '大小 ${item.size}',
    ];

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              VideoCoverThumbnail(
                code: item.code,
                title: item.title,
                category: item.videoCategory,
                maker: item.maker,
                height: 152,
                width: 108,
                heroTag: 'video-cover-${item.code}',
                borderRadius: 20,
              ),
              const SizedBox(width: 16),
              Expanded(
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
                                item.code.isEmpty ? '未命名编号' : item.code,
                                style: GoogleFonts.jetBrainsMono(
                                  textStyle: theme.textTheme.titleLarge?.copyWith(
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 0.6,
                                  ),
                                ),
                              ),
                              if (item.enrichmentStatus.isNotEmpty)
                                _Badge(
                                  text: item.enrichmentStatus,
                                  foreground: const Color(0xFF5A382F),
                                  background: const Color(0xFFEAD8CC),
                                ),
                              if (item.videoCategory.isNotEmpty)
                                _Badge(
                                  text: item.videoCategory,
                                  foreground: const Color(0xFF2D5F50),
                                  background: const Color(0xFFDCEFE9),
                                ),
                            ],
                          ),
                        ),
                        if (onTap != null)
                          const Padding(
                            padding: EdgeInsets.only(left: 12, top: 2),
                            child: Icon(
                              LucideIcons.chevronRight,
                              color: Color(0xFFAA9A8D),
                              size: 18,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      item.title.isEmpty ? item.code : item.title,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                        height: 1.35,
                      ),
                    ),
                    if (item.author.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(
                        item.author,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: const Color(0xFF5C5752),
                        ),
                      ),
                    ],
                    if (metaValues.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Text(
                        metaValues.join('  ·  '),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: const Color(0xFF6A625C),
                        ),
                      ),
                    ],
                    if (item.storageLocation.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      _DetailLine(
                        label: '存储位置',
                        value: item.storageLocation,
                        highlight: true,
                      ),
                    ],
                    if (item.maker.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      _DetailLine(label: '制作商', value: item.maker),
                    ],
                    if (item.publisher.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      _DetailLine(label: '发行商', value: item.publisher),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DetailLine extends StatelessWidget {
  const _DetailLine({
    required this.label,
    required this.value,
    this.highlight = false,
  });

  final String label;
  final String value;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final valueColor = highlight ? const Color(0xFF8E3B2E) : const Color(0xFF3E3935);
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

class _Badge extends StatelessWidget {
  const _Badge({
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
