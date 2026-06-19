import 'package:flutter/material.dart';

import 'actor_detail_screen.dart';
import 'code_prefix_detail_screen.dart';
import 'video_detail_screen.dart';

PageRoute<T> _buildFadeSlideRoute<T>(Widget page) {
  return PageRouteBuilder<T>(
    pageBuilder: (context, animation, secondaryAnimation) => page,
    transitionDuration: const Duration(milliseconds: 280),
    reverseTransitionDuration: const Duration(milliseconds: 220),
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      final curved = CurvedAnimation(
        parent: animation,
        curve: Curves.easeOutCubic,
        reverseCurve: Curves.easeInCubic,
      );
      return FadeTransition(
        opacity: curved,
        child: SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(0, 0.03),
            end: Offset.zero,
          ).animate(curved),
          child: child,
        ),
      );
    },
  );
}

Future<void> openVideoDetail(
  BuildContext context, {
  required String databasePath,
  required String code,
  bool replaceCurrent = false,
}) {
  final route = _buildFadeSlideRoute<void>(
    VideoDetailScreen(
      databasePath: databasePath,
      videoCode: code,
    ),
  );

  if (replaceCurrent) {
    return Navigator.of(context).pushReplacement<void, void>(route);
  }

  return Navigator.of(context).push(route);
}

Future<void> openActorDetail(
  BuildContext context, {
  required String databasePath,
  required String actorName,
  bool replaceCurrent = false,
}) {
  final route = _buildFadeSlideRoute<void>(
    ActorDetailScreen(
      databasePath: databasePath,
      actorName: actorName,
    ),
  );

  if (replaceCurrent) {
    return Navigator.of(context).pushReplacement<void, void>(route);
  }

  return Navigator.of(context).push(route);
}

Future<void> openCodePrefixDetail(
  BuildContext context, {
  required String databasePath,
  required String prefix,
  bool replaceCurrent = false,
}) {
  final route = _buildFadeSlideRoute<void>(
    CodePrefixDetailScreen(
      databasePath: databasePath,
      prefix: prefix,
    ),
  );

  if (replaceCurrent) {
    return Navigator.of(context).pushReplacement<void, void>(route);
  }

  return Navigator.of(context).push(route);
}
