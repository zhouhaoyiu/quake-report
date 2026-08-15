"""
震中周边历史地震分布图渲染器。

用 cartopy + matplotlib 实现，严格复刻参考模板风格：
- 黄色五角星 = 主震震中
- 红色圆，按震级 5 档大小分级（3≤M<4 / 4≤M<5 / 5≤M<6 / 6≤M<7 / M≥7）
- 黑色断层线（来自 GEM Global Active Faults）
- 陆地填色（Natural Earth）；国内事件叠加天地图/BOUL 边界
- 经纬度直角投影，保持边框和经纬线横平竖直
- 图外比例尺
- 经纬度刻度
- 右下角中文图例
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from typing import Optional, TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patheffects as path_effects
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

import cartopy
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io import shapereader
import shapefile

from .fault_loader import load_faults_in_bbox

if TYPE_CHECKING:
    import pandas as pd
    from .usgs_client import MainShock, CatalogQuery

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_CARTOPY_DATA = PROJECT_ROOT / "data/cartopy"
if LOCAL_CARTOPY_DATA.exists():
    cartopy.config["pre_existing_data_dir"] = LOCAL_CARTOPY_DATA
CHINA_BOUNDARY_DIR = PROJECT_ROOT / "data/china_boundaries"
TIANDITU_CHINA_GEOJSON = CHINA_BOUNDARY_DIR / "tianditu_china_level2.geojson"
TIANDITU_CHINA_CITIES = CHINA_BOUNDARY_DIR / "tianditu_china_cities.json"
CHINA_BBOX = (70.0, 140.0, 3.0, 56.0)
MAP_OUTPUT_UNIT = "中国地震局工程力学研究所 强震动观测中心"
LAND_COLOR = "#f8e3c4"
OCEAN_COLOR = "#abc7df"

# ----------------------------------------------------------------------------
# 中英文字体注册：拉丁字符优先 Times New Roman，中文回退 SimSun
# ----------------------------------------------------------------------------
_FONT_REGISTERED = False
_FONT_PROP = None
_FONT_PROP_BOLD = None


def _ensure_font():
    global _FONT_REGISTERED, _FONT_PROP, _FONT_PROP_BOLD
    if _FONT_REGISTERED:
        return
    for p in [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf",
        str(Path.home() / "Library/Fonts/simsun.ttc"),
        "/usr/local/share/fonts/quake-report/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        str(Path.home() / "Library/Fonts/NotoSansCJKsc-Regular.otf"),
        str(Path.home() / "Library/Fonts/NotoSansCJKsc-Bold.otf"),
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
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
            except Exception:
                pass
    preferred = [
        "Times New Roman", "SimSun", "Songti SC", "STSong",
        "PingFang SC", "STHeiti",
        "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC",
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Heiti SC",
        "Hiragino Sans GB", "Arial Unicode MS", "DejaVu Serif", "DejaVu Sans",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    families = [name for name in preferred if name in available] or ["DejaVu Serif"]
    plt.rcParams["font.family"] = families
    plt.rcParams["font.sans-serif"] = families
    plt.rcParams["font.serif"] = families
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_PROP = fm.FontProperties(family=families)
    _FONT_PROP_BOLD = fm.FontProperties(family=families, weight="bold")
    _FONT_REGISTERED = True


def _map_font(bold: bool = False):
    _ensure_font()
    return _FONT_PROP_BOLD if bold else _FONT_PROP


def _pandas():
    import pandas as pd

    return pd


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


def _expand_bbox_for_points(
    bbox: tuple[float, float, float, float],
    points: pd.DataFrame,
    margin_ratio: float = 0.10,
) -> tuple[float, float, float, float]:
    """Expand the visual map extent so plotted points do not sit on the frame."""
    pd = _pandas()
    min_lon, max_lon, min_lat, max_lat = bbox
    if not points.empty:
        lon = pd.to_numeric(points.get("longitude"), errors="coerce").dropna()
        lat = pd.to_numeric(points.get("latitude"), errors="coerce").dropna()
        if not lon.empty and not lat.empty:
            min_lon = min(min_lon, float(lon.min()))
            max_lon = max(max_lon, float(lon.max()))
            min_lat = min(min_lat, float(lat.min()))
            max_lat = max(max_lat, float(lat.max()))

    lon_span = max(max_lon - min_lon, 0.1)
    lat_span = max(max_lat - min_lat, 0.1)
    lon_pad = lon_span * margin_ratio
    lat_pad = lat_span * margin_ratio
    return (
        max(-180.0, min_lon - lon_pad),
        min(180.0, max_lon + lon_pad),
        max(-90.0, min_lat - lat_pad),
        min(90.0, max_lat + lat_pad),
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
        query: 查询参数（用于确定制图范围）
        output_path: 输出 PNG 路径
        title_zh / title_en: 图标题

    Returns:
        output_path（同一参数）
    """
    _ensure_font()
    pd = _pandas()

    lat0, lon0 = mainshock.latitude, mainshock.longitude
    radius_km = query.max_radius_km
    map_catalog = _catalog_for_map_display(catalog, min_mag=4.0 if map_view == "m4" else None)

    # bbox
    min_lon, max_lon, min_lat, max_lat = _bbox_around(lat0, lon0, radius_km, pad_factor=1.50)
    min_lon, max_lon, min_lat, max_lat = _expand_bbox_for_points(
        (min_lon, max_lon, min_lat, max_lat),
        map_catalog,
    )

    # 画布
    fig = plt.figure(figsize=(8.5, 7.0), constrained_layout=False)
    data_crs = ccrs.PlateCarree()
    map_crs = data_crs
    ax = fig.add_axes([0.08, 0.17, 0.88, 0.69], projection=map_crs)
    ax.set_extent([min_lon, max_lon, min_lat, max_lat], crs=data_crs)

    # ---- 地理底图要素 ----
    ax.set_facecolor(OCEAN_COLOR)
    ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor=OCEAN_COLOR, zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor=LAND_COLOR, edgecolor="none", zorder=1)
    is_china_map = _is_near_china_official_area(lon0, lat0)
    if is_china_map:
        _draw_china_official_boundaries(ax, min_lon, max_lon, min_lat, max_lat, data_crs)
    else:
        ax.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.8, edgecolor="#444", zorder=1)
        ax.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.6, edgecolor="#666", linestyle="--", zorder=1)

    # ---- 断层线（GEM） ----
    try:
        faults = load_faults_in_bbox(
            min_lon, max_lon, min_lat, max_lat, include_attributes=False,
        )
        for f in faults:
            if len(f.points) >= 2:
                xs, ys = zip(*f.points)
                ax.plot(xs, ys, color="#7a3f2b", linewidth=0.9,
                        transform=data_crs, zorder=2, alpha=0.9)
    except Exception as e:
        # 断层加载失败不应阻断出图
        print(f"[fault_loader] WARN: {e}")

    if is_china_map:
        _draw_china_city_labels(ax, min_lon, max_lon, min_lat, max_lat, lon0, lat0, data_crs)
    else:
        _draw_global_city_labels(ax, min_lon, max_lon, min_lat, max_lat, lon0, lat0, data_crs)

    # ---- 历史地震圆点 ----
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
                    linewidths=0.3, transform=data_crs, zorder=4,
                )
                cb = fig.colorbar(sc, ax=ax, shrink=0.64, pad=0.02)
                cb.set_label("事件时间", fontsize=8)
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
                    transform=data_crs, zorder=4,
                    rasterized=dense_small,
                )

    # ---- 主震五角星 ----
    ax.scatter(
        lon0, lat0,
        marker="*", s=600, c="#ffd400", edgecolors="#000",
        linewidths=1.2, transform=data_crs, zorder=10,
    )

    # ---- 经纬度刻度 ----
    gl = ax.gridlines(draw_labels=True, linewidth=0.4, color="#aaa", alpha=0.6,
                      linestyle=":", x_inline=False, y_inline=False)
    gl.top_labels = True
    gl.bottom_labels = False
    gl.right_labels = False
    gl.rotate_labels = False
    gl.xlabel_style = {"size": 9, "color": "#333"}
    gl.ylabel_style = {"size": 9, "color": "#333"}

    # ---- 标题 ----
    if title_zh:
        ax.set_title(
            title_zh,
            fontsize=12, pad=14, fontproperties=_map_font(True),
        )

    # ---- 图例（右下角） ----
    _draw_legend(ax, mainshock, map_view=map_view)
    _draw_map_footer(fig, ax, min_lon, max_lon, min_lat, max_lat)

    # 保存
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fig.savefig(output_path, dpi=dpi, facecolor="white", bbox_inches="tight", pad_inches=0.06, pil_kwargs={"compress_level": 2})
    plt.close(fig)
    return output_path


def _draw_map_footer(fig, ax, min_lon, max_lon, min_lat, max_lat):
    box = ax.get_position()
    # 页脚贴近图框底部，避免与地图主体间距过大
    footer_y = max(0.055, box.y0 - 0.045)
    today = datetime.now().strftime("%Y年%m月%d日")
    scale_x0 = _draw_scale_bar(fig, box, min_lon, max_lon, min_lat, max_lat, footer_y)
    unit_text = fig.text(box.x0, footer_y, f"产出单位：{MAP_OUTPUT_UNIT}",
             ha="left", va="baseline", fontsize=8.5, color="#333",
             fontproperties=_map_font())
    # 实测单位文本宽度，用于避让与折行判断
    unit_right = box.x0 + 0.40
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        inv = fig.transFigure.inverted()
        unit_right = inv.transform(unit_text.get_window_extent(renderer=renderer))[1][0]
    except Exception:
        renderer = inv = None
    # 日期右端：优先避让比例尺；同时不得小于单位右缘 + 间距，防止重叠
    date_x = min(scale_x0, box.x1 - 0.08) - 0.02
    date_x = max(date_x, unit_right + 0.02)
    date_text = fig.text(date_x, footer_y, today,
             ha="right", va="baseline", fontsize=8.5, color="#333",
             fontproperties=_map_font())
    # 小视野下比例尺过宽、右侧空间不足时，日期折行到页脚下一行
    if renderer is not None:
        try:
            date_left = inv.transform(date_text.get_window_extent(renderer=renderer))[0][0]
            if date_left < unit_right + 0.02:
                date_text.set_position((min(scale_x0, box.x1 - 0.08) - 0.02, footer_y - 0.03))
        except Exception:
            pass


def _catalog_for_map_display(catalog: pd.DataFrame, min_mag: float | None = None) -> pd.DataFrame:
    pd = _pandas()
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


def _draw_scale_bar(fig, box, min_lon, max_lon, min_lat, max_lat, footer_y):
    """在底部右侧绘制固定 100 km 括号式比例尺。"""
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat
    lat_ref = min_lat + lat_span / 2
    km_per_deg_lon = 111.32 * max(np.cos(np.radians(lat_ref)), 0.1)
    bar_km = 100
    bar_deg = bar_km / km_per_deg_lon

    bar_width = box.width * (bar_deg / lon_span)
    x1 = box.x1
    x0 = x1 - bar_width
    y_top = footer_y + 0.024
    y_bottom = footer_y + 0.014
    line_color = "#2d241c"
    line_width = 0.85
    for xs, ys in (
        ([x0, x1], [y_top, y_top]),
        ([x0, x0], [y_top, y_bottom]),
        ([x1, x1], [y_top, y_bottom]),
    ):
        line = Line2D(xs, ys, transform=fig.transFigure, color=line_color,
                      linewidth=line_width, solid_capstyle="butt", zorder=92)
        fig.add_artist(line)
    fig.text(
        (x0 + x1) / 2, footer_y, f"{bar_km} km",
        ha="center", va="baseline", fontsize=8.5, color=line_color,
        fontproperties=_map_font(), zorder=92,
    )
    return x0


def _intersects_bbox(a, b) -> bool:
    return not (a[1] < b[0] or a[0] > b[1] or a[3] < b[2] or a[2] > b[3])


def _is_near_china_official_area(lon: float, lat: float) -> bool:
    if not _intersects_bbox((lon, lon, lat, lat), CHINA_BBOX):
        return False
    areas = _china_official_geometries()
    if not areas:
        return False
    try:
        from shapely.geometry import Point

        point = Point(lon, lat)
        return any(area.covers(point) or area.distance(point) <= 0.6 for area in areas)
    except Exception:
        return False


@lru_cache(maxsize=1)
def _china_official_geometries():
    if not TIANDITU_CHINA_GEOJSON.exists():
        return tuple()
    try:
        from shapely.geometry import shape
        return tuple(
            shape(feature["geometry"])
            for feature in _load_tianditu_china_geojson().get("features", [])
            if feature.get("geometry")
        )
    except Exception:
        return tuple()


def _china_boundary_files() -> list[Path]:
    env_path = os.environ.get("QUAKE_CHINA_BOUNDARY_SHP")
    if env_path:
        return [Path(env_path)]
    return sorted(CHINA_BOUNDARY_DIR.rglob("BOUL*.shp"))


def _draw_china_official_boundaries(ax, min_lon, max_lon, min_lat, max_lat, proj):
    target_bbox = (min_lon, max_lon, min_lat, max_lat)
    if not _intersects_bbox(target_bbox, CHINA_BBOX):
        return
    official_geometries = _china_official_geometries()
    if official_geometries:
        try:
            from shapely.geometry import box

            viewport = box(min_lon, min_lat, max_lon, max_lat)
            if not any(geometry.intersects(viewport) for geometry in official_geometries):
                return
        except Exception:
            pass

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
    reader_bbox = (min_lon, min_lat, max_lon, max_lat)
    for shp_path in shp_files:
        reader = shapefile.Reader(str(shp_path), encoding="gbk", encodingErrors="replace")
        source_bbox = (reader.bbox[0], reader.bbox[2], reader.bbox[1], reader.bbox[3])
        if not _intersects_bbox(source_bbox, target_bbox):
            reader.close()
            continue
        fields = [f[0] for f in reader.fields[1:]]
        for shape_record in reader.iterShapeRecords(bbox=reader_bbox):
            shape, record = shape_record.shape, shape_record.record
            if not _intersects_bbox((shape.bbox[0], shape.bbox[2], shape.bbox[1], shape.bbox[3]),
                                    target_bbox):
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
        return "#555d59", 0.85, 0.84
    if code.startswith("64"):
        return "#737a76", 0.65, 0.72
    if code.startswith("65"):
        return "#a4aaa6", 0.30, 0.52
    return "#8c928e", 0.40, 0.60


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
            ax.plot(xs, ys, color="#747b77", linewidth=0.50, alpha=0.68,
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
        ax.plot(xs, ys, color="#555d59", linewidth=0.85, alpha=0.84,
                linestyle="-", transform=proj, zorder=1.8)


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
    max_labels = 10 if (max_lon - min_lon) > 8 else 14
    cities.sort(key=lambda c: (float(c["lng"]) - lon0) ** 2 + (float(c["lat"]) - lat0) ** 2)
    drawn_names = set()
    for city in cities[:max_labels]:
        lon, lat = float(city["lng"]), float(city["lat"])
        name = _short_city_name(str(city.get("name", "")))
        drawn_names.add(name)
        _draw_city_label(ax, lon, lat, name, proj)
    if len(drawn_names) < 4:
        _draw_tianditu_region_labels(ax, min_lon, max_lon, min_lat, max_lat, drawn_names, proj)


def _draw_tianditu_region_labels(ax, min_lon, max_lon, min_lat, max_lat, used_names: set[str], proj):
    try:
        from shapely.geometry import box, shape
    except Exception:
        return
    labels = []
    viewport = box(min_lon, min_lat, max_lon, max_lat)
    for feature in _load_tianditu_china_geojson().get("features", []):
        props = feature.get("properties") or {}
        name = _short_region_name(str(props.get("name", "")))
        if not name or name in used_names:
            continue
        geom = feature.get("geometry") or {}
        try:
            visible = shape(geom).intersection(viewport)
        except Exception:
            continue
        if visible.is_empty or visible.area <= 0.02:
            continue
        point = visible.representative_point()
        labels.append((visible.area, float(point.x), float(point.y), name))
    labels.sort(reverse=True)
    for _, lon, lat, name in labels[:4]:
        _draw_region_label(ax, lon, lat, name, proj)


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
    ax.scatter(lon, lat, s=12, marker="o", c="white", edgecolors="#555d59",
               linewidths=0.45, transform=proj, zorder=6)
    ax.text(
        lon, lat, f" {name}", fontsize=7.2, color="#222222",
        ha="left", va="bottom", transform=proj, zorder=6.5,
        fontproperties=_map_font(),
        path_effects=[path_effects.withStroke(linewidth=2.2, foreground="white", alpha=0.9)],
    )


def _draw_region_label(ax, lon: float, lat: float, name: str, proj):
    ax.text(
        lon, lat, name, fontsize=8.5, color="#555555",
        ha="center", va="center", transform=proj, zorder=5.5,
        fontproperties=_map_font(True),
        path_effects=[path_effects.withStroke(linewidth=2.6, foreground="white", alpha=0.85)],
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


def _short_region_name(name: str) -> str:
    replacements = {
        "内蒙古自治区": "内蒙古",
        "新疆维吾尔自治区": "新疆",
        "西藏自治区": "西藏",
        "广西壮族自治区": "广西",
        "宁夏回族自治区": "宁夏",
    }
    if name in replacements:
        return replacements[name]
    for suffix in ("省", "市", "特别行政区"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
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


def _draw_legend(ax, mainshock: MainShock, map_view: str = "mag"):
    """右下角图例框。"""
    # 图例条目
    legend_items = []
    # 主震
    legend_items.append(Line2D([0], [0], marker="*", color="w",
                               markerfacecolor="#ffd400", markeredgecolor="black",
                               markersize=14, markeredgewidth=1.0,
                               linestyle="None", label="震中"))
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
                               linestyle="-", label="断层"))
    leg = ax.legend(
        handles=legend_items,
        loc="lower right",
        fontsize=8.2,
        title="图例",
        title_fontsize=9,
        prop=_map_font(),
        frameon=True,
        fancybox=True,
        facecolor="white",
        edgecolor="#666",
        framealpha=0.82,
        borderpad=0.55,
        labelspacing=0.32,
        handletextpad=0.55,
        borderaxespad=0.45,
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
    pd = _pandas()
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
