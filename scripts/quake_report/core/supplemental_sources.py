"""Optional secondary data layers for richer reports.

USGS remains the primary catalog used for statistics. Secondary sources are
reported separately so cross-source duplicates do not inflate event counts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import time
from typing import Optional

import pandas as pd
import requests

from .fault_loader import load_faults_in_bbox
from .usgs_client import CatalogQuery, MainShock, haversine_km

EMSC_FDSN = "https://www.seismicportal.eu/fdsnws/event/1/query"
EMSC_CACHE_DIR = Path(os.environ.get("QUAKE_EMSC_CACHE_DIR", "/tmp/quake-emsc-cache"))
EMSC_CACHE_TTL_SEC = int(os.environ.get("QUAKE_EMSC_CACHE_TTL", "3600"))


@dataclass
class SupplementalData:
    emsc_catalog: pd.DataFrame = field(default_factory=pd.DataFrame)
    emsc_error: Optional[str] = None
    emsc_limited: bool = False
    fault_count: int = 0
    nearest_fault_name: str = ""
    nearest_fault_distance_km: Optional[float] = None


def fetch_emsc_catalog(query: CatalogQuery, *, limit: int = 2000, timeout: int = 30) -> pd.DataFrame:
    """Fetch an auxiliary EMSC/Seismic Portal catalog around the epicenter."""
    start = query.start_time or datetime(1900, 1, 1)
    end = query.end_time or datetime.now(timezone.utc)
    params = {
        "format": "json",
        "starttime": start.strftime("%Y-%m-%d"),
        "endtime": end.strftime("%Y-%m-%d"),
        "latitude": query.latitude,
        "longitude": query.longitude,
        "maxradius": query.max_radius_km / 111.32,
        "minmagnitude": query.min_magnitude,
        "limit": limit,
    }
    data = _cached_emsc_json(params, timeout=timeout)
    rows = []
    for feature in data.get("features", []):
        prop = feature.get("properties", {})
        lon, lat, depth = feature.get("geometry", {}).get("coordinates", [None, None, None])
        if lat is None or lon is None:
            continue
        rows.append(
            {
                "id": feature.get("id", ""),
                "time": prop.get("time"),
                "latitude": float(lat),
                "longitude": float(lon),
                "depth": abs(float(depth or 0)),
                "mag": float(prop.get("mag") or 0),
                "magType": prop.get("magtype", ""),
                "place": prop.get("flynn_region", ""),
                "source_catalog": prop.get("source_catalog", "EMSC"),
                "author": prop.get("auth", ""),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["dist_km"] = haversine_km(
        query.latitude, query.longitude, df["latitude"].values, df["longitude"].values
    )
    return df.sort_values(["time"], ascending=False).reset_index(drop=True)


def _cached_emsc_json(params: dict, *, timeout: int) -> dict:
    key = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
    path = EMSC_CACHE_DIR / f"{key}.json"
    if EMSC_CACHE_TTL_SEC > 0:
        try:
            if path.exists() and time.time() - path.stat().st_mtime < EMSC_CACHE_TTL_SEC:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if cached.get("ok"):
                    return cached.get("data", {})
                raise RuntimeError(cached.get("error") or "服务返回为空或格式异常，本次未纳入辅助核对")
        except RuntimeError:
            raise
        except Exception:
            pass

    try:
        r = requests.get(EMSC_FDSN, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        _write_emsc_cache(path, {"ok": True, "data": data})
        return data
    except Exception as exc:
        _write_emsc_cache(path, {"ok": False, "error": _public_emsc_error(exc)})
        raise


def _write_emsc_cache(path: Path, payload: dict):
    if EMSC_CACHE_TTL_SEC <= 0:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _bbox_around(lat: float, lon: float, radius_km: float, pad_factor: float = 1.25):
    import math

    dlat = radius_km * pad_factor / 111.32
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    return lon - dlon, lon + dlon, lat - dlat, lat + dlat


def summarize_faults(mainshock: MainShock, query: CatalogQuery) -> tuple[int, str, Optional[float]]:
    min_lon, max_lon, min_lat, max_lat = _bbox_around(
        mainshock.latitude, mainshock.longitude, query.max_radius_km
    )
    faults = load_faults_in_bbox(min_lon, max_lon, min_lat, max_lat)
    nearest_name = ""
    nearest_dist = None
    for fault in faults:
        if not fault.points:
            continue
        xs, ys = zip(*fault.points)
        dists = haversine_km(mainshock.latitude, mainshock.longitude, ys, xs)
        d = float(dists.min())
        if nearest_dist is None or d < nearest_dist:
            nearest_dist = d
            nearest_name = fault.name or "未命名断层 / unnamed fault"
    return len(faults), nearest_name, nearest_dist


def collect_supplemental_data(mainshock: MainShock, query: CatalogQuery) -> SupplementalData:
    data = SupplementalData()
    try:
        data.emsc_catalog = fetch_emsc_catalog(query)
        data.emsc_limited = len(data.emsc_catalog) >= 2000
    except Exception as exc:
        data.emsc_error = _public_emsc_error(exc)
    data.fault_count, data.nearest_fault_name, data.nearest_fault_distance_km = summarize_faults(
        mainshock, query
    )
    return data


def _public_emsc_error(exc: Exception) -> str:
    if isinstance(exc, requests.Timeout):
        return "请求超时，本次未纳入辅助核对"
    if isinstance(exc, requests.HTTPError):
        return "服务返回异常，本次未纳入辅助核对"
    return "服务返回为空或格式异常，本次未纳入辅助核对"
