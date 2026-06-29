import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import search_usgs_catalog
import sync_usgs_catalog
from quake_report.core.formatting import format_km


class CatalogToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "catalog.sqlite"
        with sqlite3.connect(self.db) as conn:
            sync_usgs_catalog.init_db(conn)
            sync_usgs_catalog.upsert_rows(conn, [
                {
                    "id": "us1",
                    "time": "2008-05-12T06:28:00.000Z",
                    "latitude": "31.0",
                    "longitude": "103.4",
                    "depth": "19",
                    "mag": "7.9",
                    "magType": "Mw",
                    "place": "Sichuan, China",
                },
                {
                    "id": "us2",
                    "time": "2008-05-12T07:00:00.000Z",
                    "latitude": "31.1",
                    "longitude": "103.5",
                    "depth": "10",
                    "mag": "4.5",
                    "magType": "mb",
                    "place": "Sichuan aftershock",
                },
                {
                    "id": "far",
                    "time": "2008-05-12T07:30:00.000Z",
                    "latitude": "10",
                    "longitude": "20",
                    "depth": "10",
                    "mag": "5.0",
                    "magType": "mb",
                    "place": "Elsewhere",
                },
            ])
            conn.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_event_id_lookup(self):
        result = search_usgs_catalog.search(self.db, {"eventId": "US1"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["events"][0]["eventId"], "us1")

    def test_text_search_uses_catalog_index(self):
        result = search_usgs_catalog.search(self.db, {
            "text": "Sichuan",
            "start": "1900-01-01",
            "end": "2020-01-01",
            "minMag": 3,
        })
        self.assertEqual(result["total"], 2)
        self.assertIn("全文索引", result["note"])

    def test_radius_count_only_matches_full_search(self):
        spec = {
            "lat": 31.0,
            "lon": 103.4,
            "radiusKm": 50,
            "start": "1900-01-01",
            "end": "2020-01-01",
            "minMag": 3,
            "page": 1,
            "pageSize": 1,
        }
        listed = search_usgs_catalog.search(self.db, spec)
        counted = search_usgs_catalog.search(self.db, {**spec, "countOnly": True})
        self.assertEqual(listed["total"], 2)
        self.assertEqual(counted["total"], listed["total"])
        self.assertEqual(counted["events"], [])

    def test_optimize_db_writes_sqlite_stats(self):
        with sqlite3.connect(self.db) as conn:
            sync_usgs_catalog.optimize_db(conn)
            analyzed = conn.execute("select count(*) from sqlite_stat1").fetchone()[0]
        self.assertGreater(analyzed, 0)

    def test_format_km_keeps_decimal_radius(self):
        self.assertEqual(format_km(200), "200")
        self.assertEqual(format_km(200.5), "200.5")


if __name__ == "__main__":
    unittest.main()
