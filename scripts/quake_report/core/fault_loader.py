"""
GEM 全球活动断层加载器。

数据源：https://github.com/GEMScienceTools/gem-global-active-faults
本地缓存：项目根目录/data/gem_faults/gem_active_faults_harmonized.{shp,shx,dbf}

提供按经纬度边界框裁剪的功能，返回用于绘图的 LineString 列表。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

import shapefile

# GEM shapefile 的 dbf 用 latin-1 编码存放一些非 ASCII 字符（如法语、西班牙语人名），
# pyshp 默认 utf-8 解码会失败 —— 切到 latin-1 兜底（不会丢字符，只会让非 ASCII 显示成乱码，但 name 字段我们也不展示在图上）
import shapefile as _sf
_orig_init = _sf.Reader.__init__
def _patched_init(self, *args, **kwargs):
    kwargs.setdefault("encoding", "latin-1")
    kwargs.setdefault("encodingErrors", "replace")
    return _orig_init(self, *args, **kwargs)
_sf.Reader.__init__ = _patched_init

# 默认 shapefile 路径
DEFAULT_SHP = str(Path(__file__).resolve().parents[3] / "data/gem_faults/gem_active_faults_harmonized.shp")


@dataclass
class FaultSegment:
    """一条断层段。"""

    name: str
    slip_type: str
    points: List[Tuple[float, float]]  # [(lon, lat), ...]


def load_faults_in_bbox(
    min_lon: float,
    max_lon: float,
    min_lat: float,
    max_lat: float,
    shp_path: str = DEFAULT_SHP,
) -> List[FaultSegment]:
    """加载 bbox 范围内的断层段。

    bbox 不跨越国际日期变更线（±180°）—— 若需要可分两次调用再合并。
    """
    if not os.path.exists(shp_path):
        return []

    records = _load_fault_records(shp_path, os.path.getmtime(shp_path))
    segments: List[FaultSegment] = []

    for sb, pts, name, slip in records:
        # 快速 bbox 过滤
        if sb[2] < min_lon or sb[0] > max_lon:
            continue
        if sb[3] < min_lat or sb[1] > max_lat:
            continue

        # 细粒度点过滤：保留落在 bbox 内的点，跨 bbox 的段做裁剪
        kept = [
            (lon, lat)
            for lon, lat in pts
            if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
        ]
        if len(kept) < 2:
            # 至少要 2 个点才能画线
            # 但若原线段穿过 bbox 边缘，单点会丢；这里简化处理：跳过
            continue

        segments.append(FaultSegment(name=name, slip_type=slip, points=kept))

    return segments


@lru_cache(maxsize=4)
def _load_fault_records(shp_path: str, mtime: float):
    sf = shapefile.Reader(shp_path)
    rows = []
    for shape, record in zip(sf.shapes(), sf.records()):
        pts = shape.points
        if not pts:
            continue
        try:
            name = record["name"] or ""
            slip = record["slip_type"] or ""
        except (IndexError, KeyError):
            name, slip = "", ""
        rows.append((tuple(shape.bbox), tuple(pts), name, slip))
    sf.close()
    return tuple(rows)


def fault_color(slip_type: str) -> str:
    """根据 slip_type 返回颜色（参考模板：黑色断层线）。"""
    # GEM slip_type 常见值：'Sinistral' / 'Dextral' / 'Normal' / 'Reverse' / 'Sinistral-Normal' ...
    # 模板里是黑色统一画，这里也保持黑色
    return "#333333"
