#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

DEFAULT_DB = Path("var/usgs_catalog.sqlite")
PAGE_LIMIT = 200
COLUMNS = (
    "events.id, events.time, events.latitude, events.longitude, "
    "events.depth, events.mag, events.magType, events.place"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the local USGS SQLite catalog.")
    parser.add_argument("--db", default=os.environ.get("QUAKE_USGS_CATALOG_DB", str(DEFAULT_DB)))
    parser.add_argument("--spec-json", default="{}")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        return self_check()

    spec = json.loads(args.spec_json)
    result = search(Path(args.db), spec)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


def search(db: Path, spec: dict) -> dict:
    if not db.exists():
        raise FileNotFoundError(f"本地目录库不存在：{db}")
    page = max(1, int(spec.get("page") or 1))
    page_size = max(1, min(PAGE_LIMIT, int(spec.get("pageSize") or 10)))

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        event_id = (spec.get("eventId") or "").strip()
        if event_id:
            row = conn.execute(f"select {COLUMNS} from events where id = ? collate nocase limit 1", (event_id,)).fetchone()
            return payload([row_to_event(row)] if row else [], 1 if row else 0, page, page_size, "本地目录 Event ID 命中")

        if spec.get("countOnly"):
            total = count_rows(conn, spec)
            return payload([], total, page, page_size, "本地 SQLite 目录快速计数")

        if spec.get("candidateMatch"):
            return candidate_payload(conn, spec, page_size)

        rows, total = select_rows(conn, spec, page, page_size)
        note = "本地 SQLite 目录搜索"
        if spec.get("text"):
            note += "，地名/Event ID 使用全文索引"
        if spec.get("lat") is not None and spec.get("lon") is not None:
            note += "，半径搜索先按经纬度包围盒过滤"
        return payload([row_to_event(row) for row in rows], total, page, page_size, note)


def select_rows(conn: sqlite3.Connection, spec: dict, page: int, page_size: int) -> tuple[list[sqlite3.Row], int]:
    from_sql, where, params, used_fts = build_query(conn, spec)
    offset = (page - 1) * page_size

    lat = spec.get("lat")
    lon = spec.get("lon")
    if lat is not None and lon is not None:
        radius = float(spec.get("radiusKm") or 200)
        where, params = add_bbox(where, params, float(lat), float(lon), radius)
        candidates = conn.execute(
            f"select {COLUMNS} {from_sql} where {' and '.join(where)} order by time desc",
            params,
        ).fetchall()
        filtered = [
            (row, haversine(float(lat), float(lon), float(row["latitude"]), float(row["longitude"])))
            for row in candidates
            if row["latitude"] is not None and row["longitude"] is not None
        ]
        filtered = [(row, dist) for row, dist in filtered if dist <= radius]
        return [row for row, _ in filtered[offset:offset + page_size]], len(filtered)

    total = conn.execute(f"select count(*) {from_sql} where {' and '.join(where)}", params).fetchone()[0]
    if from_sql == "from events":
        from_sql = "from events indexed by idx_events_time_mag"
    rows = conn.execute(
        f"select {COLUMNS} {from_sql} where {' and '.join(where)} order by time desc limit ? offset ?",
        [*params, page_size, offset],
    ).fetchall()
    return rows, int(total)


def candidate_payload(conn: sqlite3.Connection, spec: dict, limit: int) -> dict:
    lat = spec.get("lat")
    lon = spec.get("lon")
    has_coords = lat is not None and lon is not None
    if not has_coords and not (spec.get("text") or "").strip():
        return payload([], 0, 1, limit, "缺少地点或经纬度，无法候选匹配")

    radius = float(spec.get("radiusKm") or 300)
    target_mag = float(spec.get("targetMag") or 0)
    target_time = parse_utc_dt(spec.get("targetTimeUtc"))
    query_spec = {**spec, "text": ""} if has_coords else spec
    from_sql, where, params, _used_fts = build_query(conn, query_spec)
    if has_coords:
        where, params = add_bbox(where, params, float(lat), float(lon), radius)
        candidates = conn.execute(
            f"select {COLUMNS} {from_sql} where {' and '.join(where)} order by time desc",
            params,
        ).fetchall()
    else:
        candidates = conn.execute(
            f"select {COLUMNS} {from_sql} where {' and '.join(where)} order by time desc limit 5000",
            params,
        ).fetchall()
    scored = []
    for row in candidates:
        if has_coords and (row["latitude"] is None or row["longitude"] is None):
            continue
        event = row_to_event(row)
        score = 0.0
        if has_coords:
            dist = haversine(float(lat), float(lon), float(row["latitude"]), float(row["longitude"]))
            if dist > radius:
                continue
            score += dist / max(radius, 1)
            event["matchDistanceKm"] = round(dist, 1)
        if target_mag:
            score += abs(float(event["mag"]) - target_mag) * 1.5
        if target_time:
            event_time = parse_utc_dt(event["time"])
            if event_time:
                score += time_shape_score(target_time, event_time)
        event["matchScore"] = round(score, 4)
        scored.append((score, event))

    scored.sort(key=lambda item: item[0])
    events = [event for _score, event in scored[:limit]]
    criteria = "震中、" if has_coords else "地点、"
    criteria += "震级、" if target_mag else ""
    criteria += "月日时分、" if target_time else ""
    return {
        **payload(events, len(scored), 1, limit, f"按{criteria.rstrip('、')}从本地 SQLite 目录匹配候选"),
        "candidateMatch": True,
    }


def count_rows(conn: sqlite3.Connection, spec: dict) -> int:
    from_sql, where, params, _used_fts = build_query(conn, spec)
    lat = spec.get("lat")
    lon = spec.get("lon")
    if lat is None or lon is None:
        return int(conn.execute(f"select count(*) {from_sql} where {' and '.join(where)}", params).fetchone()[0])

    radius = float(spec.get("radiusKm") or 200)
    where, params = add_bbox(where, params, float(lat), float(lon), radius)
    rows = conn.execute(
        f"select events.latitude, events.longitude {from_sql} where {' and '.join(where)}",
        params,
    ).fetchall()
    return sum(
        1
        for row in rows
        if row["latitude"] is not None
        and row["longitude"] is not None
        and haversine(float(lat), float(lon), float(row["latitude"]), float(row["longitude"])) <= radius
    )


def build_query(conn: sqlite3.Connection, spec: dict):
    where = ["time >= ?", "time < ?", "mag >= ?"]
    params: list[object] = [
        sql_time(spec.get("start"), end=False),
        sql_time(spec.get("end"), end=True),
        float(spec.get("minMag") or 3),
    ]
    text = (spec.get("text") or "").strip()
    if not text:
        return "from events", where, params, False

    fts_query = make_fts_query(text)
    if fts_query and has_fts(conn):
        where.append("events_fts match ?")
        params.append(fts_query)
        return "from events join events_fts on events_fts.rowid = events.rowid", where, params, True

    where.append("(place like ? collate nocase or id like ? collate nocase)")
    like = f"%{text}%"
    params.extend([like, like])
    return "from events", where, params, False


def add_bbox(where: list[str], params: list[object], lat: float, lon: float, radius_km: float):
    lat_delta = radius_km / 111.32
    cos_lat = max(0.05, abs(math.cos(math.radians(lat))))
    lon_delta = radius_km / (111.32 * cos_lat)
    lon_min = lon - lon_delta
    lon_max = lon + lon_delta
    where.extend(["latitude between ? and ?"])
    params.extend([lat - lat_delta, lat + lat_delta])
    if lon_min < -180:
        where.append("(longitude >= ? or longitude <= ?)")
        params.extend([lon_min + 360, lon_max])
    elif lon_max > 180:
        where.append("(longitude >= ? or longitude <= ?)")
        params.extend([lon_min, lon_max - 360])
    else:
        where.append("longitude between ? and ?")
        params.extend([lon_min, lon_max])
    return where, params


def sql_time(value: str | None, end: bool) -> str:
    if not value:
        value = dt.datetime.now(dt.timezone.utc).date().isoformat() if end else "1900-01-01"
    if len(value) == 10:
        return f"{value}T00:00:00.000Z"
    if value.endswith("Z"):
        return value
    if "+" in value:
        return dt.datetime.fromisoformat(value).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return f"{value}Z"


def parse_utc_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def time_shape_score(target: dt.datetime, event: dt.datetime) -> float:
    month_delta = 0 if target.month == event.month else 3
    day_delta = min(abs(target.day - event.day), 31 - abs(target.day - event.day))
    target_minutes = target.hour * 60 + target.minute
    event_minutes = event.hour * 60 + event.minute
    minute_delta = abs(target_minutes - event_minutes)
    minute_delta = min(minute_delta, 1440 - minute_delta)
    return month_delta + day_delta * 0.45 + minute_delta / 180


def make_fts_query(text: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z_\u4e00-\u9fff]+", text.lower())
    return " ".join(f"{token}*" for token in tokens[:8])


def has_fts(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("select 1 from sqlite_master where type='table' and name='events_fts'").fetchone())


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def row_to_event(row: sqlite3.Row) -> dict:
    return {
        "eventId": row["id"],
        "time": row["time"],
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "depth": float(row["depth"] or 0),
        "mag": float(row["mag"]),
        "magType": row["magType"] or "M",
        "place": row["place"] or "",
    }


def payload(events: list[dict], total: int, page: int, page_size: int, note: str) -> dict:
    return {"ok": True, "events": events, "total": total, "page": page, "pageSize": page_size, "note": note, "localCatalog": True}


def self_check() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sync_usgs_catalog import init_db, upsert_rows

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "catalog.sqlite"
        with sqlite3.connect(db) as conn:
            init_db(conn)
            upsert_rows(conn, [
                {"id": "us1", "time": "2008-05-12T06:28:00.000Z", "latitude": "31.0", "longitude": "103.4", "depth": "19", "mag": "7.9", "magType": "Mw", "place": "Sichuan, China"},
                {"id": "us2", "time": "2009-01-01T00:00:00.000Z", "latitude": "10.0", "longitude": "20.0", "depth": "10", "mag": "4.5", "magType": "mb", "place": "Elsewhere"},
                {"id": "us3", "time": "2025-06-24T22:30:00.000Z", "latitude": "40.2", "longitude": "142.4", "depth": "50", "mag": "6.9", "magType": "Mww", "place": "near the east coast of Honshu, Japan"},
            ])
            conn.commit()
        result = search(db, {"text": "Sichuan", "start": "1900-01-01", "end": "2020-01-01", "minMag": 3, "page": 1, "pageSize": 10})
        assert result["total"] == 1, result
        result = search(db, {"lat": 31.0, "lon": 103.4, "radiusKm": 50, "start": "1900-01-01", "end": "2020-01-01", "minMag": 3, "page": 1, "pageSize": 10})
        assert result["total"] == 1, result
        result = search(db, {"lat": 31.0, "lon": 103.4, "radiusKm": 50, "start": "1900-01-01", "end": "2020-01-01", "minMag": 3, "countOnly": True})
        assert result["total"] == 1 and result["events"] == [], result
        result = search(db, {
            "candidateMatch": True,
            "lat": 40.2,
            "lon": 142.4,
            "radiusKm": 200,
            "minMag": 6.4,
            "targetMag": 6.9,
            "targetTimeUtc": "2026-06-24T22:30:00Z",
            "pageSize": 5,
        })
        assert result["events"][0]["eventId"] == "us3", result
        assert result["events"][0]["matchDistanceKm"] == 0.0, result
        result = search(db, {
            "candidateMatch": True,
            "text": "Sichuan",
            "minMag": 7.4,
            "targetMag": 7.9,
            "targetTimeUtc": "2026-05-12T06:28:00Z",
            "pageSize": 5,
        })
        assert result["events"][0]["eventId"] == "us1", result
        assert "matchDistanceKm" not in result["events"][0], result
    print("self-check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
