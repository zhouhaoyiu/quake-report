"""
历史地震统计叙述文字构建器（中英双语 + 时区切换）。

支持三种时区显示模式：
- "utc": 全部用 UTC 时间（默认，与原模板一致）
- "utc8" / "cn": 全部用北京时间 (UTC+8)
- "both": 同时显示 UTC 和北京时间（推荐，最严谨）

参考模板：

【模板 A - 完整版（N7>0 或 N8>0）】
据统计，在本次地震的震中周围200千米以内，发生3级以上地震{N3}次，4级以上地震为{N4}次，
5级以上地震{N5}次，6级以上地震{N6}次，7级以上地震{N7}次，8级以上地震{N8}次。
距离震中最近的8级及以上地震为UTC时间{Y8}年{Mo8}月{D8}日{h8}点{m8}分发生的Mw {M8}地震，
震中距离约{dist8}千米。
...
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Optional

import pandas as pd

from .usgs_client import CatalogStats, MainShock
from .formatting import format_km


Timezone = Literal["utc", "utc8", "cn", "both"]

# 北京时间偏移
_BJ_OFFSET = timedelta(hours=8)


def _to_bj(dt_utc: datetime) -> datetime:
    """UTC naive datetime → 北京时间 naive datetime"""
    return dt_utc + _BJ_OFFSET


def _parse_time(t) -> datetime:
    """解析 USGS time 字段（CSV 字符串或 GeoJSON 时间戳）。"""
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t / 1000.0, tz=__import__("datetime").timezone.utc).replace(tzinfo=None)
    s = str(t)
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)


# ============================================================================
# 时间格式化（按 tz 输出）
# ============================================================================

def _fmt_time_zh(dt_utc: datetime, tz: Timezone) -> str:
    """中文时间字符串。"""
    if tz == "utc":
        return (
            f"UTC时间{dt_utc.year}年{dt_utc.month}月{dt_utc.day}日"
            f"{dt_utc.hour}点{dt_utc.minute:02d}分"
        )
    if tz in ("utc8", "cn"):
        t = _to_bj(dt_utc)
        return (
            f"北京时间{t.year}年{t.month}月{t.day}日"
            f"{t.hour}点{t.minute:02d}分"
        )
    # both
    t = _to_bj(dt_utc)
    return (
        f"UTC时间{dt_utc.year}年{dt_utc.month}月{dt_utc.day}日"
        f"{dt_utc.hour}点{dt_utc.minute:02d}分"
        f"（北京时间{t.year}年{t.month}月{t.day}日"
        f"{t.hour}点{t.minute:02d}分）"
    )


def _fmt_time_en(dt_utc: datetime, tz: Timezone) -> str:
    """英文时间字符串。"""
    if tz == "utc":
        return dt_utc.strftime("%H:%M UTC on %d %B %Y")
    if tz in ("utc8", "cn"):
        t = _to_bj(dt_utc)
        return t.strftime("%H:%M (UTC+8) on %d %B %Y")
    # both
    t = _to_bj(dt_utc)
    return (
        f"{dt_utc.strftime('%H:%M UTC on %d %B %Y')} "
        f"({t.strftime('%H:%M UTC+8, %d %B %Y')})"
    )


def _fmt_event_zh(row: pd.Series, mag_type: str, tz: Timezone) -> str:
    """格式化历史事件说明。"""
    dt = _parse_time(row["time"])
    dist = float(row["dist_km"])
    return (
        f"{_fmt_time_zh(dt, tz)}的 {mag_type} {row['mag']:.1f} 地震，"
        f"距本次震中约 {dist:.1f} km"
    )


def _fmt_event_en(row: pd.Series, mag_type: str, tz: Timezone) -> str:
    dt = _parse_time(row["time"])
    dist = float(row["dist_km"])
    return (
        f"the {mag_type} {row['mag']:.1f} earthquake at {_fmt_time_en(dt, tz)}, "
        f"approximately {dist:.1f} km from the epicenter"
    )


def _fmt_mag_threshold(value: float, *, en: bool = False) -> str:
    value = float(value)
    text = str(int(value)) if value.is_integer() else f"{value:.1f}".rstrip("0").rstrip(".")
    return f"M>={text}" if en and not value.is_integer() else f"M≥{text}" if not en and not value.is_integer() else f"M{text}+"


def _query_min_mag(stats: CatalogStats) -> float:
    if stats.query is None or stats.query.min_magnitude is None:
        return 3.0
    return float(stats.query.min_magnitude)


def _query_start_year(stats: CatalogStats) -> int:
    if stats.query is None or stats.query.start_time is None:
        return 1900
    return int(stats.query.start_time.year)


def _cumulative_counts_zh(stats: CatalogStats) -> str:
    min_mag = _query_min_mag(stats)
    parts = []
    if min_mag <= 3:
        parts.append(f"3.0级以上地震{stats.n3} 次")
    else:
        parts.append(f"{min_mag:.1f}级以上地震{stats.total_count} 次")
    for threshold, count in [(4, stats.n4), (5, stats.n5), (6, stats.n6), (7, stats.n7), (8, stats.n8)]:
        if min_mag < threshold:
            parts.append(f"{threshold:.1f}级以上地震 {count} 次")
    return "，".join(parts)


def _cumulative_counts_en(stats: CatalogStats) -> str:
    min_mag = _query_min_mag(stats)
    parts = []
    if min_mag <= 3:
        parts.append(f"{stats.n3} M3+ earthquakes")
    else:
        parts.append(f"{stats.total_count} {_fmt_mag_threshold(min_mag, en=True)} earthquakes")
    for threshold, count in [(4, stats.n4), (5, stats.n5), (6, stats.n6), (7, stats.n7), (8, stats.n8)]:
        if min_mag < threshold:
            parts.append(f"{count} M{threshold}+ earthquakes")
    return ", ".join(parts)


# ============================================================================
# 中文叙述
# ============================================================================

def build_narrative_zh(
    mainshock: MainShock,
    stats: CatalogStats,
    fig_num: str = "1",
    radius_km: float = 200.0,
    mag_type: str = "Mw",
    tz: Timezone = "utc",
) -> str:
    """构建中文叙述段落。"""
    head = f"据统计，在本次地震的震中周围{format_km(radius_km)}千米以内，自 {_query_start_year(stats)} 年以来，发生"
    counts_zh = f"{_cumulative_counts_zh(stats)}。"

    recent_parts = []
    if stats.nearest_m8 is not None:
        recent_parts.append(
            f"距震中最近的 8.0级以上地震为{_fmt_event_zh(stats.nearest_m8, mag_type, tz)}。"
        )
    if stats.nearest_m7 is not None:
        recent_parts.append(
            f"距震中最近的 7.0-7.9 级地震为{_fmt_event_zh(stats.nearest_m7, mag_type, tz)}。"
        )
    if stats.nearest_m6 is not None:
        recent_parts.append(
            f"距震中最近的 6.0-6.9 级地震为{_fmt_event_zh(stats.nearest_m6, mag_type, tz)}。"
        )
    if stats.nearest_m5 is not None:
        recent_parts.append(
            f"距震中最近的 5.0-5.9 级地震为{_fmt_event_zh(stats.nearest_m5, mag_type, tz)}。"
        )

    tail = f"此次地震的震中周围历史地震分布图见图 {fig_num}。"

    return head + counts_zh + "".join(recent_parts) + tail


# ============================================================================
# 英文叙述
# ============================================================================

def build_narrative_en(
    mainshock: MainShock,
    stats: CatalogStats,
    fig_num: str = "1",
    radius_km: float = 200.0,
    mag_type: str = "Mw",
    tz: Timezone = "utc",
) -> str:
    head = (
        f"According to statistics, since {_query_start_year(stats)}, within a {format_km(radius_km)}-km radius "
        f"around the epicenter of this earthquake, "
    )

    counts_en = f"the USGS catalog contains {_cumulative_counts_en(stats)}. "

    recent_parts = []
    if stats.nearest_m8 is not None:
        recent_parts.append(
            f"The nearest earthquake of magnitude 8.0 and above was {_fmt_event_en(stats.nearest_m8, mag_type, tz)}. "
        )
    if stats.nearest_m7 is not None:
        recent_parts.append(
            f"The nearest earthquake of magnitude 7.0-8.0 was {_fmt_event_en(stats.nearest_m7, mag_type, tz)}. "
        )
    if stats.nearest_m6 is not None:
        recent_parts.append(
            f"The nearest earthquake of magnitude 6.0-7.0 was {_fmt_event_en(stats.nearest_m6, mag_type, tz)}. "
        )
    if stats.nearest_m5 is not None:
        recent_parts.append(
            f"The nearest earthquake of magnitude 5.0-6.0 was {_fmt_event_en(stats.nearest_m5, mag_type, tz)}. "
        )

    tail = f"The distribution of historical earthquakes around the epicenter is shown in Figure {fig_num}."

    return head + counts_en + "".join(recent_parts) + " " + tail


# ============================================================================
# 主震基本信息文字（支持时区）
# ============================================================================

def build_mainshock_summary_zh_v2(
    mainshock: MainShock,
    tz: Timezone = "utc",
) -> str:
    """主震概要（支持时区）。"""
    lat_str = f"南纬{abs(mainshock.latitude):.2f}°" if mainshock.latitude < 0 else f"北纬{mainshock.latitude:.2f}°"
    if mainshock.longitude < 0:
        lon_str = f"西经{abs(mainshock.longitude):.2f}°"
    else:
        lon_str = f"东经{mainshock.longitude:.2f}°"
    time_str = _fmt_time_zh(mainshock.time_utc, tz)
    return (
        f"本次地震发生于{time_str}，震中位于{lat_str}、{lon_str}，"
        f"震源深度约 {mainshock.depth_km:.1f} km，震级为 {mainshock.mag_type} {mainshock.magnitude:.1f}。"
    )


def build_mainshock_summary_en(
    mainshock: MainShock,
    tz: Timezone = "utc",
) -> str:
    lat_str = f"{mainshock.latitude:.2f}°{'S' if mainshock.latitude < 0 else 'N'}"
    lon_str = f"{abs(mainshock.longitude):.2f}°{'W' if mainshock.longitude < 0 else 'E'}"
    time_str = _fmt_time_en(mainshock.time_utc, tz)
    return (
        f"This earthquake occurred at {time_str}, "
        f"with epicenter at {lat_str}, {lon_str}, "
        f"focal depth approximately {mainshock.depth_km:.1f} km, "
        f"magnitude {mainshock.mag_type} {mainshock.magnitude:.1f}."
        + (f" Location name: {mainshock.place}." if mainshock.place else "")
    )


# ============================================================================
# 兼容旧 API（保留无 tz 参数调用）
# ============================================================================

def build_mainshock_summary_zh(mainshock: MainShock) -> str:
    """[已弃用] 旧版主震概要，请用 build_mainshock_summary_zh_v2。"""
    return build_mainshock_summary_zh_v2(mainshock, tz="utc")
