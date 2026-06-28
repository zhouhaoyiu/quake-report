#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

FDSN = "https://earthquake.usgs.gov/fdsnws/event/1"
DEFAULT_DB = Path("var/usgs_catalog.sqlite")
DEFAULT_LIMIT = 20000
FTS_SCHEMA_VERSION = "1"
CSV_COLUMNS = [
    "time", "latitude", "longitude", "depth", "mag", "magType", "nst", "gap",
    "dmin", "rms", "net", "id", "updated", "place", "type", "horizontalError",
    "depthError", "magError", "magNst", "status", "locationSource", "magSource",
]
REAL_COLUMNS = {
    "latitude", "longitude", "depth", "mag", "nst", "gap", "dmin", "rms",
    "horizontalError", "depthError", "magError", "magNst",
}


def main() -> int:
    p = argparse.ArgumentParser(description="Sync USGS FDSN M>=3 catalog into SQLite.")
    p.add_argument("--db", default=os.environ.get("QUAKE_USGS_CATALOG_DB", str(DEFAULT_DB)))
    p.add_argument("--start", default=None, help="UTC start date, default: incremental or 1900-01-01")
    p.add_argument("--end", default=None, help="UTC end date, default: tomorrow")
    p.add_argument("--min-mag", type=float, default=3.0)
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--overlap-days", type=int, default=7)
    p.add_argument("--full-if-empty", action="store_true")
    p.add_argument("--export-csv-gz", default=None, help="Optional gzip CSV export path.")
    p.add_argument("--status-json", default=os.environ.get("QUAKE_USGS_CATALOG_STATUS"))
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args()

    if args.self_check:
        return self_check()

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        init_db(conn)
        start, end = sync_window(conn, args.start, args.end, args.overlap_days, args.full_if_empty)
        print(f"USGS sync: db={db} start={start.date()} end={end.date()} minMag={args.min_mag}")
        total = 0
        cursor = start
        while cursor < end:
            next_year = dt.datetime(cursor.year + 1, 1, 1, tzinfo=dt.timezone.utc)
            chunk_end = min(next_year, end)
            total += sync_interval(conn, cursor, chunk_end, args.min_mag, args.limit)
            cursor = chunk_end
        set_meta(conn, "last_sync_utc", utc_now().isoformat())
        set_meta(conn, "min_magnitude", str(args.min_mag))
        optimize_db(conn)
        conn.commit()
        row_count = conn.execute("select count(*) from events").fetchone()[0]
        write_status(conn, db, Path(args.status_json) if args.status_json else db.with_name("usgs_catalog_status.json"))
        print(f"USGS sync done: downloaded_or_updated={total} sqlite_rows={row_count}")
        if args.export_csv_gz:
            export_csv_gz(conn, Path(args.export_csv_gz))
        return 0
    finally:
        conn.close()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def parse_utc(value: str) -> dt.datetime:
    value = value.strip()
    if len(value) == 10:
        value += "T00:00:00Z"
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0)


def fmt(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def sync_window(conn: sqlite3.Connection, start: str | None, end: str | None, overlap_days: int, full_if_empty: bool):
    end_dt = parse_utc(end) if end else (utc_now() + dt.timedelta(days=1))
    if start:
        return parse_utc(start), end_dt

    row = conn.execute("select max(time) from events").fetchone()
    if row and row[0]:
        start_dt = parse_utc(row[0]) - dt.timedelta(days=max(0, overlap_days))
        return max(start_dt, parse_utc("1900-01-01")), end_dt

    if full_if_empty:
        return parse_utc("1900-01-01"), end_dt

    return utc_now() - dt.timedelta(days=max(1, overlap_days)), end_dt


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("pragma journal_mode=wal")
    cols = []
    for name in CSV_COLUMNS:
        typ = "real" if name in REAL_COLUMNS else "text"
        if name == "id":
            cols.append("id text primary key")
        else:
            cols.append(f"{name} {typ}")
    conn.execute(f"create table if not exists events ({', '.join(cols)})")
    conn.execute("create table if not exists meta (key text primary key, value text not null)")
    conn.execute("create index if not exists idx_events_time on events(time)")
    conn.execute("create index if not exists idx_events_mag on events(mag)")
    conn.execute("create index if not exists idx_events_lat_lon on events(latitude, longitude)")
    conn.execute("create index if not exists idx_events_mag_time on events(mag, time)")
    conn.execute("create index if not exists idx_events_time_mag on events(time, mag)")
    conn.execute("create index if not exists idx_events_lat_lon_mag_time on events(latitude, longitude, mag, time)")
    init_fts(conn)


def init_fts(conn: sqlite3.Connection) -> None:
    conn.execute("""
        create virtual table if not exists events_fts using fts5(
            id,
            place,
            content='events',
            content_rowid='rowid'
        )
    """)
    conn.executescript("""
        create trigger if not exists events_ai after insert on events begin
            insert into events_fts(rowid, id, place) values (new.rowid, new.id, coalesce(new.place, ''));
        end;
        create trigger if not exists events_ad after delete on events begin
            insert into events_fts(events_fts, rowid, id, place)
            values('delete', old.rowid, old.id, coalesce(old.place, ''));
        end;
        create trigger if not exists events_au after update on events begin
            insert into events_fts(events_fts, rowid, id, place)
            values('delete', old.rowid, old.id, coalesce(old.place, ''));
            insert into events_fts(rowid, id, place) values (new.rowid, new.id, coalesce(new.place, ''));
        end;
    """)
    event_count = conn.execute("select count(*) from events").fetchone()[0]
    version = conn.execute("select value from meta where key='fts_schema_version'").fetchone()
    if event_count and (not version or version[0] != FTS_SCHEMA_VERSION):
        conn.execute("insert into events_fts(events_fts) values('rebuild')")
    conn.execute(
        "insert into meta(key, value) values('fts_schema_version', ?) on conflict(key) do update set value=excluded.value",
        (FTS_SCHEMA_VERSION,),
    )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
        (key, value),
    )


def write_status(conn: sqlite3.Connection, db: Path, path: Path) -> None:
    last_sync = conn.execute("select value from meta where key='last_sync_utc'").fetchone()
    min_mag = conn.execute("select value from meta where key='min_magnitude'").fetchone()
    row_count, max_time = conn.execute("select count(*), max(time) from events").fetchone()
    payload = {
        "ok": True,
        "db": str(db),
        "rows": row_count,
        "lastEventTime": max_time,
        "lastSyncUtc": last_sync[0] if last_sync else None,
        "minMagnitude": float(min_mag[0]) if min_mag else 3.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_interval(
    conn: sqlite3.Connection,
    start: dt.datetime,
    end: dt.datetime,
    min_mag: float,
    limit: int,
) -> int:
    count = fetch_count(start, end, min_mag)
    if count == 0:
        print(f"  {start.date()}..{end.date()} count=0")
        return 0
    if count > limit:
        mid = start + (end - start) / 2
        return sync_interval(conn, start, mid, min_mag, limit) + sync_interval(conn, mid, end, min_mag, limit)

    rows = fetch_csv_rows(start, end, min_mag, limit)
    upsert_rows(conn, rows)
    conn.commit()
    print(f"  {start.date()}..{end.date()} count={count} rows={len(rows)}")
    return len(rows)


def fetch_count(start: dt.datetime, end: dt.datetime, min_mag: float) -> int:
    text = http_get(f"{FDSN}/count", {
        "starttime": fmt(start),
        "endtime": fmt(end),
        "minmagnitude": min_mag,
    })
    return int(text.strip() or "0")


def fetch_csv_rows(start: dt.datetime, end: dt.datetime, min_mag: float, limit: int) -> list[dict[str, str]]:
    text = http_get(f"{FDSN}/query", {
        "format": "csv",
        "starttime": fmt(start),
        "endtime": fmt(end),
        "minmagnitude": min_mag,
        "orderby": "time-asc",
        "limit": limit,
    })
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader if row.get("id")]


def http_get(url: str, params: dict, retries: int = 5) -> str:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url, headers={"User-Agent": "quake-report-catalog-sync/1.0"})
            with urllib.request.urlopen(req, timeout=90) as res:
                return res.read().decode("utf-8", "replace")
        except Exception as exc:
            last = exc
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"USGS request failed after {retries} retries: {last}")


def to_float(value: str | None):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def upsert_rows(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in CSV_COLUMNS)
    updates = ", ".join(f"{col}=excluded.{col}" for col in CSV_COLUMNS if col != "id")
    sql = f"""
        insert into events({", ".join(CSV_COLUMNS)})
        values({placeholders})
        on conflict(id) do update set {updates}
    """
    values = []
    for row in rows:
        values.append(tuple(to_float(row.get(col)) if col in REAL_COLUMNS else row.get(col, "") for col in CSV_COLUMNS))
    conn.executemany(sql, values)


def export_csv_gz(conn: sqlite3.Connection, path: Path) -> None:
    import gzip

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for row in conn.execute(f"select {', '.join(CSV_COLUMNS)} from events order by time"):
            writer.writerow(row)
    print(f"CSV gzip exported: {path}")


def optimize_db(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("insert into events_fts(events_fts) values('optimize')")
    except sqlite3.Error:
        pass
    conn.execute("analyze")


def self_check() -> int:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.sqlite"
        conn = sqlite3.connect(db)
        try:
            init_db(conn)
            upsert_rows(conn, [
                {"id": "a", "time": "2000-01-01T00:00:00.000Z", "latitude": "1", "longitude": "2", "mag": "3.2", "place": "Sichuan"},
                {"id": "a", "time": "2000-01-01T00:00:00.000Z", "latitude": "1", "longitude": "2", "mag": "3.4", "place": "Sichuan"},
                {"id": "b", "time": "2000-01-02T00:00:00.000Z", "latitude": "3", "longitude": "4", "mag": "5.0", "place": "Japan"},
            ])
            count, max_mag = conn.execute("select count(*), max(mag) from events").fetchone()
            assert count == 2, count
            assert abs(max_mag - 5.0) < 1e-9, max_mag
            fts_count = conn.execute("select count(*) from events_fts where events_fts match 'sichuan'").fetchone()[0]
            assert fts_count == 1, fts_count
            optimize_db(conn)
            analyzed = conn.execute("select count(*) from sqlite_stat1").fetchone()[0]
            assert analyzed > 0, analyzed
        finally:
            conn.close()
    print("self-check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
