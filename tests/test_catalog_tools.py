import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import search_usgs_catalog
import sync_usgs_catalog
from quake_report.cli import _default_slug
from quake_report.core.catalog_export import write_catalog_csv
from quake_report.core.docx_builder import _source_text_intro
from quake_report.core.formatting import format_km
from quake_report.core.mainshock_helpers import apply_place_override
from quake_report.core.narrative_builder import build_narrative_zh
from quake_report.core.usgs_client import CatalogQuery, CatalogStats


class CatalogToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "catalog.sqlite"
        with closing(sqlite3.connect(self.db)) as conn:
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
        with closing(sqlite3.connect(self.db)) as conn:
            sync_usgs_catalog.optimize_db(conn)
            analyzed = conn.execute("select count(*) from sqlite_stat1").fetchone()[0]
        self.assertGreater(analyzed, 0)

    def test_reconcile_interval_removes_stale_rows_only_inside_window(self):
        with closing(sqlite3.connect(self.db)) as conn:
            deleted = sync_usgs_catalog.reconcile_interval(
                conn,
                sync_usgs_catalog.parse_utc("2008-05-12T06:00:00Z"),
                sync_usgs_catalog.parse_utc("2008-05-12T07:15:00Z"),
                3.0,
                [{"id": "us1"}],
            )
            self.assertEqual(deleted, 1)
            ids = [r[0] for r in conn.execute("select id from events order by id")]
        self.assertEqual(ids, ["far", "us1"])

    def test_format_km_keeps_decimal_radius(self):
        self.assertEqual(format_km(200), "200")
        self.assertEqual(format_km(200.5), "200.5")

    def test_place_override_applies_to_resolved_mainshock(self):
        shock = SimpleNamespace(place="Sichuan, China")
        apply_place_override([shock], "汶川地震")
        self.assertEqual(shock.place, "汶川地震")

    def test_catalog_csv_keeps_numeric_distance_and_sorts_by_time(self):
        out = Path(self.tmp.name) / "catalog.csv"
        write_catalog_csv(pd.DataFrame([
            {"time": "2020-01-02T00:00:00Z", "dist_km": 99.98508823505868, "mag": 4.1},
            {"time": "2020-01-01T00:00:00Z", "dist_km": 9.5, "mag": 4.2},
        ]), str(out))
        lines = out.read_text(encoding="utf-8-sig").splitlines()
        self.assertIn(",9.5,", lines[1])
        self.assertIn(",99.98508823505868,", lines[2])
        self.assertIn("2020-01-01", lines[1])
        self.assertIn("2020-01-02", lines[2])

    def test_default_slug_uses_report_timezone_chinese_brief_name(self):
        shock = SimpleNamespace(
            time_utc=datetime(2026, 7, 3, 4, 4, tzinfo=timezone.utc),
            place="先岛诸岛",
            magnitude=6.2,
        )
        self.assertEqual(
            _default_slug(shock, "utc8"),
            "2026年7月3日先岛诸岛M6.2地震震中区历史地震简报",
        )

    def test_source_text_intro_prefixes_bulletin_once(self):
        text = "中国地震台网正式测定：07月03日12时04分，在先岛诸岛发生6.2级地震。"
        self.assertEqual(_source_text_intro(text), f"据{text}")
        self.assertEqual(_source_text_intro(f"据{text}"), f"据{text}")

    def test_chinese_narrative_uses_brief_template_wording(self):
        stats = CatalogStats(
            n3=1542,
            n4=1434,
            n5=254,
            n6=33,
            n7=3,
            n8=1,
            total_count=1542,
            query=CatalogQuery(26.23, 126.18),
        )
        text = build_narrative_zh(
            SimpleNamespace(),
            stats,
            fig_num="1",
            radius_km=200,
            mag_type="Mw",
            tz="utc8",
        )
        self.assertIn("据统计，在本次地震的震中周围200千米以内，自 1900 年以来，发生3.0级以上地震1542 次", text)
        self.assertIn("4.0级以上地震 1434 次", text)
        self.assertIn("此次地震的震中周围历史地震分布图见图 1。", text)
        self.assertNotIn("USGS 目录记录", text)


if __name__ == "__main__":
    unittest.main()
