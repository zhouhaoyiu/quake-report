"""
USGS FDSN 客户端 —— 从 USGS Earthquake Hazards Program 获取历史地震数据。

支持四种震中信息来源：
1) 手动输入参数（lat/lon/mag/time）
2) 按 eventid 精准查（USGS 事件唯一 ID，如 us7000xxxx）
3) 拉取 USGS 最新大震（近 30 天 M≥6.0 列表）
4) 批量模式（CSV 多行输入）

参考 API 文档: https://earthquake.usgs.gov/fdsnws/event/1/
"""
from __future__ import annotations

import io
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

FDSN_BASE = "https://earthquake.usgs.gov/fdsnws/event/1"
EVENT_DETAIL_BASE = "https://earthquake.usgs.gov/earthquakes/eventpage"
GEOJSON_DETAIL_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail"
USGS_CATALOG_LIMIT = int(os.environ.get("QUAKE_USGS_CATALOG_LIMIT", "20000"))
_CACHE_DIR = Path(os.environ.get("QUAKE_USGS_CACHE_DIR", "/tmp/quake-usgs-cache"))
_CACHE_TTL_SEC = int(os.environ.get("QUAKE_USGS_CACHE_TTL", "86400"))
_CATALOG_DB_ENV = "QUAKE_USGS_CATALOG_DB"


def normalize_mag_type(value: str | None) -> str:
    mag_type = str(value or "Mw").strip()
    if mag_type.upper().startswith("MW"):
        return "MW"
    return mag_type.upper()


def _get_text(url: str, *, params: dict | None = None, timeout: int = 30, cache_ttl: int | None = None):
    ttl = _CACHE_TTL_SEC if cache_ttl is None else cache_ttl
    key_src = json.dumps([url, sorted((params or {}).items())], ensure_ascii=False, default=str)
    path = _CACHE_DIR / f"{hashlib.sha256(key_src.encode()).hexdigest()}.txt"
    if ttl > 0:
        try:
            if path.exists() and time.time() - path.stat().st_mtime < ttl:
                return 200, path.read_text(encoding="utf-8")
        except OSError:
            pass

    r = requests.get(url, params=params, timeout=timeout)
    text = r.text
    if r.ok and ttl > 0:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return r.status_code, text


@dataclass
class MainShock:
    """主震信息。time_utc 字段为 UTC naive datetime。"""

    event_id: str
    latitude: float
    longitude: float
    depth_km: float
    magnitude: float
    mag_type: str
    time_utc: datetime
    place: str = ""

    @property
    def time_str(self) -> str:
        """UTC 中文时间，形如 '2026年6月25日14点17分'"""
        return (
            f"{self.time_utc.year}年{self.time_utc.month}月{self.time_utc.day}日"
            f"{self.time_utc.hour}点{self.time_utc.minute:02d}分"
        )

    @property
    def time_str_en(self) -> str:
        """UTC 英文时间，形如 '2026-06-25 14:17 UTC'"""
        return self.time_utc.strftime("%Y-%m-%d %H:%M UTC")

    @property
    def time_bj_str(self) -> str:
        """北京时间 (UTC+8) 中文时间，形如 '2026年6月25日22点17分'"""
        from datetime import timedelta
        t = self.time_utc + timedelta(hours=8)
        return (
            f"{t.year}年{t.month}月{t.day}日"
            f"{t.hour}点{t.minute:02d}分"
        )

    @property
    def time_bj_str_en(self) -> str:
        """北京时间 (UTC+8) 英文时间，形如 '2026-06-25 22:17 UTC+8'"""
        from datetime import timedelta
        t = self.time_utc + timedelta(hours=8)
        return t.strftime("%Y-%m-%d %H:%M UTC+8")


@dataclass
class CatalogQuery:
    """历史地震目录查询参数。"""

    latitude: float
    longitude: float
    max_radius_km: float = 200.0
    start_time: Optional[datetime] = None  # None 表示 1900-01-01
    end_time: Optional[datetime] = None    # None 表示当前时间
    min_magnitude: float = 3.0

    def to_params(self) -> dict:
        p = {
            "format": "csv",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "maxradiuskm": self.max_radius_km,
            "minmagnitude": self.min_magnitude,
            "orderby": "time-asc",
            "limit": USGS_CATALOG_LIMIT,
        }
        p["starttime"] = _format_usgs_datetime(self.start_time or datetime(1900, 1, 1))
        p["endtime"] = _format_usgs_datetime(self.end_time or datetime.now(timezone.utc))
        return p


def _format_usgs_datetime(dt: datetime) -> str:
    """Format a datetime for USGS FDSN without losing time-of-day precision."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt.strftime("%Y-%m-%d")
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


# ============================================================================
# 主震解析
# ============================================================================

def _parse_usgs_time(t) -> datetime:
    """解析 USGS 时间字段。

    支持两种格式：
    - CSV 格式：'2026-06-25T14:17:45.123Z'（ISO8601 字符串）
    - GeoJSON detail 格式：Unix 毫秒时间戳（int）
    """
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    s = str(t)
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)


def fetch_mainshock_by_id(event_id: str, timeout: int = 30) -> MainShock:
    """按 USGS eventid 拉取主震详情。event_id 形如 'us7000xxxx'。"""
    url = f"{GEOJSON_DETAIL_BASE}/{event_id}.geojson"
    status, text = _get_text(url, timeout=timeout)
    if status >= 400:
        raise requests.HTTPError(f"USGS event detail returned {status}")
    js = json.loads(text)
    props = js["properties"]
    geo = js["geometry"]
    coords = geo["coordinates"]  # [lon, lat, depth_km]
    return MainShock(
        event_id=event_id,
        latitude=coords[1],
        longitude=coords[0],
        depth_km=coords[2],
        magnitude=props["mag"],
        mag_type=normalize_mag_type(props.get("magType")),
        time_utc=_parse_usgs_time(props["time"]),
        place=props.get("place", ""),
    )


def fetch_recent_large_events(
    days: int = 30,
    min_magnitude: float = 6.0,
    limit: int = 30,
    timeout: int = 30,
) -> pd.DataFrame:
    """拉取近 N 天 M≥min_magnitude 的全球地震列表，按时间倒序。

    用于"拉取 USGS 最新大震"模式 —— 让用户从列表中选一个事件。
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    url = f"{FDSN_BASE}/query"
    params = {
        "format": "csv",
        "starttime": start.strftime("%Y-%m-%d"),
        "endtime": end.strftime("%Y-%m-%d"),
        "minmagnitude": min_magnitude,
        "orderby": "time",
    }
    status, text = _get_text(url, params=params, timeout=timeout, cache_ttl=300)
    if status >= 400:
        raise requests.HTTPError(f"USGS recent query returned {status}")
    df = pd.read_csv(io.StringIO(text))
    if len(df) > limit:
        df = df.head(limit)
    return df


def mainshock_from_manual(
    latitude: float,
    longitude: float,
    magnitude: float,
    time_utc: datetime,
    depth_km: float = 10.0,
    mag_type: str = "Mw",
    place: str = "",
    event_id: str = "manual",
) -> MainShock:
    """手动构造主震对象。"""
    return MainShock(
        event_id=event_id,
        latitude=latitude,
        longitude=longitude,
        depth_km=depth_km,
        magnitude=magnitude,
        mag_type=normalize_mag_type(mag_type),
        time_utc=time_utc,
        place=place,
    )


def mainshock_from_csv_row(row: dict) -> MainShock:
    """从 CSV 行构造主震。CSV 列：latitude, longitude, magnitude, time(ISO8601 UTC), depth(可选), place(可选), event_id(可选), mag_type(可选)"""
    return mainshock_from_manual(
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        magnitude=float(row["magnitude"]),
        time_utc=_parse_usgs_time(row["time"]),
        depth_km=float(row.get("depth", 10.0)),
        place=row.get("place", ""),
        event_id=row.get("event_id", "csv"),
        mag_type=row.get("mag_type", "Mw"),
    )


# ============================================================================
# 历史地震目录查询
# ============================================================================

def fetch_historical_catalog(
    query: CatalogQuery,
    exclude_event_id: Optional[str] = None,
    timeout: int = 120,
    retries: int = 3,
) -> pd.DataFrame:
    """获取震中周围历史地震目录。

    Args:
        query: 查询参数
        exclude_event_id: 主震 eventid，将从结果中剔除避免重复
        timeout: HTTP 超时秒数
        retries: 失败重试次数

    Returns:
        DataFrame，列同 USGS CSV：time, latitude, longitude, depth, mag, magType, id, ...
        额外列：
            - dist_km: 距主震震中的距离（km，Haversine）
            - mag_bin: 震级分档标签
    """
    local = _fetch_historical_catalog_from_db(query, exclude_event_id=exclude_event_id)
    if local is not None:
        return local

    url = f"{FDSN_BASE}/query"
    params = query.to_params()

    last_err = None
    for attempt in range(retries):
        try:
            status, text = _get_text(url, params=params, timeout=timeout)
            if status == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if status >= 400:
                raise requests.HTTPError(f"USGS query returned {status}")
            if not text.strip():
                return _empty_catalog()
            df = pd.read_csv(io.StringIO(text))
            df.attrs["usgs_query_limit"] = USGS_CATALOG_LIMIT
            df.attrs["usgs_limit_hit"] = len(df) >= USGS_CATALOG_LIMIT
            break
        except (requests.RequestException, pd.errors.ParserError) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"USGS 查询失败（重试 {retries} 次）：{last_err}")

    if df.empty:
        return _empty_catalog()

    # 剔除主震
    if exclude_event_id and "id" in df.columns:
        attrs = dict(df.attrs)
        df = df[df["id"] != exclude_event_id].copy()
        df.attrs.update(attrs)

    # 计算距离
    df["dist_km"] = haversine_km(
        query.latitude, query.longitude, df["latitude"].values, df["longitude"].values
    )

    # 震级分档
    df["mag_bin"] = df["mag"].apply(_mag_bin_label)
    result = df.reset_index(drop=True)
    result.attrs.update(df.attrs)
    return result


def _catalog_db_path() -> Optional[Path]:
    candidates: list[Path] = []
    configured = os.environ.get(_CATALOG_DB_ENV)
    if configured:
        candidates.append(Path(configured))
    candidates.extend((
        Path.cwd() / "var" / "usgs_catalog.sqlite",
        Path("/opt/quake-report-cache/usgs_catalog.sqlite"),
    ))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _fetch_historical_catalog_from_db(query: CatalogQuery, exclude_event_id: Optional[str] = None) -> Optional[pd.DataFrame]:
    path = _catalog_db_path()
    if path is None:
        return None

    start = _format_usgs_datetime(query.start_time or datetime(1900, 1, 1))
    end = _format_usgs_datetime(query.end_time or datetime.now(timezone.utc))
    lat_delta = float(query.max_radius_km) / 111.32
    cos_lat = max(0.05, abs(np.cos(np.radians(float(query.latitude)))))
    lon_delta = float(query.max_radius_km) / (111.32 * cos_lat)
    lon_min = float(query.longitude) - lon_delta
    lon_max = float(query.longitude) + lon_delta
    lon_clause = "longitude between ? and ?"
    lon_params = [lon_min, lon_max]
    if lon_min < -180:
        lon_clause = "(longitude >= ? or longitude <= ?)"
        lon_params = [lon_min + 360, lon_max]
    elif lon_max > 180:
        lon_clause = "(longitude >= ? or longitude <= ?)"
        lon_params = [lon_min, lon_max - 360]
    params = [
        start,
        end,
        float(query.min_magnitude),
        float(query.latitude) - lat_delta,
        float(query.latitude) + lat_delta,
        *lon_params,
    ]
    sql = """
        select time, latitude, longitude, depth, mag, magType, id, place
        from events
        where time >= ? and time <= ?
          and mag >= ?
          and latitude between ? and ?
          and {lon_clause}
        order by time asc
    """.format(lon_clause=lon_clause)
    try:
        with sqlite3.connect(path) as conn:
            df = pd.read_sql_query(sql, conn, params=params)
    except sqlite3.Error:
        return None

    if df.empty:
        return _empty_catalog()

    df["dist_km"] = haversine_km(
        query.latitude, query.longitude, df["latitude"].values, df["longitude"].values
    )
    df = df[df["dist_km"] <= float(query.max_radius_km)].copy()
    if exclude_event_id and "id" in df.columns:
        df = df[df["id"] != exclude_event_id].copy()
    if df.empty:
        return _empty_catalog()
    df["mag_bin"] = df["mag"].apply(_mag_bin_label)
    result = df.reset_index(drop=True)
    result.attrs["source"] = "local_usgs_catalog"
    result.attrs["usgs_query_limit"] = len(result)
    result.attrs["usgs_limit_hit"] = False
    return result


def exclude_mainshock_like(
    catalog: pd.DataFrame,
    mainshock: MainShock,
    *,
    max_time_seconds: int = 3600,
    max_distance_km: float = 50.0,
    max_mag_delta: float = 0.5,
) -> tuple[pd.DataFrame, int]:
    """Remove rows that look like the mainshock when no exact event id is available.

    Manual mode uses event_id="manual", so the USGS catalog cannot remove the
    mainshock by id. A tight time/space/magnitude match keeps the historical
    statistics from counting the target event itself.
    """
    if catalog.empty or "time" not in catalog.columns:
        return catalog, 0

    times = pd.to_datetime(catalog["time"], utc=True, errors="coerce").dt.tz_convert(None)
    time_delta = (times - mainshock.time_utc).abs().dt.total_seconds()
    dist = catalog.get("dist_km")
    if dist is None:
        dist = haversine_km(
            mainshock.latitude,
            mainshock.longitude,
            catalog["latitude"].values,
            catalog["longitude"].values,
        )
    mag_delta = (catalog["mag"].astype(float) - float(mainshock.magnitude)).abs()
    mask = (
        (time_delta <= max_time_seconds)
        & (dist.astype(float) <= max_distance_km)
        & (mag_delta <= max_mag_delta)
    )
    removed = int(mask.sum())
    if removed == 0:
        return catalog, 0
    attrs = dict(catalog.attrs)
    result = catalog.loc[~mask].reset_index(drop=True)
    result.attrs.update(attrs)
    return result, removed


def _empty_catalog() -> pd.DataFrame:
    cols = ["time", "latitude", "longitude", "depth", "mag", "magType",
            "id", "place", "dist_km", "mag_bin"]
    return pd.DataFrame(columns=cols)


def _mag_bin_label(m: float) -> str:
    """5 档标签，与地图图例一致。"""
    if m >= 8.0:
        return "M≥8"
    if m >= 7.0:
        return "7≤M<8"
    if m >= 6.0:
        return "6≤M<7"
    if m >= 5.0:
        return "5≤M<6"
    if m >= 4.0:
        return "4≤M<5"
    return "3≤M<4"


# ============================================================================
# Haversine 距离
# ============================================================================

import numpy as np


def haversine_km(lat1, lon1, lat2, lon2):
    """计算两点间大圆距离（km）。支持标量或数组。"""
    R = 6371.0088
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lon1 = np.radians(np.asarray(lon1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    lon2 = np.radians(np.asarray(lon2, dtype=float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# ============================================================================
# 档位统计 + 最近事件
# ============================================================================

@dataclass
class CatalogStats:
    """目录统计结果。"""

    n3: int = 0   # M≥3
    n4: int = 0   # M≥4
    n5: int = 0   # M≥5
    n6: int = 0   # M≥6
    n7: int = 0   # M≥7
    n8: int = 0   # M≥8

    nearest_m8: Optional[pd.Series] = None
    nearest_m7: Optional[pd.Series] = None
    nearest_m6: Optional[pd.Series] = None
    nearest_m5: Optional[pd.Series] = None

    query: Optional[CatalogQuery] = None
    use_since_1950: bool = False
    total_count: int = 0
    mc_estimate: Optional[float] = None
    mc_method: str = ""
    query_limit_hit: bool = False
    query_limit: int = USGS_CATALOG_LIMIT


def compute_stats(catalog: pd.DataFrame, query: CatalogQuery) -> CatalogStats:
    """按档位统计并找出各档最近事件。"""
    s = CatalogStats(query=query)
    if catalog.empty:
        return s

    m = catalog["mag"]
    s.n3 = int((m >= 3).sum())
    s.n4 = int((m >= 4).sum())
    s.n5 = int((m >= 5).sum())
    s.n6 = int((m >= 6).sum())
    s.n7 = int((m >= 7).sum())
    s.n8 = int((m >= 8).sum())
    s.total_count = int(len(catalog))
    s.query_limit_hit = bool(catalog.attrs.get("usgs_limit_hit", False))
    s.query_limit = int(catalog.attrs.get("usgs_query_limit", USGS_CATALOG_LIMIT))
    s.mc_estimate, s.mc_method = estimate_completeness_magnitude(catalog)

    # 各档最近事件
    def nearest(mask):
        sub = catalog[mask]
        if sub.empty:
            return None
        idx = sub["dist_km"].idxmin()
        return sub.loc[idx]

    s.nearest_m8 = nearest(m >= 8)
    s.nearest_m7 = nearest((m >= 7) & (m < 8))
    s.nearest_m6 = nearest((m >= 6) & (m < 7))
    s.nearest_m5 = nearest((m >= 5) & (m < 6))

    s.use_since_1950 = False
    return s


def estimate_completeness_magnitude(catalog: pd.DataFrame) -> tuple[Optional[float], str]:
    """Estimate catalog completeness magnitude with a conservative max-curvature rule.

    This is a catalog diagnostic, not a validated regional completeness study.
    """
    if catalog.empty or "mag" not in catalog:
        return None, "事件数不足，未估计"
    mags = pd.to_numeric(catalog["mag"], errors="coerce").dropna()
    if len(mags) < 50:
        return None, "事件数不足，未估计"
    lo = max(0.0, float(np.floor(mags.min() * 10) / 10))
    hi = float(np.ceil(mags.max() * 10) / 10 + 0.1)
    bins = np.arange(lo, hi + 0.1, 0.1)
    if len(bins) < 3:
        return None, "震级范围过窄，未估计"
    counts, edges = np.histogram(mags, bins=bins)
    peak = int(np.argmax(counts))
    mc = float(round(edges[peak] + 0.2, 1))
    return mc, "最大曲率法近似估计；仅作目录完整性提示"
