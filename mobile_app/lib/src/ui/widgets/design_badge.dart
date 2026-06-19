import 'package:flutter/material.dart';

import '../theme/app_design.dart';

class DesignBadge extends StatelessWidget {
  const DesignBadge({
    super.key,
    required this.text,
    required this.foreground,
    required this.background,
    this.borderColor,
    this.padding = const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
  });

  factory DesignBadge.tone({
    Key? key,
    required String text,
    required LibraryTone tone,
  }) {
    return DesignBadge(
      key: key,
      text: text,
      foreground: AppDesign.toneForeground(tone),
      background: AppDesign.toneSurface(tone),
      borderColor: AppDesign.toneForeground(tone).withValues(alpha: 0.12),
    );
  }

  factory DesignBadge.hero({
    Key? key,
    required String text,
  }) {
    return DesignBadge(
      key: key,
      text: text,
      foreground: Colors.white,
      background: Colors.white.withValues(alpha: 0.12),
      borderColor: Colors.white.withValues(alpha: 0.16),
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
    );
  }

  final String text;
  final Color foreground;
  final Color background;
  final Color? borderColor;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(AppDesign.chipRadius),
        border: borderColor == null ? null : Border.all(color: borderColor!),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: foreground,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.1,
            ),
      ),
    );
  }
}
