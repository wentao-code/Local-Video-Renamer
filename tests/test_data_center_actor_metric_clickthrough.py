import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.data.database_handler import VideoDatabase
from app.services.library import DataCenterService


class DataCenterActorMetricClickthroughTest(unittest.TestCase):
    def test_actor_metric_distribution_rows_include_bucket_values_and_bucket_lists(self):
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

            age_bucket = service.get_actor_metric_bucket_snapshot("age", 70)
            self.assertEqual(age_bucket["metric_key"], "age")
            self.assertEqual(age_bucket["bucket_value"], 70)
            self.assertEqual(
                age_bucket["actors"],
                [
                    {"actor_name": "Actor A", "display_value": "70\u5c81", "numeric_value": 70},
                    {"actor_name": "Actor D", "display_value": "70\u5c81", "numeric_value": 70},
                ],
            )

            height_bucket = service.get_actor_metric_bucket_snapshot("height", 179)
            self.assertEqual(
                height_bucket["actors"],
                [
                    {"actor_name": "Actor A", "display_value": "179 cm", "numeric_value": 179},
                ],
            )

            del service
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
