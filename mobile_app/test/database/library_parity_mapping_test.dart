import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/src/database/actor_detail.dart';
import 'package:mobile_app/src/database/actor_list_item.dart';
import 'package:mobile_app/src/database/code_prefix_detail.dart';
import 'package:mobile_app/src/database/code_prefix_list_item.dart';
import 'package:mobile_app/src/database/indexed_video_detail_row.dart';
import 'package:mobile_app/src/database/video_detail.dart';

void main() {
  test('buildIndexedVideoDetailRow merges actor and prefix rows for fallback detail', () {
    final row = buildIndexedVideoDetailRow(
      'IPX-001',
      actorMovieRow: <String, Object?>{
        'title': 'Indexed title',
        'author': 'Alice',
        'javtxt_release_date': '2024-01-02',
        'video_category': 'Drama',
        'javtxt_tags': 'Story',
      },
      codePrefixMovieRow: <String, Object?>{
        'prefix': 'IPX',
        'title': 'Prefix title',
      },
      codePrefixEnrichmentRow: <String, Object?>{
        'javtxt_enrichment_status': 'Complete',
      },
    );

    expect(row, isNotNull);
    expect(row?['code'], 'IPX-001');
    expect(row?['display_title'], 'Indexed title');
    expect(row?['author'], 'Alice');
    expect(row?['storage_location'], '');
    expect(row?['code_prefix'], 'IPX');
    expect(row?['enrichment_status'], 'Complete');
  });

  test('VideoDetail.fromMap keeps detail source metadata', () {
    final detail = VideoDetail.fromMap(
      <String, Object?>{
        'code': 'IPX-001',
        'display_title': 'Indexed title',
        'author': 'Alice',
        'duration': '',
        'size': '',
        'storage_location': '',
        'display_release_date': '2024-01-02',
        'maker': '',
        'publisher': '',
        'video_category': 'Drama',
        'enrichment_status': 'Complete',
        'description': '',
        'javtxt_tags': 'Story',
        'code_prefix': 'IPX',
      },
      actors: const <String>['Alice'],
      detailSource: VideoDetailSource.indexed,
    );

    expect(detail.detailSource, VideoDetailSource.indexed);
    expect(detail.prefix, 'IPX');
  });

  test('ActorDetail.fromMap reads ladder tier', () {
    final detail = ActorDetail.fromMap(
      <String, Object?>{
        'name': 'Alice',
        'birthday': '2000-01-01',
        'age': '24',
        'matched': 1,
        'movie_count': 8,
        'latest_release_date': '2024-05-20',
        'ladder_tier': 'S',
      },
      videos: const [],
    );

    expect(detail.ladderTier, 'S');
  });

  test('CodePrefixDetail.fromMap reads ladder tier', () {
    final detail = CodePrefixDetail.fromMap(
      <String, Object?>{
        'prefix': 'IPX',
        'movie_count': 12,
        'latest_release_date': '2024-05-20',
        'sample_category': 'Drama',
        'enrichment_status': 'Complete',
        'indexed_video_count': 66,
        'ladder_tier': 'A',
      },
      videos: const [],
    );

    expect(detail.ladderTier, 'A');
  });

  test('ActorListItem and CodePrefixListItem read ladder tiers', () {
    final actor = ActorListItem.fromMap(
      <String, Object?>{
        'name': 'Alice',
        'birthday': '',
        'age': '',
        'matched': 1,
        'movie_count': 3,
        'latest_release_date': '2024-05-20',
        'sample_category': '',
        'sample_code': 'ABP-123',
        'sample_title': 'Sample',
        'ladder_tier': 'S',
      },
    );
    final prefix = CodePrefixListItem.fromMap(
      <String, Object?>{
        'prefix': 'IPX',
        'movie_count': 3,
        'latest_release_date': '2024-05-20',
        'sample_category': '',
        'sample_code': 'IPX-001',
        'sample_title': 'Sample',
        'sample_author': 'Alice',
        'enrichment_status': 'Complete',
        'indexed_video_count': 8,
        'ladder_tier': 'A',
      },
    );

    expect(actor.ladderTier, 'S');
    expect(prefix.ladderTier, 'A');
  });
}
