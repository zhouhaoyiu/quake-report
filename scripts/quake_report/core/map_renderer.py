"""
震中周边历史地震分布图渲染器。

用 cartopy + matplotlib 实现，严格复刻参考模板风格：
- 黄色五角星 = 主震震中
- 红色圆，按震级 5 档大小分级（3≤M<4 / 4≤M<5 / 5≤M<6 / 6≤M<7 / M≥7）
- 黑色断层线（来自 GEM Global Active Faults）
- 海岸线 + 国界（cartopy Natural Earth）
- 200km 半径虚线圆
- 比例尺
- 经纬度刻度
- 右下角中文图例
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patheffects as path_effects
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch

import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io import shapereader
from cartopy.geodesic import Geodesic
import shapefile

from .usgs_client import MainShock, CatalogQuery
from .fault_loader import load_faults_in_bbox

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHINA_BOUNDARY_DIR = PROJECT_ROOT / "data/china_boundaries"
TIANDITU_CHINA_GEOJSON = CHINA_BOUNDARY_DIR / "tianditu_china_level2.geojson"
TIANDITU_CHINA_CITIES = CHINA_BOUNDARY_DIR / "tianditu_china_cities.json"
CHINA_BBOX = (70.0, 140.0, 3.0, 56.0)

# ----------------------------------------------------------------------------
# 中文字体注册
# ----------------------------------------------------------------------------
_FONT_REGISTERED = False
_FONT_PROP = None
_FONT_PROP_BOLD = None


def _ensure_font():
    global _FONT_REGISTERED, _FONT_PROP, _FONT_PROP_BOLD
    if _FONT_REGISTERED:
        return
    for p in [
        "/usr/share/fonts/google-noto/NotoSansSC-Regular.otf",
        "/usr/share/fonts/google-noto/NotoSansSC-Bold.otf",
        "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Regular.ttf",
        "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Bold.ttf",
        "/usr/share/fonts/google-noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
            except Exception:
                pass
    preferred = [
        "Source Han Sans SC", "Noto Sans SC", "Noto Sans CJK SC",
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "DejaVu Sans",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    families = [name for name in preferred if name in available] or ["DejaVu Sans"]
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = families
    plt.rcParams["font.serif"] = ["Noto Serif SC", "DejaVu Serif"]
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_PROP = fm.FontProperties(family=families)
    _FONT_PROP_BOLD = fm.FontProperties(family=families, weight="bold")
    _FONT_REGISTERED = True


def _map_font(bold: bool = False):
    _ensure_font()
    return _FONT_PROP_BOLD if bold else _FONT_PROP


# 震级 → 圆点大小（pt²）与边框颜色
MAG_BINS = [
    (3.0, 4.0, "3≤M<4", 12, "#ffb3b3"),
    (4.0, 5.0, "4≤M<5", 28, "#ff7070"),
    (5.0, 6.0, "5≤M<6", 55, "#ff3030"),
    (6.0, 7.0, "6≤M<7", 95, "#cc0000"),
    (7.0, float("inf"), "M≥7",   160, "#800000"),
]


def _mag_to_size_color(m: float):
    for lo, hi, label, size, color in MAG_BINS:
        if lo <= m < hi:
            return size, color, label
    return 12, "#ffb3b3", "3≤M<4"


def _bbox_around(lat: float, lon: float, radius_km: float, pad_factor: float = 1.2):
    """根据震中与查询半径计算 bbox。"""
    # 1° 纬度 ≈ 111.32 km；1° 经度 ≈ 111.32*cos(lat)
    dlat = (radius_km * pad_factor) / 111.32
    dlon = dlat / max(np.cos(np.radians(lat)), 0.1)
    return (
        max(-180.0, lon - dlon),
        min(180.0, lon + dlon),
        max(-90.0, lat - dlat),
        min(90.0, lat + dlat),
    )


def render_distribution_map(
    mainshock: MainShock,
    catalog: pd.DataFrame,
    query: CatalogQuery,
    output_path: str,
    title_zh: Optional[str] = None,
    title_en: Optional[str] = None,
    dpi: int = 200,
    map_view: str = "mag",
) -> str:
    """渲染震中周边历史地震分布图。

    Args:
        mainshock: 主震对象
        catalog: 历史地震目录（含 dist_km, mag 列）
        query: 查询参数（用于确定半径圆）
        output_path: 输出 PNG 路径
        title_zh / title_en: 图标题

    Returns:
        output_path（同一参数）
    """
    _ensure_font()

    lat0, lon0 = mainshock.latitude, mainshock.longitude
    radius_km = query.max_radius_km

    # bbox
    min_lon, max_lon, min_lat, max_lat = _bbox_around(lat0, lon0, radius_km, pad_factor=1.25)

    # 画布
    fig = plt.figure(figsize=(8.5, 7.0), constrained_layout=False)
    proj = ccrs.PlateCarree()
    ax = fig.add_axes([0.08, 0.10, 0.88, 0.82], projection=proj)
    ax.set_extent([min_lon, max_lon, min_lat, max_lat], crs=proj)

    # ---- 地理底图要素 ----
    # 海洋 / 陆地填色（淡）
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f5f3ed", zorder=0)
    ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#e7f0f5", zorder=0)
    if _intersects_bbox((min_lon, max_lon, min_lat, max_lat), CHINA_BBOX):
        _draw_china_official_boundaries(ax, min_lon, max_lon, min_lat, max_lat, proj)
    else:
        # 海岸线 + 国界
        ax.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.8, edgecolor="#444", zorder=1)
        ax.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.6, edgecolor="#666",
                       linestyle="--", zorder=1)

    # ---- 200km 半径圆 ----
    # 用 cartopy Geodesic 计算圆周点
    gd = Geodesic()
    n_pts = 128
    azis = np.linspace(0, 360, n_pts)
    dists = np.full(n_pts, radius_km * 1000.0)
    # Geodesic.direct(points, azimuths, distances)
    pts = gd.direct([lon0, lat0], azis, dists)
    clons = [p[0] for p in pts]
    clats = [p[1] for p in pts]
    ax.plot(clons, clats, color="#1f78b4", linewidth=1.8, linestyle="--",
            transform=proj, zorder=3)

    # ---- 断层线（GEM） ----
    try:
        faults = load_faults_in_bbox(min_lon, max_lon, min_lat, max_lat)
        for f in faults:
            if len(f.points) >= 2:
                xs, ys = zip(*f.points)
                ax.plot(xs, ys, color="#7a3f2b", linewidth=0.9,
                        transform=proj, zorder=2, alpha=0.9)
    except Exception as e:
        # 断层加载失败不应阻断出图
        print(f"[fault_loader] WARN: {e}")

    if _intersects_bbox((min_lon, max_lon, min_lat, max_lat), CHINA_BBOX):
        _draw_china_city_labels(ax, min_lon, max_lon, min_lat, max_lat, lon0, lat0, proj)
    else:
        _draw_global_city_labels(ax, min_lon, max_lon, min_lat, max_lat, lon0, lat0, proj)

    # ---- 历史地震圆点 ----
    all_map_catalog = _catalog_for_map_display(catalog)
    map_catalog = _catalog_for_map_display(catalog, min_mag=4.0 if map_view == "m4" else None)
    if not map_catalog.empty:
        if map_view == "time":
            dated = map_catalog.copy()
            dated["_map_time"] = pd.to_datetime(dated.get("time"), errors="coerce", utc=True)
            dated = dated.dropna(subset=["_map_time"])
            if not dated.empty:
                sizes = dated["_map_mag"].map(lambda m: _mag_to_size_color(float(m))[0] * 0.8)
                sc = ax.scatter(
                    dated["longitude"], dated["latitude"],
                    s=sizes, c=mdates.date2num(dated["_map_time"].dt.to_pydatetime()),
                    cmap="YlOrRd", alpha=0.72, edgecolors="#4a0000",
                    linewidths=0.3, transform=proj, zorder=4,
                )
                cb = fig.colorbar(sc, ax=ax, shrink=0.64, pad=0.02)
                cb.set_label("事件时间 / Event time", fontsize=8)
                cb.ax.yaxis.set_major_formatter(mdates.DateFormatter("%Y"))
                cb.ax.tick_params(labelsize=7)
        else:
            for lo, hi, _, size, color in MAG_BINS:
                sub = map_catalog[(map_catalog["_map_mag"] >= lo) & (map_catalog["_map_mag"] < hi)]
                if sub.empty:
                    continue
                point_size, point_alpha, dense_small = _adaptive_point_style(size, len(sub), len(map_catalog), hi)
                ax.scatter(
                    sub["longitude"], sub["latitude"],
                    s=point_size,
                    c=color,
                    alpha=point_alpha,
                    edgecolors="none" if dense_small else "#4a0000",
                    linewidths=0 if dense_small else 0.35,
                    transform=proj, zorder=4,
                    rasterized=dense_small,
                )

    _draw_map_count_note(ax, len(map_catalog), len(all_map_catalog), map_view)

    # ---- 主震五角星 ----
    ax.scatter(
        lon0, lat0,
        marker="*", s=600, c="#ffd400", edgecolors="#000",
        linewidths=1.2, transform=proj, zorder=10,
    )

    # ---- 经纬度刻度 ----
    gl = ax.gridlines(draw_labels=True, linewidth=0.4, color="#aaa", alpha=0.6,
                      linestyle=":", x_inline=False, y_inline=False)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 9, "color": "#333"}
    gl.ylabel_style = {"size": 9, "color": "#333"}

    # ---- 标题 ----
    if title_zh:
        ax.set_title(
            f"{title_zh}\n{title_en or ''}",
            fontsize=12, pad=14, fontproperties=_map_font(True),
        )

    # ---- 比例尺 ----
    _draw_scale_bar(ax, min_lon, max_lon, min_lat, max_lat, proj)

    # ---- 图例（右下角） ----
    _draw_legend(ax, mainshock, radius_km, map_view=map_view)

    # 保存
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor="white", pil_kwargs={"compress_level": 2})
    plt.close(fig)
    return output_path


def _catalog_for_map_display(catalog: pd.DataFrame, min_mag: float | None = None) -> pd.DataFrame:
    if catalog.empty:
        return catalog.copy()
    df = catalog.copy()
    df["_map_mag"] = pd.to_numeric(df.get("mag"), errors="coerce")
    df = df.dropna(subset=["longitude", "latitude", "_map_mag"])
    if min_mag is not None:
        df = df[df["_map_mag"] >= min_mag]
    return df.sort_values("_map_mag", ascending=True)


def _adaptive_point_style(size: float, bin_count: int, total_count: int, hi: float) -> tuple[float, float, bool]:
    dense_small = hi <= 4.0 and bin_count > 1200
    if not dense_small:
        return size, 0.68, False
    if total_count > 12000:
        return 5.0, 0.22, True
    if total_count > 6000:
        return 6.0, 0.28, True
    return 8.0, 0.34, True


def _draw_map_count_note(ax, shown: int, total: int, map_view: str):
    mode = {
        "m4": "图面隐藏 M3-M4",
        "time": "按时间着色",
    }.get(map_view, "全量按震级显示")
    ax.text(
        0.02, 0.98,
        f"{mode}；地图显示 {shown}/{total} 条，统计使用全量目录",
        transform=ax.transAxes, ha="left", va="top", fontsize=7.2, color="#333",
        fontproperties=_map_font(),
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#999", "alpha": 0.88},
        zorder=40,
    )


def _draw_scale_bar(ax, min_lon, max_lon, min_lat, max_lat, proj):
    """画一个简单的比例尺。长度根据纬度自适应。"""
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat
    lat_ref = min_lat + lat_span / 2
    km_per_deg_lon = 111.32 * max(np.cos(np.radians(lat_ref)), 0.1)
    # 取一个接近图宽 1/5 的常用长度
    candidates = [5, 10, 20, 50, 100, 200, 500, 1000]
    target_km = lon_span * km_per_deg_lon * 0.2
    bar_km = min(candidates, key=lambda x: abs(x - target_km))
    bar_deg = bar_km / km_per_deg_lon

    x0 = min_lon + 0.06 * lon_span
    y0 = min_lat + 0.08 * lat_span
    x1 = x0 + bar_deg
    tick_h = 0.05 * lat_span

    ax.plot([x0, x1], [y0, y0], color="black", linewidth=2.5, transform=proj, zorder=20)
    ax.plot([x0, x0], [y0, y0 + tick_h], color="black", linewidth=1.5, transform=proj, zorder=20)
    ax.plot([x1, x1], [y0, y0 + tick_h], color="black", linewidth=1.5, transform=proj, zorder=20)
    ax.text((x0 + x1) / 2, y0 + tick_h * 1.15, f"{bar_km} km",
            ha="center", va="bottom", fontsize=8, transform=proj, zorder=20,
            fontproperties=_map_font())


def _intersects_bbox(a, b) -> bool:
    return not (a[1] < b[0] or a[0] > b[1] or a[3] < b[2] or a[2] > b[3])


def _china_boundary_files() -> list[Path]:
    env_path = os.environ.get("QUAKE_CHINA_BOUNDARY_SHP")
    if env_path:
        return [Path(env_path)]
    return sorted(CHINA_BOUNDARY_DIR.rglob("BOUL*.shp"))


def _draw_china_official_boundaries(ax, min_lon, max_lon, min_lat, max_lat, proj):
    shp_files = [p for p in _china_boundary_files() if p.exists()]
    if not shp_files and TIANDITU_CHINA_GEOJSON.exists():
        _draw_china_tianditu_geojson(ax, min_lon, max_lon, min_lat, max_lat, proj)
        return
    if not shp_files:
        raise RuntimeError(
            "中国区域地图需要国内官方边界数据：请把全国地理信息资源目录服务系统"
            "1:100万公众版基础地理信息数据（2021）的 BOUL*.shp 放到 data/china_boundaries/，"
            "或放入天地图行政区划 GeoJSON 缓存。"
        )
    for shp_path in shp_files:
        reader = shapefile.Reader(str(shp_path), encoding="gbk", encodingErrors="replace")
        fields = [f[0] for f in reader.fields[1:]]
        for shape, record in zip(reader.shapes(), reader.records()):
            if not _intersects_bbox((shape.bbox[0], shape.bbox[2], shape.bbox[1], shape.bbox[3]),
                                    (min_lon, max_lon, min_lat, max_lat)):
                continue
            attrs = dict(zip(fields, record))
            code = str(attrs.get("GB") or attrs.get("gb") or attrs.get("CODE") or attrs.get("code") or "")
            color, linewidth, alpha = _china_boundary_style(code)
            parts = list(shape.parts) + [len(shape.points)]
            for i in range(len(parts) - 1):
                pts = shape.points[parts[i]:parts[i + 1]]
                kept = [(x, y) for x, y in pts if min_lon <= x <= max_lon and min_lat <= y <= max_lat]
                if len(kept) >= 2:
                    xs, ys = zip(*kept)
                    ax.plot(xs, ys, color=color, linewidth=linewidth,
                            linestyle="-", alpha=alpha, transform=proj, zorder=1.5)
        reader.close()


def _china_boundary_style(code: str) -> tuple[str, float, float]:
    # ponytail: BOUL code prefixes are enough for map hierarchy; add a code table if labels are needed.
    if code.startswith("63"):
        return "#222222", 1.15, 0.95
    if code.startswith("64"):
        return "#4a4a4a", 0.8, 0.85
    return "#777777", 0.45, 0.65


def _draw_china_tianditu_geojson(ax, min_lon, max_lon, min_lat, max_lat, proj):
    data = _load_tianditu_china_geojson()
    target_bbox = (min_lon, max_lon, min_lat, max_lat)
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        rings = _geojson_rings(geom)
        for ring in rings:
            if len(ring) < 2:
                continue
            xs, ys = zip(*ring)
            if not _intersects_bbox((min(xs), max(xs), min(ys), max(ys)), target_bbox):
                continue
            ax.plot(xs, ys, color="#6a6a6a", linewidth=0.55,
                    linestyle="-", transform=proj, zorder=1.4)
    _draw_tianditu_outer_boundary(ax, target_bbox, proj)


@lru_cache(maxsize=1)
def _load_tianditu_china_geojson() -> dict:
    with TIANDITU_CHINA_GEOJSON.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_tianditu_china_cities() -> tuple[dict, ...]:
    if not TIANDITU_CHINA_CITIES.exists():
        return tuple()
    with TIANDITU_CHINA_CITIES.open("r", encoding="utf-8") as f:
        return tuple(json.load(f))


def _draw_tianditu_outer_boundary(ax, target_bbox, proj):
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        geoms = [
            shape(feature["geometry"])
            for feature in _load_tianditu_china_geojson().get("features", [])
            if feature.get("geometry")
        ]
        boundary = unary_union(geoms).boundary
    except Exception:
        return
    for line in _iter_lines(boundary):
        xs, ys = line.xy
        if not _intersects_bbox((min(xs), max(xs), min(ys), max(ys)), target_bbox):
            continue
        ax.plot(xs, ys, color="#222222", linewidth=1.25, linestyle="-",
                transform=proj, zorder=1.8)


def _iter_lines(geom):
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "LineString":
        yield geom
        return
    for part in getattr(geom, "geoms", []):
        yield from _iter_lines(part)


def _draw_china_city_labels(ax, min_lon, max_lon, min_lat, max_lat, lon0, lat0, proj):
    cities = [
        c for c in _load_tianditu_china_cities()
        if min_lon <= float(c.get("lng", 999)) <= max_lon
        and min_lat <= float(c.get("lat", 999)) <= max_lat
        and _is_city_label(c)
    ]
    if not cities:
        return
    max_labels = 10 if (max_lon - min_lon) > 8 else 14
    cities.sort(key=lambda c: (float(c["lng"]) - lon0) ** 2 + (float(c["lat"]) - lat0) ** 2)
    for city in cities[:max_labels]:
        lon, lat = float(city["lng"]), float(city["lat"])
        name = _short_city_name(str(city.get("name", "")))
        _draw_city_label(ax, lon, lat, name, proj)


def _draw_global_city_labels(ax, min_lon, max_lon, min_lat, max_lat, lon0, lat0, proj):
    cities = [
        c for c in _load_global_cities()
        if min_lon <= c["lng"] <= max_lon and min_lat <= c["lat"] <= max_lat
    ]
    if not cities:
        return
    max_labels = 8 if (max_lon - min_lon) > 8 else 12
    cities.sort(key=lambda c: ((c["lng"] - lon0) ** 2 + (c["lat"] - lat0) ** 2, -c["pop"]))
    for city in cities[:max_labels]:
        _draw_city_label(ax, city["lng"], city["lat"], city["name"], proj)


def nearest_city_rows(lat: float, lon: float, radius_km: float, limit: int = 5) -> list[list[str]]:
    if _intersects_bbox((lon, lon, lat, lat), CHINA_BBOX):
        cities = [
            {"name": _short_city_name(str(c.get("name", ""))), "lng": float(c["lng"]), "lat": float(c["lat"])}
            for c in _load_tianditu_china_cities()
            if c.get("lng") is not None and c.get("lat") is not None and _is_city_label(c)
        ]
    else:
        cities = list(_load_global_cities())
    rows = []
    for city in cities:
        dist = _haversine_km(lat, lon, float(city["lat"]), float(city["lng"]))
        if dist <= max(radius_km * 2, 300):
            rows.append((dist, city))
    rows.sort(key=lambda item: item[0])
    return [
        [str(city["name"]), f"{dist:.1f}", f"{float(city['lat']):.2f}°, {float(city['lng']):.2f}°"]
        for dist, city in rows[:limit]
    ]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlambda / 2) ** 2
    return float(2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))


def _draw_city_label(ax, lon: float, lat: float, name: str, proj):
    ax.scatter(lon, lat, s=12, marker="s", c="#222222", edgecolors="white",
               linewidths=0.35, transform=proj, zorder=6)
    ax.text(
        lon, lat, f" {name}", fontsize=7.2, color="#222222",
        ha="left", va="bottom", transform=proj, zorder=6.5,
        fontproperties=_map_font(),
        path_effects=[path_effects.withStroke(linewidth=2.2, foreground="white", alpha=0.9)],
    )


@lru_cache(maxsize=1)
def _load_global_cities() -> tuple[dict, ...]:
    try:
        shp = shapereader.natural_earth("50m", "cultural", "populated_places")
        reader = shapereader.Reader(shp)
    except Exception as exc:
        print(f"[city_loader] WARN: {exc}")
        return tuple()
    cities = []
    for record in reader.records():
        attrs = record.attributes
        name = attrs.get("NAMEASCII") or attrs.get("NAME_EN") or attrs.get("NAME")
        if not name:
            continue
        try:
            lon = float(attrs.get("LONGITUDE") or record.geometry.x)
            lat = float(attrs.get("LATITUDE") or record.geometry.y)
            pop = int(float(attrs.get("POP_MAX") or 0))
        except Exception:
            continue
        cities.append({"name": str(name), "lng": lon, "lat": lat, "pop": pop})
    return tuple(cities)


def _short_city_name(name: str) -> str:
    for suffix in ("特别行政区", "地区", "盟", "市"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    if name.endswith("自治州"):
        return (
            name.split("自治州", 1)[0]
            .replace("藏族羌族", "")
            .replace("土家族苗族", "")
            .replace("哈尼族彝族", "")
            .replace("蒙古族藏族", "")
            .replace("傣族景颇族", "")
            .replace("布依族苗族", "")
            .replace("苗族侗族", "")
            .replace("彝族", "")
            .replace("藏族", "")
        )
    return name


def _is_city_label(city: dict) -> bool:
    name = str(city.get("name", ""))
    if not name or name == "境界线":
        return False
    if name.endswith(("省", "自治区")):
        return False
    return True


def _geojson_rings(geom: dict) -> list[list[tuple[float, float]]]:
    if geom.get("type") == "Polygon":
        return [[tuple(point[:2]) for point in ring] for ring in geom.get("coordinates", [])]
    if geom.get("type") == "MultiPolygon":
        return [
            [tuple(point[:2]) for point in ring]
            for polygon in geom.get("coordinates", [])
            for ring in polygon
        ]
    return []


def _draw_legend(ax, mainshock: MainShock, radius_km: float, map_view: str = "mag"):
    """右下角图例框。"""
    # 图例条目
    legend_items = []
    # 主震
    legend_items.append(Line2D([0], [0], marker="*", color="w",
                               markerfacecolor="#ffd400", markeredgecolor="black",
                               markersize=16, markeredgewidth=1.0,
                               linestyle="None", label="震中  Epicenter"))
    if map_view == "time":
        legend_items.append(Line2D([0], [0], marker="o", color="w",
                                   markerfacecolor="#d94801", markeredgecolor="#4a0000",
                                   markeredgewidth=0.6, markersize=6,
                                   linestyle="None", label="历史地震按时间着色"))
    else:
        for lo, hi, label, size, color in MAG_BINS:
            if map_view == "m4" and hi <= 4.0:
                continue
            legend_items.append(Line2D([0], [0], marker="o", color="w",
                                       markerfacecolor=color, markeredgecolor="#4a0000",
                                       markeredgewidth=0.6,
                                       markersize=_size_to_marker(size),
                                       linestyle="None", label=f"{label}"))
    # 断层
    legend_items.append(Line2D([0], [0], color="#7a3f2b", linewidth=1.6,
                               linestyle="-", label="断层  Fault"))
    # 半径圆
    legend_items.append(Line2D([0], [0], color="#1f78b4", linewidth=1.8,
                               linestyle="--", label=f"{int(radius_km)} km 半径"))

    # 标题用中英双语
    leg = ax.legend(
        handles=legend_items,
        loc="lower right",
        fontsize=9,
        title="图例 / Legend",
        title_fontsize=10,
        prop=_map_font(),
        frameon=True,
        fancybox=True,
        facecolor="white",
        edgecolor="#666",
        framealpha=0.95,
        borderpad=1.0,
        labelspacing=0.5,
        handletextpad=0.8,
    )
    leg.set_zorder(30)
    # 标题字体加粗
    try:
        for text in leg.get_texts():
            text.set_fontproperties(_map_font())
        leg.get_title().set_fontproperties(_map_font(True))
        leg.get_title().set_fontweight("bold")
        leg.get_title().set_color("#222")
    except Exception:
        pass


def _size_to_marker(s: float) -> float:
    """scatter s (pt²) → legend markersize (pt 直径)。"""
    # markersize 是直径；s 是面积，sqrt(s)*某常数。经验缩放：
    return max(4, (s ** 0.5) * 0.55)


def _self_check_map_catalog():
    df = pd.DataFrame({
        "longitude": np.linspace(70, 71, 1800),
        "latitude": np.linspace(36, 37, 1800),
        "mag": [3.2] * 1000 + [4.2] * 500 + [5.2] * 200 + [6.2] * 50 + [7.2] * 50,
    })
    shown = _catalog_for_map_display(df)
    shown_m4 = _catalog_for_map_display(df, min_mag=4.0)
    assert len(df) == 1800
    assert len(shown) == 1800
    assert len(shown_m4) == 800
    assert shown["_map_mag"].is_monotonic_increasing


if __name__ == "__main__":
    _self_check_map_catalog()
