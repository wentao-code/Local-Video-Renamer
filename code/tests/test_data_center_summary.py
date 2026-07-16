import gc
import json
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
)
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.data.database_handler import VideoDatabase
from app.core.snapshot_store import SnapshotStore
from app.services.library import DataCenterService
from app.services.video import (
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_SINGLE,
)
from app.services.video import VideoFilterService


def _build_complete_summary_stub(version):
    label = f'summary-{version}'
    source_summary = {
        'label': label,
        'total_count': version,
        'completed_count': version,
        'success_count': version,
        'pending_count': 0,
        'failed_count': 0,
        'no_search_count': 0,
        'no_detail_count': 0,
        'progress_percent': 100.0,
        'count_label': 'done',
        'pending_label': 'pending',
        'list_kind': 'video',
        'issue_groups': [],
    }
    actor_source_summary = dict(source_summary, list_kind='actor')
    return {
        'video_library': {
            'label': 'video',
            'sources': {
                AVFAN_VIDEO_SOURCE: dict(source_summary),
                JAVTXT_VIDEO_SOURCE: dict(source_summary),
                SUPPLEMENT_TASK_SOURCE: dict(source_summary),
            },
        },
        'code_prefix_library': {
            'label': 'code',
            'sources': {
                AVFAN_VIDEO_SOURCE: dict(source_summary, list_kind='code_prefix'),
                JAVTXT_VIDEO_SOURCE: dict(source_summary, list_kind='code_prefix'),
                SUPPLEMENT_TASK_SOURCE: dict(source_summary, list_kind='code_prefix'),
            },
        },
        'actor_library': {
            'label': 'actor',
            'sources': {
                AVFAN_VIDEO_SOURCE: dict(actor_source_summary),
                JAVTXT_VIDEO_SOURCE: dict(actor_source_summary),
                BINGHUO_ACTOR_SOURCE: dict(actor_source_summary),
                BAOMU_ACTOR_SOURCE: dict(actor_source_summary),
                SUPPLEMENT_TASK_SOURCE: dict(actor_source_summary),
            },
        },
    }


class DataCenterSummarySplitCountsTest(unittest.TestCase):
    def test_supplement_summary_reports_pending_candidates_for_all_libraries(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Missing Actor",
                author="",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
            )
            self._seed_processed_video(
                db_path,
                code="AAA-002",
                title="No Search Video",
                author="",
                release_date="2024-01-02",
                status=NO_SEARCH_RESULTS_STATUS,
            )

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie("AAA-001", "Missing Actor", "", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "No Search Video", "", "2024-01-02", NO_SEARCH_RESULTS_STATUS),
                ],
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies(
                "Actor A",
                [
                    self._build_library_movie("AAA-001", "Missing Actor", "", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "No Search Video", "", "2024-01-02", NO_SEARCH_RESULTS_STATUS),
                ],
            )

            summary = DataCenterService(db).get_summary()

            video_summary = summary["video_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(video_summary["total_count"], 2)
            self.assertEqual(video_summary["pending_count"], 2)
            self.assertEqual(video_summary["count_label"], "待补充")

            code_prefix_summary = summary["code_prefix_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(code_prefix_summary["total_count"], 2)
            self.assertEqual(code_prefix_summary["pending_count"], 2)
            self.assertEqual(code_prefix_summary["list_kind"], "video")
            self.assertEqual(code_prefix_summary["issue_groups"][0]["key"], "pending")
            self.assertEqual(
                {item["code"] for item in code_prefix_summary["issue_groups"][0]["items"]},
                {"AAA-001", "AAA-002"},
            )

            actor_summary = summary["actor_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(actor_summary["total_count"], 2)
            self.assertEqual(actor_summary["pending_count"], 2)
            self.assertEqual(actor_summary["list_kind"], "video")
            self.assertEqual(actor_summary["issue_groups"][0]["key"], "pending")
            self.assertEqual(
                {item["code"] for item in actor_summary["issue_groups"][0]["items"]},
                {"AAA-001", "AAA-002"},
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_supplement_summary_excludes_javtxt_filtered_videos(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="SKIP-001",
                title="Filtered Missing Actor",
                author="",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
            )
            self._seed_processed_video(
                db_path,
                code="AAA-002",
                title="Visible Missing Actor",
                author="",
                release_date="2024-01-02",
                status=ENRICHED_STATUS,
                movie_id="m2",
                url="https://example.com/2",
            )

            db.replace_code_prefix_movies(
                "SKIP",
                [
                    self._build_library_movie("SKIP-001", "Filtered Missing Actor", "", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                ],
            )
            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie("AAA-002", "Visible Missing Actor", "", "2024-01-02", ENRICHED_STATUS, "m2", "https://example.com/2"),
                ],
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies(
                "Actor A",
                [
                    self._build_library_movie("SKIP-001", "Filtered Missing Actor", "", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "Visible Missing Actor", "", "2024-01-02", ENRICHED_STATUS, "m2", "https://example.com/2"),
                ],
            )

            filter_service = VideoFilterService(
                settings_loader=lambda: {
                    "rules": {
                        "code": ["SKIP"],
                        "title": [],
                        "javtxt_tags": [],
                        "co_star_code": [],
                    }
                }
            )
            summary = DataCenterService(db, video_filter_service=filter_service).get_summary()

            video_summary = summary["video_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(video_summary["total_count"], 1)
            self.assertEqual(video_summary["pending_count"], 1)
            self.assertEqual(
                {item["code"] for item in video_summary["issue_groups"][0]["items"]},
                {"AAA-002"},
            )

            code_prefix_summary = summary["code_prefix_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(code_prefix_summary["total_count"], 1)
            self.assertEqual(code_prefix_summary["pending_count"], 1)
            self.assertEqual(
                {item["code"] for item in code_prefix_summary["issue_groups"][0]["items"]},
                {"AAA-002"},
            )

            actor_summary = summary["actor_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(actor_summary["total_count"], 1)
            self.assertEqual(actor_summary["pending_count"], 1)
            self.assertEqual(
                {item["code"] for item in actor_summary["issue_groups"][0]["items"]},
                {"AAA-002"},
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_supplement_summary_includes_success_and_terminal_counts(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-011",
                title="Missing Actor",
                author="",
                release_date="2024-01-11",
                status=ENRICHED_STATUS,
                movie_id="m11",
                url="https://example.com/11",
            )
            self._seed_processed_video(
                db_path,
                code="AAA-012",
                title="Resolved Video",
                author="Actor B",
                release_date="2024-01-12",
                status=ENRICHED_STATUS,
                movie_id="m12",
                url="https://example.com/12",
            )
            self._seed_processed_video(
                db_path,
                code="AAA-013",
                title="No Search Video",
                author="",
                release_date="2024-01-13",
                status=NO_SEARCH_RESULTS_STATUS,
            )
            db.save_video_supplement_status("AAA-012", ENRICHED_STATUS)
            db.save_video_supplement_status("AAA-013", NO_SEARCH_RESULTS_STATUS)

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie("AAA-011", "Missing Actor", "", "2024-01-11", ENRICHED_STATUS, "m11", "https://example.com/11"),
                    self._build_library_movie("AAA-012", "Resolved Video", "Actor B", "2024-01-12", ENRICHED_STATUS, "m12", "https://example.com/12"),
                    self._build_library_movie("AAA-013", "No Search Video", "", "2024-01-13", NO_SEARCH_RESULTS_STATUS),
                ],
            )
            db.save_code_prefix_movie_supplement_status("AAA", "AAA-012", ENRICHED_STATUS)
            db.save_code_prefix_movie_supplement_status("AAA", "AAA-013", NO_SEARCH_RESULTS_STATUS)

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies(
                "Actor A",
                [
                    self._build_library_movie("AAA-011", "Missing Actor", "", "2024-01-11", ENRICHED_STATUS, "m11", "https://example.com/11"),
                    self._build_library_movie("AAA-012", "Resolved Video", "Actor A", "2024-01-12", ENRICHED_STATUS, "m12", "https://example.com/12"),
                    self._build_library_movie("AAA-013", "No Search Video", "", "2024-01-13", NO_SEARCH_RESULTS_STATUS),
                ],
            )
            db.save_actor_movie_supplement_status("Actor A", "AAA-012", ENRICHED_STATUS)
            db.save_actor_movie_supplement_status("Actor A", "AAA-013", NO_SEARCH_RESULTS_STATUS)

            summary = DataCenterService(db).get_summary()

            video_summary = summary["video_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(video_summary["total_count"], 3)
            self.assertEqual(video_summary["completed_count"], 2)
            self.assertEqual(video_summary["success_count"], 1)
            self.assertEqual(video_summary["pending_count"], 1)
            self.assertEqual(video_summary["no_search_count"], 1)
            self.assertEqual([group["key"] for group in video_summary["issue_groups"]], ["pending", "no_search"])

            code_prefix_summary = summary["code_prefix_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(code_prefix_summary["total_count"], 3)
            self.assertEqual(code_prefix_summary["completed_count"], 2)
            self.assertEqual(code_prefix_summary["success_count"], 1)
            self.assertEqual(code_prefix_summary["pending_count"], 1)
            self.assertEqual(code_prefix_summary["no_search_count"], 1)
            self.assertEqual([group["key"] for group in code_prefix_summary["issue_groups"]], ["pending", "no_search"])

            actor_summary = summary["actor_library"]["sources"][SUPPLEMENT_TASK_SOURCE]
            self.assertEqual(actor_summary["total_count"], 3)
            self.assertEqual(actor_summary["completed_count"], 2)
            self.assertEqual(actor_summary["success_count"], 1)
            self.assertEqual(actor_summary["pending_count"], 1)
            self.assertEqual(actor_summary["no_search_count"], 1)
            self.assertEqual([group["key"] for group in actor_summary["issue_groups"]], ["pending", "no_search"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_javtxt_summary_keeps_no_detail_separate_from_no_search(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Resolved Video",
                author="Actor A",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
            )
            self._seed_processed_video(
                db_path,
                code="AAA-002",
                title="No Search Video",
                author="Actor A",
                release_date="2024-01-02",
                status=NO_SEARCH_RESULTS_STATUS,
            )
            self._seed_processed_video(
                db_path,
                code="AAA-003",
                title="No Detail Video",
                author="Actor A",
                release_date="2024-01-03",
                status=NO_VIDEO_DETAIL_STATUS,
            )

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie("AAA-001", "Resolved Video", "Actor A", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "No Search Video", "Actor A", "2024-01-02", NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie("AAA-003", "No Detail Video", "Actor A", "2024-01-03", NO_VIDEO_DETAIL_STATUS),
                ],
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies(
                "Actor A",
                [
                    self._build_library_movie("AAA-001", "Resolved Video", "Actor A", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "No Search Video", "Actor A", "2024-01-02", NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie("AAA-003", "No Detail Video", "Actor A", "2024-01-03", NO_VIDEO_DETAIL_STATUS),
                ],
            )

            service = DataCenterService(db)
            summary = service.get_summary()

            video_summary = summary["video_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(video_summary["success_count"], 1)
            self.assertEqual(video_summary["no_search_count"], 1)
            self.assertEqual(video_summary["no_detail_count"], 1)
            self.assertEqual(video_summary["list_kind"], "video")
            self.assertEqual(
                video_summary["issue_groups"],
                [
                    {
                        "key": "no_search",
                        "label": "无结果",
                        "items": [
                            {
                                "code": "AAA-002",
                                "title": "No Search Video",
                                "author": "Actor A",
                            }
                        ],
                    },
                    {
                        "key": "no_detail",
                        "label": "无详情",
                        "items": [
                            {
                                "code": "AAA-003",
                                "title": "No Detail Video",
                                "author": "Actor A",
                            }
                        ],
                    },
                ],
            )

            code_prefix_summary = summary["code_prefix_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(code_prefix_summary["success_count"], 1)
            self.assertEqual(code_prefix_summary["no_search_count"], 1)
            self.assertEqual(code_prefix_summary["no_detail_count"], 1)
            self.assertEqual(code_prefix_summary["list_kind"], "video")
            self.assertEqual(
                code_prefix_summary["issue_groups"],
                [
                    {
                        "key": "no_search",
                        "label": "无结果",
                        "items": [
                            {
                                "code": "AAA-002",
                                "title": "No Search Video",
                                "author": "Actor A",
                            }
                        ],
                    },
                    {
                        "key": "no_detail",
                        "label": "无详情",
                        "items": [
                            {
                                "code": "AAA-003",
                                "title": "No Detail Video",
                                "author": "Actor A",
                            }
                        ],
                    },
                ],
            )

            actor_summary = summary["actor_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(actor_summary["success_count"], 1)
            self.assertEqual(actor_summary["no_search_count"], 1)
            self.assertEqual(actor_summary["no_detail_count"], 1)
            self.assertEqual(actor_summary["list_kind"], "video")
            self.assertEqual(
                actor_summary["issue_groups"],
                [
                    {
                        "key": "no_search",
                        "label": "无结果",
                        "items": [
                            {
                                "code": "AAA-002",
                                "title": "No Search Video",
                                "author": "Actor A",
                            }
                        ],
                    },
                    {
                        "key": "no_detail",
                        "label": "无详情",
                        "items": [
                            {
                                "code": "AAA-003",
                                "title": "No Detail Video",
                                "author": "Actor A",
                            }
                        ],
                    },
                ],
            )

            del summary
            del service
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_javtxt_summary_deduplicates_same_video_code_across_multiple_actors(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Resolved Video",
                author="Actor A Actor B",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [("Actor A",), ("Actor B",)],
                )
                conn.commit()

            shared_movie = self._build_library_movie(
                "AAA-001",
                "Resolved Video",
                "Actor A Actor B",
                "2024-01-01",
                ENRICHED_STATUS,
                "m1",
                "https://example.com/1",
            )
            db.replace_actor_movies("Actor A", [shared_movie])
            db.replace_actor_movies("Actor B", [shared_movie])

            summary = DataCenterService(db).get_summary()
            actor_summary = summary["actor_library"]["sources"][JAVTXT_VIDEO_SOURCE]

            self.assertEqual(actor_summary["total_count"], 1)
            self.assertEqual(actor_summary["success_count"], 1)
            self.assertEqual(actor_summary["pending_count"], 0)

            del summary
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_filtered_videos_are_excluded_from_video_based_data_center_stats(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Visible Video",
                author="Actor A",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
                avfan_status=ENRICHED_STATUS,
            )
            self._seed_processed_video(
                db_path,
                code="AAA-002",
                title="Filtered Collection",
                author="Actor A",
                release_date="2024-01-02",
                status=ENRICHED_STATUS,
                movie_id="m2",
                url="https://example.com/2",
                avfan_status=ENRICHED_STATUS,
            )

            movies = [
                self._build_library_movie("AAA-001", "Visible Video", "Actor A", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                self._build_library_movie("AAA-002", "Filtered Collection", "Actor A", "2024-01-02", ENRICHED_STATUS, "m2", "https://example.com/2"),
            ]
            db.replace_code_prefix_movies("AAA", movies)

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies("Actor A", movies)

            filter_service = VideoFilterService(
                settings_loader=lambda: {
                    "rules": {
                        "code": [],
                        "title": ["Collection"],
                        "javtxt_tags": [],
                    }
                }
            )
            summary = DataCenterService(db, video_filter_service=filter_service).get_summary()

            video_avfan_summary = summary["video_library"]["sources"][AVFAN_VIDEO_SOURCE]
            self.assertEqual(video_avfan_summary["total_count"], 1)
            self.assertEqual(video_avfan_summary["success_count"], 1)

            video_javtxt_summary = summary["video_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(video_javtxt_summary["total_count"], 1)
            self.assertEqual(video_javtxt_summary["success_count"], 1)

            code_prefix_summary = summary["code_prefix_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(code_prefix_summary["total_count"], 1)
            self.assertEqual(code_prefix_summary["success_count"], 1)

            actor_summary = summary["actor_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(actor_summary["total_count"], 1)
            self.assertEqual(actor_summary["success_count"], 1)

            del summary
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_binghuo_summary_counts_incomplete_profiles_as_no_detail(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [
                        ("Actor Success",),
                        ("Actor Partial",),
                        ("Actor No Search",),
                        ("Actor Failed",),
                        ("Actor Pending",),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        binghuo_enrichment_status,
                        binghuo_person_id,
                        binghuo_birthday,
                        binghuo_height
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("Actor Success", ENRICHED_STATUS, "1001", "1990-01-01", "168"),
                        ("Actor Partial", NO_VIDEO_DETAIL_STATUS, "", "", "170"),
                        ("Actor No Search", NO_SEARCH_RESULTS_STATUS, "", "", ""),
                        ("Actor Failed", FAILED_STATUS, "", "", ""),
                    ],
                )
                conn.commit()

            summary = DataCenterService(db).get_summary_snapshot()["summary"]
            binghuo_summary = summary["actor_library"]["sources"][BINGHUO_ACTOR_SOURCE]

            self.assertEqual(binghuo_summary["total_count"], 5)
            self.assertEqual(binghuo_summary["success_count"], 1)
            self.assertEqual(binghuo_summary["no_search_count"], 1)
            self.assertEqual(binghuo_summary["no_detail_count"], 1)
            self.assertEqual(binghuo_summary["failed_count"], 1)
            self.assertEqual(binghuo_summary["pending_count"], 1)
            self.assertEqual(binghuo_summary["enriched_count"], 3)
            self.assertEqual(binghuo_summary["progress_percent"], 60.0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_baomu_summary_uses_baomu_status_counts(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [
                        ("Actor Success",),
                        ("Actor No Search",),
                        ("Actor Failed",),
                        ("Actor Pending",),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        baomu_enrichment_status
                    )
                    VALUES (?, ?)
                    """,
                    [
                        ("Actor Success", ENRICHED_STATUS),
                        ("Actor No Search", NO_SEARCH_RESULTS_STATUS),
                        ("Actor Failed", FAILED_STATUS),
                    ],
                )
                conn.commit()

            summary = DataCenterService(db).get_summary_snapshot()["summary"]
            baomu_summary = summary["actor_library"]["sources"][BAOMU_ACTOR_SOURCE]

            self.assertEqual(baomu_summary["total_count"], 4)
            self.assertEqual(baomu_summary["success_count"], 1)
            self.assertEqual(baomu_summary["no_search_count"], 1)
            self.assertEqual(baomu_summary["failed_count"], 1)
            self.assertEqual(baomu_summary["pending_count"], 1)
            self.assertEqual(baomu_summary["enriched_count"], 2)
            self.assertEqual(baomu_summary["progress_percent"], 50.0)
            self.assertEqual(baomu_summary["list_kind"], "actor")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_binghuo_summary_splits_missing_fields_and_builds_issue_groups(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 0)",
                    [
                        ("Actor No Search", "", ""),
                        ("Actor Missing Age", "1990-01-01", "35"),
                        ("Actor Missing Measurements", "1991-02-02", "34"),
                        ("Actor Missing Height And Measurements", "1992-03-03", "33"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        binghuo_enrichment_status,
                        binghuo_person_id,
                        binghuo_birthday,
                        binghuo_age,
                        binghuo_height,
                        binghuo_bust,
                        binghuo_waist,
                        binghuo_hip
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("Actor No Search", NO_SEARCH_RESULTS_STATUS, "", "", "", "", "", "", ""),
                        ("Actor Missing Age", NO_VIDEO_DETAIL_STATUS, "1001", "1990-01-01", "", "168", "86", "58", "88"),
                        ("Actor Missing Measurements", NO_VIDEO_DETAIL_STATUS, "1002", "1991-02-02", "34", "170", "", "", ""),
                        ("Actor Missing Height And Measurements", NO_VIDEO_DETAIL_STATUS, "1003", "1992-03-03", "33", "", "90", "", "91"),
                    ],
                )
                conn.commit()

            summary = DataCenterService(db).get_summary_snapshot()["summary"]
            binghuo_summary = summary["actor_library"]["sources"][BINGHUO_ACTOR_SOURCE]

            self.assertEqual(binghuo_summary["list_kind"], "actor")
            self.assertEqual(binghuo_summary["no_search_count"], 1)
            self.assertEqual(binghuo_summary["missing_age_count"], 1)
            self.assertEqual(binghuo_summary["missing_measurements_count"], 2)
            self.assertEqual(binghuo_summary["missing_height_count"], 1)
            self.assertEqual(
                binghuo_summary["issue_groups"],
                [
                    {
                        "key": "no_search",
                        "label": "无结果",
                        "items": [{"name": "Actor No Search"}],
                    },
                    {
                        "key": "missing_age",
                        "label": "无年龄",
                        "items": [{"name": "Actor Missing Age"}],
                    },
                    {
                        "key": "missing_measurements",
                        "label": "无三围",
                        "items": [
                            {"name": "Actor Missing Height And Measurements"},
                            {"name": "Actor Missing Measurements"},
                        ],
                    },
                    {
                        "key": "missing_height",
                        "label": "无身高",
                        "items": [{"name": "Actor Missing Height And Measurements"}],
                    },
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_summary_cache_only_rebuilds_on_manual_refresh(self):
        service = DataCenterService(database=None)
        built_values = [_build_complete_summary_stub(1), _build_complete_summary_stub(2)]

        with patch.object(service, "_load_filter_settings", return_value=None), patch.object(
            service,
            "_build_summary",
            side_effect=built_values,
        ) as build_summary_mock, patch.object(
            service,
            "_current_cache_timestamp",
            side_effect=["2026-06-21 10:00:00", "2026-06-21 10:05:00"],
        ):
            first = service.get_summary_snapshot()
            second = service.get_summary_snapshot()
            refreshed = service.get_summary_snapshot(force_refresh=True)

        self.assertEqual(build_summary_mock.call_count, 2)
        self.assertEqual(first["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 1)
        self.assertEqual(second["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 1)
        self.assertEqual(refreshed["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 2)
        self.assertEqual(first["refreshed_at"], "2026-06-21 10:00:00")
        self.assertEqual(second["refreshed_at"], "2026-06-21 10:00:00")
        self.assertEqual(refreshed["refreshed_at"], "2026-06-21 10:05:00")

    def test_summary_snapshot_persists_across_service_restarts(self):
        temp_dir = tempfile.mkdtemp()
        try:
            snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
            filter_service = VideoFilterService(settings_loader=lambda: None)
            first_service = DataCenterService(database=None, snapshot_file=snapshot_file, video_filter_service=filter_service)

            with patch.object(first_service, "_build_summary", return_value=_build_complete_summary_stub(1)), patch.object(
                first_service,
                "_current_cache_timestamp",
                return_value="2026-06-30 09:00:00",
            ):
                first = first_service.get_summary_snapshot(force_refresh=True)

            second_service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                video_filter_service=VideoFilterService(settings_loader=lambda: None),
            )
            with patch.object(
                second_service,
                "_build_summary",
                side_effect=AssertionError("should reuse persisted snapshot"),
            ):
                second = second_service.get_summary_snapshot()

            self.assertEqual(first, second)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_summary_and_analysis_use_independent_dual_format_files(self):
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            store = SnapshotStore(root / 'snapshots')
            snapshot_file = root / 'legacy' / 'data_center_snapshot.json'
            service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                snapshot_store=store,
                video_filter_service=VideoFilterService(settings_loader=lambda: None),
            )
            with patch.object(service, '_build_summary', return_value=_build_complete_summary_stub(1)), patch.object(
                service,
                '_build_actor_metric_analysis',
                return_value={'metric_key': 'age', 'distribution_rows': [], 'ranking_rows': []},
            ), patch.object(service, '_current_cache_timestamp', return_value='2026-07-16 12:20:00'):
                service.get_summary_snapshot(force_refresh=True)
                service.get_actor_metric_analysis_snapshot('age', force_refresh=True)

            for key in ('data_center/data_center_summary', 'data_center/actor_age'):
                self.assertTrue(store.messagepack_path(key).exists())
                self.assertTrue(store.json_path(key).exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_legacy_summary_snapshot_without_filter_fingerprint_is_reused(self):
        temp_dir = tempfile.mkdtemp()
        try:
            snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
            legacy_payload = {
                "version": DataCenterService.SNAPSHOT_VERSION,
                "summary_snapshot": {
                    "summary": _build_complete_summary_stub(7),
                    "refreshed_at": "2026-07-06 10:00:00",
                },
                "analysis_snapshots": {},
            }
            snapshot_file.write_text(
                json.dumps(legacy_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                video_filter_service=VideoFilterService(
                    settings_loader=lambda: {
                        "rules": {
                            "code": ["AAA"],
                            "title": [],
                            "javtxt_tags": [],
                            "co_star_code": [],
                        }
                    }
                ),
            )
            with patch.object(
                service,
                "_build_summary",
                side_effect=AssertionError("should reuse legacy persisted snapshot"),
            ):
                result = service.get_summary_snapshot()

            self.assertEqual(result["refreshed_at"], "2026-07-06 10:00:00")
            self.assertEqual(
                result["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"],
                7,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_summary_snapshot_is_rebuilt_when_filter_settings_change(self):
        temp_dir = tempfile.mkdtemp()
        try:
            snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
            first_service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                video_filter_service=VideoFilterService(
                    settings_loader=lambda: {
                        "rules": {
                            "code": ["AAA"],
                            "title": [],
                            "javtxt_tags": [],
                            "co_star_code": [],
                        }
                    }
                ),
            )

            with patch.object(first_service, "_build_summary", return_value=_build_complete_summary_stub(1)), patch.object(
                first_service,
                "_current_cache_timestamp",
                return_value="2026-06-30 09:00:00",
            ):
                first = first_service.get_summary_snapshot(force_refresh=True)

            second_service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                video_filter_service=VideoFilterService(
                    settings_loader=lambda: {
                        "rules": {
                            "code": ["BBB"],
                            "title": [],
                            "javtxt_tags": [],
                            "co_star_code": [],
                        }
                    }
                ),
            )
            with patch.object(second_service, "_build_summary", return_value=_build_complete_summary_stub(2)) as build_summary_mock, patch.object(
                second_service,
                "_current_cache_timestamp",
                return_value="2026-06-30 09:05:00",
            ):
                second = second_service.get_summary_snapshot()

            self.assertEqual(first["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 1)
            self.assertEqual(build_summary_mock.call_count, 1)
            self.assertEqual(second["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 2)
            self.assertEqual(second["refreshed_at"], "2026-06-30 09:05:00")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_summary_cache_is_invalidated_when_filter_settings_change_in_same_service(self):
        current_settings = {
            "rules": {
                "code": ["AAA"],
                "title": [],
                "javtxt_tags": [],
                "co_star_code": [],
            }
        }
        service = DataCenterService(
            database=None,
            video_filter_service=VideoFilterService(settings_loader=lambda: current_settings),
        )

        with patch.object(service, "_build_summary", side_effect=[_build_complete_summary_stub(1), _build_complete_summary_stub(2)]) as build_summary_mock, patch.object(
            service,
            "_current_cache_timestamp",
            side_effect=["2026-06-30 09:00:00", "2026-06-30 09:05:00"],
        ):
            first = service.get_summary_snapshot(force_refresh=True)
            current_settings["rules"]["code"] = ["BBB"]
            second = service.get_summary_snapshot()

        self.assertEqual(build_summary_mock.call_count, 2)
        self.assertEqual(first["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 1)
        self.assertEqual(second["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 2)
        self.assertEqual(second["refreshed_at"], "2026-06-30 09:05:00")

    def test_empty_persisted_summary_snapshot_is_ignored_and_rebuilt(self):
        temp_dir = tempfile.mkdtemp()
        try:
            snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
            snapshot_file.write_text(
                json.dumps(
                    {
                        "version": DataCenterService.SNAPSHOT_VERSION,
                        "summary_snapshot": {
                            "summary": {},
                            "refreshed_at": "2026-06-21 10:00:00",
                        },
                        "analysis_snapshots": {},
                    }
                ),
                encoding="utf-8",
            )
            service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                video_filter_service=VideoFilterService(settings_loader=lambda: None),
            )

            with patch.object(service, "_load_filter_settings", return_value=None), patch.object(
                service,
                "_build_summary",
                return_value=_build_complete_summary_stub(3),
            ) as build_summary_mock, patch.object(
                service,
                "_current_cache_timestamp",
                return_value="2026-07-01 03:00:00",
            ):
                result = service.get_summary_snapshot()

            self.assertEqual(build_summary_mock.call_count, 1)
            self.assertEqual(result["refreshed_at"], "2026-07-01 03:00:00")
            self.assertEqual(result["summary"]["video_library"]["sources"][AVFAN_VIDEO_SOURCE]["total_count"], 3)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_analysis_snapshot_persists_across_service_restarts(self):
        temp_dir = tempfile.mkdtemp()
        try:
            snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
            first_service = DataCenterService(database=None, snapshot_file=snapshot_file)

            with patch.object(
                first_service,
                "_build_actor_metric_analysis",
                return_value={"metric_key": "age", "distribution_rows": [], "ranking_rows": []},
            ), patch.object(
                first_service,
                "_current_cache_timestamp",
                return_value="2026-06-30 09:10:00",
            ):
                first = first_service.get_actor_metric_analysis_snapshot("age", force_refresh=True)

            second_service = DataCenterService(database=None, snapshot_file=snapshot_file)
            with patch.object(
                second_service,
                "_build_actor_metric_analysis",
                side_effect=AssertionError("should reuse persisted analysis snapshot"),
            ):
                second = second_service.get_actor_metric_analysis_snapshot("age")

            self.assertEqual(first, second)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_legacy_analysis_snapshot_without_version_is_ignored_and_rebuilt(self):
        temp_dir = tempfile.mkdtemp()
        try:
            snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
            filter_settings = {
                "rules": {
                    "code": [],
                    "title": [],
                    "javtxt_tags": [],
                    "co_star_code": [],
                }
            }
            snapshot_file.write_text(
                json.dumps(
                    {
                        "version": DataCenterService.SNAPSHOT_VERSION,
                        "filter_settings_fingerprint": DataCenterService._build_filter_settings_fingerprint(
                            filter_settings
                        ),
                        "summary_snapshot": {
                            "summary": _build_complete_summary_stub(1),
                            "refreshed_at": "2026-06-30 09:00:00",
                        },
                        "analysis_snapshots": {
                            "actor:age": {
                                "analysis": {
                                    "metric_key": "age",
                                    "distribution_rows": [
                                        {"label": "70岁", "count": 2, "bucket_value": 70},
                                    ],
                                    "ranking_rows": [
                                        {
                                            "actor_name": "Actor A",
                                            "display_value": "70岁",
                                            "numeric_value": 70,
                                        }
                                    ],
                                },
                                "refreshed_at": "2026-06-30 09:05:00",
                            }
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            service = DataCenterService(
                database=None,
                snapshot_file=snapshot_file,
                video_filter_service=VideoFilterService(settings_loader=lambda: filter_settings),
            )
            with patch.object(
                service,
                "_build_actor_metric_analysis",
                return_value={"metric_key": "age", "distribution_rows": [], "ranking_rows": []},
            ) as build_analysis_mock, patch.object(
                service,
                "_current_cache_timestamp",
                return_value="2026-07-06 12:00:00",
            ):
                result = service.get_actor_metric_analysis_snapshot("age")

            self.assertEqual(build_analysis_mock.call_count, 1)
            self.assertEqual(result["refreshed_at"], "2026-07-06 12:00:00")
            self.assertEqual(result["analysis"]["ranking_rows"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_metric_analysis_builds_distribution_and_top_rankings(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', ?, 0)",
                    [
                        ("Actor A", "70"),
                        ("Actor B", "69"),
                        ("Actor C", ""),
                        ("Actor D", "70"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        binghuo_height,
                        binghuo_bust,
                        binghuo_waist,
                        binghuo_hip
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("Actor A", "179", "90", "60", "92"),
                        ("Actor B", "168", "84", "58", "88"),
                        ("Actor D", "175", "", "", ""),
                    ],
                )
                conn.commit()

            service = DataCenterService(db)

            age_analysis = service.get_actor_metric_analysis_snapshot("age")
            self.assertEqual(
                age_analysis["analysis"]["distribution_rows"],
                [
                    {"label": "70岁", "count": 2},
                    {"label": "69岁", "count": 1},
                    {"label": "无数据", "count": 1},
                ],
            )
            self.assertEqual(
                age_analysis["analysis"]["ranking_rows"][:3],
                [
                    {"actor_name": "Actor A", "display_value": "70岁", "numeric_value": 70},
                    {"actor_name": "Actor D", "display_value": "70岁", "numeric_value": 70},
                    {"actor_name": "Actor B", "display_value": "69岁", "numeric_value": 69},
                ],
            )

            height_analysis = service.get_actor_metric_analysis_snapshot("height")
            self.assertEqual(
                height_analysis["analysis"]["distribution_rows"],
                [
                    {"label": "179 cm", "count": 1},
                    {"label": "175 cm", "count": 1},
                    {"label": "168 cm", "count": 1},
                    {"label": "无数据", "count": 1},
                ],
            )
            self.assertEqual(
                height_analysis["analysis"]["ranking_rows"][:3],
                [
                    {"actor_name": "Actor A", "display_value": "179 cm", "numeric_value": 179},
                    {"actor_name": "Actor D", "display_value": "175 cm", "numeric_value": 175},
                    {"actor_name": "Actor B", "display_value": "168 cm", "numeric_value": 168},
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_video_count_analysis_uses_effective_single_and_co_star_movies(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)
            actors_and_counts = [
                ("Actor A", 4, VIDEO_CATEGORY_SINGLE),
                ("Actor B", 5, VIDEO_CATEGORY_CO_STAR),
                ("Actor C", 10, VIDEO_CATEGORY_SINGLE),
                ("Actor D", 30, VIDEO_CATEGORY_CO_STAR),
                ("Actor E", 80, VIDEO_CATEGORY_SINGLE),
                ("Actor F", 0, VIDEO_CATEGORY_SINGLE),
            ]
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [(actor_name,) for actor_name, _count, _category in actors_and_counts],
                )
                conn.commit()

            for actor_index, (actor_name, count, category) in enumerate(actors_and_counts):
                movies = [
                    self._build_library_movie(
                        f"A{actor_index:02d}-{movie_index:03d}",
                        f"Movie {movie_index}",
                        actor_name,
                        "2026-01-01",
                        ENRICHED_STATUS,
                        video_category=category,
                    )
                    for movie_index in range(count)
                ]
                if actor_name == "Actor A":
                    movies.append(dict(movies[0]))
                if actor_name == "Actor C":
                    movies.append(
                        self._build_library_movie(
                            "A02-999",
                            "Excluded collection",
                            actor_name,
                            "2026-01-01",
                            ENRICHED_STATUS,
                            video_category=VIDEO_CATEGORY_COLLECTION,
                        )
                    )
                db.replace_actor_movies(actor_name, movies)

            analysis = DataCenterService(db).get_actor_metric_analysis_snapshot("video_count")["analysis"]

            self.assertEqual(
                analysis["distribution_rows"],
                [
                    {"label": "5\u4e2a\u4ee5\u4e0b", "count": 2, "bucket_value": "0_4"},
                    {"label": "5~9\u4e2a", "count": 1, "bucket_value": "5_9"},
                    {"label": "10~29\u4e2a", "count": 1, "bucket_value": "10_29"},
                    {"label": "30~79\u4e2a", "count": 1, "bucket_value": "30_79"},
                    {"label": "80\u4e2a\u4ee5\u4e0a", "count": 1, "bucket_value": "80_plus"},
                ],
            )
            self.assertEqual(
                analysis["ranking_rows"],
                [
                    {"actor_name": "Actor E", "display_value": "80\u4e2a", "numeric_value": 80},
                    {"actor_name": "Actor D", "display_value": "30\u4e2a", "numeric_value": 30},
                    {"actor_name": "Actor C", "display_value": "10\u4e2a", "numeric_value": 10},
                    {"actor_name": "Actor B", "display_value": "5\u4e2a", "numeric_value": 5},
                    {"actor_name": "Actor A", "display_value": "4\u4e2a", "numeric_value": 4},
                    {"actor_name": "Actor F", "display_value": "0\u4e2a", "numeric_value": 0},
                ],
            )
            bucket = DataCenterService(db).get_actor_metric_bucket_snapshot("video_count", "5_9")
            self.assertEqual(
                bucket["actors"],
                [{"actor_name": "Actor B", "display_value": "5\u4e2a", "numeric_value": 5}],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_code_prefix_video_count_analysis_builds_ranges_and_ranking(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)
            prefixes_and_counts = [
                ("AAA", 49),
                ("BBB", 50),
                ("CCC", 100),
                ("DDD", 300),
                ("EEE", 800),
            ]
            for prefix, count in prefixes_and_counts:
                db.replace_code_prefix_movies(
                    prefix,
                    [
                        self._build_library_movie(
                            f"{prefix}-{movie_index:04d}",
                            f"{prefix} Movie {movie_index}",
                            "Actor",
                            "2026-01-01",
                            ENRICHED_STATUS,
                            video_category=VIDEO_CATEGORY_SINGLE,
                        )
                        for movie_index in range(count)
                    ],
                )

            service = DataCenterService(db)
            analysis = service.get_code_prefix_metric_analysis_snapshot("video_count")["analysis"]

            self.assertEqual(
                analysis["distribution_rows"],
                [
                    {"label": "50\u4e2a\u4ee5\u4e0b", "count": 1, "bucket_value": "0_49"},
                    {"label": "50~99\u4e2a", "count": 1, "bucket_value": "50_99"},
                    {"label": "100~299\u4e2a", "count": 1, "bucket_value": "100_299"},
                    {"label": "300~799\u4e2a", "count": 1, "bucket_value": "300_799"},
                    {"label": "800\u4e2a\u4ee5\u4e0a", "count": 1, "bucket_value": "800_plus"},
                ],
            )
            self.assertEqual(
                analysis["ranking_rows"],
                [
                    {"prefix": "EEE", "label": "EEE", "display_value": "800\u4e2a", "numeric_value": 800},
                    {"prefix": "DDD", "label": "DDD", "display_value": "300\u4e2a", "numeric_value": 300},
                    {"prefix": "CCC", "label": "CCC", "display_value": "100\u4e2a", "numeric_value": 100},
                    {"prefix": "BBB", "label": "BBB", "display_value": "50\u4e2a", "numeric_value": 50},
                    {"prefix": "AAA", "label": "AAA", "display_value": "49\u4e2a", "numeric_value": 49},
                ],
            )
            bucket = service.get_code_prefix_metric_bucket_snapshot("video_count", "50_99")
            self.assertEqual(bucket["metric_key"], "video_count")
            self.assertEqual(bucket["bucket_value"], "50_99")
            self.assertEqual(bucket["bucket_label"], "50~99\u4e2a")
            self.assertEqual(
                bucket["prefixes"],
                [
                    {
                        "prefix": "BBB",
                        "label": "BBB",
                        "display_value": "50\u4e2a",
                        "numeric_value": 50,
                    }
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_video_count_ranking_is_limited_to_top_50_with_stable_ties(self):
        config = {
            "key": "video_count",
            "ranges": (
                {"key": "0_49", "label": "50\u4e2a\u4ee5\u4e0b", "minimum": 0, "maximum": 49},
                {"key": "50_plus", "label": "50\u4e2a\u4ee5\u4e0a", "minimum": 50, "maximum": None},
            ),
        }
        rows = [
            {
                "actor_name": f"Actor {index:02d}",
                "display_value": "1\u4e2a",
                "numeric_value": 1,
            }
            for index in range(55)
        ]

        analysis = DataCenterService._build_range_count_analysis(config, rows, "actor_name")

        self.assertEqual(len(analysis["ranking_rows"]), 50)
        self.assertEqual(analysis["ranking_rows"][0]["actor_name"], "Actor 00")
        self.assertEqual(analysis["ranking_rows"][-1]["actor_name"], "Actor 49")

    def test_code_prefix_metric_analysis_builds_ratio_distribution_and_top_rankings(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie("AAA-001", "AAA Collection", "Actor A", "2024-01-01", ENRICHED_STATUS, video_category=VIDEO_CATEGORY_COLLECTION),
                    self._build_library_movie("AAA-002", "AAA Single", "Actor A", "2024-01-02", ENRICHED_STATUS),
                ],
            )
            db.replace_code_prefix_movies(
                "BBB",
                [
                    self._build_library_movie("BBB-001", "BBB Collection 1", "Actor B", "2024-01-01", ENRICHED_STATUS, video_category=VIDEO_CATEGORY_COLLECTION),
                    self._build_library_movie("BBB-002", "BBB Collection 2", "Actor B", "2024-01-02", ENRICHED_STATUS, video_category=VIDEO_CATEGORY_COLLECTION),
                    self._build_library_movie("BBB-003", "BBB Single", "Actor B", "2024-01-03", ENRICHED_STATUS),
                ],
            )
            db.replace_code_prefix_movies(
                "CCC",
                [
                    self._build_library_movie("CCC-001", "CCC Collection", "Actor C", "2024-01-01", ENRICHED_STATUS, video_category=VIDEO_CATEGORY_COLLECTION),
                ],
            )
            db.replace_code_prefix_movies(
                "DDD",
                [
                    self._build_library_movie("DDD-001", "DDD Single 1", "Actor D", "2024-01-01", ENRICHED_STATUS),
                    self._build_library_movie("DDD-002", "DDD Single 2", "Actor D", "2024-01-02", ENRICHED_STATUS),
                ],
            )

            analysis = DataCenterService(db).get_code_prefix_metric_analysis_snapshot("collection_ratio")

            distribution_rows = analysis["analysis"]["distribution_rows"]
            self.assertEqual(len(distribution_rows), 100)
            self.assertEqual(distribution_rows[0], {"label": "1%", "count": 0})
            self.assertEqual(distribution_rows[49], {"label": "50%", "count": 1})
            self.assertEqual(distribution_rows[66], {"label": "67%", "count": 1})
            self.assertEqual(distribution_rows[99], {"label": "100%", "count": 1})
            self.assertEqual(analysis["analysis"]["distribution_items_per_line"], 6)
            self.assertEqual(analysis["analysis"]["ranking_items_per_line"], 6)
            self.assertEqual(
                analysis["analysis"]["ranking_rows"][:4],
                [
                    {
                        "prefix": "CCC",
                        "label": "CCC",
                        "display_value": "100.0% (1/1)",
                        "numeric_value": 100.0,
                        "collection_count": 1,
                        "total_count": 1,
                    },
                    {
                        "prefix": "BBB",
                        "label": "BBB",
                        "display_value": "66.7% (2/3)",
                        "numeric_value": 66.7,
                        "collection_count": 2,
                        "total_count": 3,
                    },
                    {
                        "prefix": "AAA",
                        "label": "AAA",
                        "display_value": "50.0% (1/2)",
                        "numeric_value": 50.0,
                        "collection_count": 1,
                        "total_count": 2,
                    },
                    {
                        "prefix": "DDD",
                        "label": "DDD",
                        "display_value": "0.0% (0/2)",
                        "numeric_value": 0.0,
                        "collection_count": 0,
                        "total_count": 2,
                    },
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_code_prefix_metric_analysis_excludes_filtered_videos_before_counting_ratios(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie(
                        "AAA-001",
                        "Visible Collection",
                        "Actor A",
                        "2024-01-01",
                        ENRICHED_STATUS,
                        movie_id="m1",
                        url="https://example.com/1",
                        video_category=VIDEO_CATEGORY_COLLECTION,
                    ),
                    self._build_library_movie(
                        "AAA-002",
                        "Filtered Collection",
                        "Actor A",
                        "2024-01-02",
                        ENRICHED_STATUS,
                        movie_id="m2",
                        url="https://example.com/2",
                        video_category=VIDEO_CATEGORY_COLLECTION,
                    ),
                    self._build_library_movie(
                        "AAA-003",
                        "Visible Single",
                        "Actor A",
                        "2024-01-03",
                        ENRICHED_STATUS,
                        movie_id="m3",
                        url="https://example.com/3",
                    ),
                ],
            )

            filter_service = VideoFilterService(
                settings_loader=lambda: {
                    "rules": {
                        "code": [],
                        "title": ["Filtered"],
                        "javtxt_tags": [],
                    }
                }
            )

            analysis = DataCenterService(db, video_filter_service=filter_service).get_code_prefix_metric_analysis_snapshot(
                "collection_ratio"
            )

            self.assertEqual(
                analysis["analysis"]["ranking_rows"],
                [
                    {
                        "prefix": "AAA",
                        "label": "AAA",
                        "display_value": "50.0% (1/2)",
                        "numeric_value": 50.0,
                        "collection_count": 1,
                        "total_count": 2,
                    }
                ],
            )
            self.assertEqual(analysis["analysis"]["distribution_rows"][49], {"label": "50%", "count": 1})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_code_prefix_metric_analysis_merges_code_prefix_and_actor_libraries_then_deduplicates_codes(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie(
                        "AAA-001",
                        "AAA Shared Collection",
                        "Actor A",
                        "2024-01-01",
                        ENRICHED_STATUS,
                        movie_id="m1",
                        url="https://example.com/1",
                        video_category=VIDEO_CATEGORY_COLLECTION,
                    ),
                    self._build_library_movie(
                        "AAA-002",
                        "AAA Single",
                        "Actor A",
                        "2024-01-02",
                        ENRICHED_STATUS,
                        movie_id="m2",
                        url="https://example.com/2",
                    ),
                ],
            )

            db.replace_actor_movies(
                "Actor A",
                [
                    self._build_library_movie(
                        "AAA-001",
                        "AAA Shared Collection",
                        "Actor A",
                        "2024-01-01",
                        ENRICHED_STATUS,
                        movie_id="m1",
                        url="https://example.com/1",
                        video_category=VIDEO_CATEGORY_COLLECTION,
                    ),
                    self._build_library_movie(
                        "AAA-003",
                        "AAA Actor-Only Collection",
                        "Actor A",
                        "2024-01-03",
                        ENRICHED_STATUS,
                        movie_id="m3",
                        url="https://example.com/3",
                        video_category=VIDEO_CATEGORY_COLLECTION,
                    ),
                ],
            )
            db.replace_actor_movies(
                "Actor B",
                [
                    self._build_library_movie(
                        "ZZZ-001",
                        "ZZZ Shared Single",
                        "Actor B",
                        "2024-02-01",
                        ENRICHED_STATUS,
                        movie_id="m4",
                        url="https://example.com/4",
                    ),
                ],
            )
            db.replace_actor_movies(
                "Actor C",
                [
                    self._build_library_movie(
                        "ZZZ-001",
                        "ZZZ Shared Single",
                        "Actor C",
                        "2024-02-01",
                        ENRICHED_STATUS,
                        movie_id="m4",
                        url="https://example.com/4",
                    ),
                ],
            )

            analysis = DataCenterService(db).get_code_prefix_metric_analysis_snapshot("collection_ratio")

            self.assertEqual(
                analysis["analysis"]["ranking_rows"][:2],
                [
                    {
                        "prefix": "AAA",
                        "label": "AAA",
                        "display_value": "66.7% (2/3)",
                        "numeric_value": 66.7,
                        "collection_count": 2,
                        "total_count": 3,
                    },
                    {
                        "prefix": "ZZZ",
                        "label": "ZZZ",
                        "display_value": "0.0% (0/1)",
                        "numeric_value": 0.0,
                        "collection_count": 0,
                        "total_count": 1,
                    },
                ],
            )
            self.assertEqual(analysis["analysis"]["distribution_rows"][66], {"label": "67%", "count": 1})
            self.assertEqual(analysis["analysis"]["distribution_rows"][0], {"label": "1%", "count": 0})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_metric_analysis_builds_distribution_and_top_rankings(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', ?, 0)",
                    [
                        ("Actor A", "70"),
                        ("Actor B", "69"),
                        ("Actor C", ""),
                        ("Actor D", "70"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        binghuo_height,
                        binghuo_bust,
                        binghuo_waist,
                        binghuo_hip
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("Actor A", "179", "90", "60", "92"),
                        ("Actor B", "168", "84", "58", "88"),
                        ("Actor D", "175", "", "", ""),
                    ],
                )
                conn.commit()

            service = DataCenterService(db)

            age_analysis = service.get_actor_metric_analysis_snapshot("age")
            self.assertEqual(
                age_analysis["analysis"]["distribution_rows"],
                [
                    {"label": "70\u5c81", "count": 2, "bucket_value": 70},
                    {"label": "69\u5c81", "count": 1, "bucket_value": 69},
                    {"label": "\u65e0\u6570\u636e", "count": 1},
                ],
            )
            self.assertEqual(
                age_analysis["analysis"]["ranking_rows"][:3],
                [
                    {"actor_name": "Actor A", "display_value": "70\u5c81", "numeric_value": 70},
                    {"actor_name": "Actor D", "display_value": "70\u5c81", "numeric_value": 70},
                    {"actor_name": "Actor B", "display_value": "69\u5c81", "numeric_value": 69},
                ],
            )

            height_analysis = service.get_actor_metric_analysis_snapshot("height")
            self.assertEqual(
                height_analysis["analysis"]["distribution_rows"],
                [
                    {"label": "179 cm", "count": 1, "bucket_value": 179},
                    {"label": "175 cm", "count": 1, "bucket_value": 175},
                    {"label": "168 cm", "count": 1, "bucket_value": 168},
                    {"label": "\u65e0\u6570\u636e", "count": 1},
                ],
            )
            self.assertEqual(
                height_analysis["analysis"]["ranking_rows"][:3],
                [
                    {"actor_name": "Actor A", "display_value": "179 cm", "numeric_value": 179},
                    {"actor_name": "Actor D", "display_value": "175 cm", "numeric_value": 175},
                    {"actor_name": "Actor B", "display_value": "168 cm", "numeric_value": 168},
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _seed_processed_video(
        db_path,
        code,
        title,
        author,
        release_date,
        status,
        movie_id="",
        url="",
        avfan_status=UNENRICHED_STATUS,
        javtxt_tags="",
    ):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO processed_videos (
                    code,
                    title,
                    author,
                    release_date,
                    javtxt_release_date,
                    enrichment_status,
                    avfan_enrichment_status,
                    javtxt_enrichment_status,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_actors,
                    javtxt_actors_raw,
                    javtxt_tags,
                    video_category
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    code,
                    title,
                    author,
                    release_date,
                    release_date,
                    UNENRICHED_STATUS,
                    avfan_status,
                    status,
                    movie_id,
                    url,
                    author if status == ENRICHED_STATUS else "",
                    author if status == ENRICHED_STATUS else "",
                    javtxt_tags,
                ),
            )
            conn.commit()

    @staticmethod
    def _build_library_movie(code, title, author, release_date, status, movie_id="", url="", video_category=""):
        return {
            "code": code,
            "title": title,
            "author": author if status == ENRICHED_STATUS else "",
            "author_raw": author if status == ENRICHED_STATUS else "",
            "release_date": release_date,
            "avfan_url": "",
            "page_number": 1,
            "javtxt_enrichment_status": status,
            "javtxt_movie_id": movie_id,
            "javtxt_url": url,
            "javtxt_tags": "",
            "javtxt_release_date": release_date,
            "video_category": video_category,
        }


if __name__ == "__main__":
    unittest.main()
