#!/bin/sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:3000}"

python3 - "$BASE_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

def get_json(path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.load(r)

def post_json(path, body):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

recent = get_json("/api/quake/recent?days=30&minMag=6.0&limit=5")
assert recent.get("ok") and len(recent.get("events", [])) > 0, recent

search = get_json("/api/quake/search?q=us6000rgf4&page=1")
assert search.get("ok") and search.get("total", 0) >= 1, search

count = post_json("/api/quake/count", {
    "mode": "manual",
    "lat": 10.4351,
    "lon": -68.4716,
    "mag": 7.5,
    "time": "2026-06-24T22:05:00Z",
    "radiusKm": 200,
    "minMag": 3.0,
})
assert count.get("ok") and isinstance(count.get("count"), (int, float)), count

print("smoke_ok", {"recent": len(recent["events"]), "search_total": search["total"], "manual_count": count["count"]})
PY
