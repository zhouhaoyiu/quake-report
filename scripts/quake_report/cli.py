#!/usr/bin/env python3
"""
USGS 地震一键自动产出图件与报告 —— 命令行入口。

四种震中输入模式：
  (1) 手动输入参数：  --mode manual --lat 41.5 --lon 142.5 --mag 7.0 --time "2026-06-25T14:17:00Z"
  (2) 按 eventid 查： --mode eventid --event-id us7000xxxx
  (3) 拉取最新大震：  --mode recent  （列出近 30 天 M≥6.0 列表，取最大事件）
  (4) 批量 CSV：      --mode batch --csv events.csv

输出：
  - {slug}_map.png      震中周边历史地震分布图
  - {slug}.docx         完整报告（含封面+目录+正文+图+扩展章节）
  - {slug}.pdf          docx 转 PDF

示例：
  python quake_report.py --mode manual --lat 10.21 --lon -68.18 --mag 7.1 \
      --time "2026-06-25T00:31:00Z" --place "Venezuela" --slug venezuela
  python quake_report.py --mode eventid --event-id us7000ndeb
  python quake_report.py --mode recent
  python quake_report.py --mode batch --csv events.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 把 scripts/ 加入 sys.path 以便 import quake_report.core.*
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from quake_report.core.usgs_client import (
    MainShock, CatalogQuery, fetch_historical_catalog, compute_stats,
    fetch_mainshock_by_id, fetch_recent_large_events,
    mainshock_from_manual, mainshock_from_csv_row,
    exclude_mainshock_like,
)
from quake_report.core.formatting import format_km
from quake_report.core.mainshock_helpers import apply_place_override
from quake_report.core.catalog_export import write_catalog_csv
from quake_report.core.map_renderer import render_distribution_map
from quake_report.core.docx_builder import build_report, convert_docx_to_pdf
from quake_report.core.supplemental_sources import collect_supplemental_data


DOWNLOAD_DIR = str(PROJECT_ROOT / "download")


# ============================================================================
# 主流程
# ============================================================================

def generate_one(
    mainshock: MainShock,
    *,
    radius_km: float = 200.0,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    min_magnitude: float = 3.0,
    fig_num: str = "1",
    slug: str | None = None,
    title_zh: str | None = None,
    title_en: str | None = None,
    source_text: str | None = None,
    output_dir: str = DOWNLOAD_DIR,
    also_pdf: bool = True,
    report_level: str = "simple",
    tz: str = "utc",
    map_view: str = "mag",
) -> dict:
    """针对单个主震执行完整流程：查询目录 → 渲染图 → 生成 docx → 转 pdf。"""
    print(f"\n{'='*70}")
    print(f"主震 Mainshock: {mainshock}")
    print(f"  event_id  = {mainshock.event_id}")
    print(f"  epicenter = ({mainshock.latitude}, {mainshock.longitude})")
    print(f"  magnitude = {mainshock.mag_type} {mainshock.magnitude}")
    print(f"  time_utc  = {mainshock.time_str}")
    print(f"  time_bj   = {mainshock.time_bj_str}")
    print(f"  tz_mode   = {tz}")
    print(f"  place     = {mainshock.place}")
    print(f"{'='*70}")

    # 1) slug
    if slug is None:
        slug = _default_slug(mainshock, tz)

    os.makedirs(output_dir, exist_ok=True)

    # 2) 查询历史目录。默认只统计主震前事件，避免把余震写成历史背景。
    catalog_end_time = end_time
    if catalog_end_time is None:
        catalog_end_time = mainshock.time_utc - timedelta(seconds=1)

    query = CatalogQuery(
        latitude=mainshock.latitude, longitude=mainshock.longitude,
        max_radius_km=radius_km, start_time=start_time, end_time=catalog_end_time,
        min_magnitude=min_magnitude,
    )
    print(f"\n[1/5] 查询 USGS 历史目录（半径 {format_km(radius_km)} km，M≥{min_magnitude}）...")
    catalog = fetch_historical_catalog(query, exclude_event_id=mainshock.event_id)
    catalog, removed_mainshock = exclude_mainshock_like(catalog, mainshock)
    warnings = []
    if catalog.attrs.get("catalog_stale"):
        coverage = catalog.attrs.get("catalog_coverage_end", "未知时间")
        warnings.append(f"离线 USGS 目录截至 {coverage}，该时刻之后的事件未纳入统计。")
    print(f"  → 命中 {len(catalog)} 条事件")
    if removed_mainshock:
        print(f"  → 已从历史目录中剔除疑似主震记录 {removed_mainshock} 条")

    # 3) 统计
    stats = compute_stats(catalog, query)
    print(f"  → 统计：N3={stats.n3} N4={stats.n4} N5={stats.n5} "
          f"N6={stats.n6} N7={stats.n7} N8={stats.n8}")
    if stats.mc_estimate is not None:
        print(f"  → 目录完整性震级 Mc≈{stats.mc_estimate:.1f}（{stats.mc_method}）")
    if stats.query_limit_hit:
        warnings.append(
            f"USGS 返回记录达到 {stats.query_limit} 条查询上限，统计可能低于真实目录量；建议提高最小震级或缩小半径后复核。"
        )
    print(f"  → 统计口径：自 {(query.start_time or datetime(1900, 1, 1)).year} 年以来")

    catalog_path = os.path.join(output_dir, f"{slug}_catalog.csv")
    write_catalog_csv(catalog, catalog_path)
    print(f"  → 统计目录 CSV：{catalog_path}")

    # 4) 渲染地图
    map_path = os.path.join(output_dir, f"{slug}_map.png")
    report_title_zh = title_zh or _default_title_zh(mainshock, tz)
    map_title_zh = title_zh or _default_map_title_zh(mainshock, tz)
    if title_en is None:
        title_en = _default_title_en(mainshock)
    print(f"\n[2/5] 渲染震中分布图 → {map_path}")
    render_distribution_map(
        mainshock, catalog, query,
        output_path=map_path,
        title_zh=map_title_zh,
        title_en=title_en,
        map_view=map_view,
    )
    print(f"MAP_READY:{map_path}")

    # 5) 辅助数据层
    supplemental = None
    if report_level == "simple":
        print("\n[3/5] 简报模式无需辅助目录，跳过 EMSC 查询。")
    else:
        print("\n[3/5] 拉取辅助数据层（EMSC 目录 + GEM 断层摘要）...")
        supplemental = collect_supplemental_data(mainshock, query)
        if supplemental.emsc_error:
            print(f"  → EMSC 辅助目录不可用：{supplemental.emsc_error}")
        else:
            suffix = "（达到查询上限，可能未完整）" if supplemental.emsc_limited else ""
            print(f"  → EMSC 辅助目录返回 {len(supplemental.emsc_catalog)} 条事件{suffix}")
        if supplemental.nearest_fault_distance_km is None:
            print(f"  → GEM 断层：半径附近加载 {supplemental.fault_count} 条，未计算到最近距离")
        else:
            print(
                f"  → GEM 断层：半径附近加载 {supplemental.fault_count} 条，"
                f"最近约 {supplemental.nearest_fault_distance_km:.1f} km"
            )

    # 6) 生成 docx
    docx_path = os.path.join(output_dir, f"{slug}.docx")
    print(f"\n[4/5] 生成 docx 报告 → {docx_path}")
    build_report(
        mainshock, stats, catalog, map_path, docx_path,
        fig_num=fig_num, title_zh=report_title_zh, title_en=title_en,
        radius_km=radius_km, report_level=report_level,
        tz=tz, supplemental=supplemental, removed_mainshock_count=removed_mainshock,
        catalog_warnings=warnings, source_text=source_text,
    )

    # 7) 转 PDF
    pdf_path = None
    if also_pdf:
        print(f"\n[5/5] 转换 PDF ...")
        try:
            pdf_path = convert_docx_to_pdf(docx_path)
            print(f"  → {pdf_path}")
        except Exception as e:
            print(f"  ⚠ PDF 转换失败：{e}")
            pdf_path = None

    return {
        "mainshock": mainshock,
        "stats": stats,
        "map_path": map_path,
        "catalog_path": catalog_path,
        "docx_path": docx_path,
        "pdf_path": pdf_path,
        "warnings": warnings,
        "map_meta": _map_meta(catalog, map_view),
    }


# ============================================================================
# 默认 slug / title
# ============================================================================

def _default_slug(mainshock: MainShock, tz: str = "utc") -> str:
    t = _title_date(mainshock, tz)
    place = (mainshock.place or "震中区").split(",")[0].strip()
    place = "".join(c for c in place if c not in '\\/:*?"<>|').strip()[:32] or "震中区"
    return f"{t.year}年{t.month}月{t.day}日{place}M{mainshock.magnitude:.1f}地震震中区历史地震简报"


def _title_date(mainshock: MainShock, tz: str) -> datetime:
    return mainshock.time_utc + timedelta(hours=8) if tz in ("utc8", "cn", "both") else mainshock.time_utc


def _default_title_zh(mainshock: MainShock, tz: str = "utc") -> str:
    t = _title_date(mainshock, tz)
    place = (mainshock.place or "").split(",")[0].strip()[:24]
    name = f"{place} " if place and place.isascii() else place
    return f"{t.year}年{t.month}月{t.day}日{name}M{mainshock.magnitude:.1f}地震 震中区历史地震活动分析"


def _default_map_title_zh(mainshock: MainShock, tz: str = "utc") -> str:
    t = _title_date(mainshock, tz)
    place = (mainshock.place or "").split(",")[0].strip()[:24]
    name = f"{place} " if place and place.isascii() else place
    return f"{t.year}年{t.month}月{t.day}日{name}M{mainshock.magnitude:.1f}地震 震中区历史地震分布图"


def _default_title_en(mainshock: MainShock) -> str:
    place = (mainshock.place or "").split(",")[0].strip()
    name = f"{place} " if place else ""
    return f"Seismicity around the {mainshock.time_utc:%Y-%m} {name}M{mainshock.magnitude:.1f} Earthquake"


def _map_meta(catalog, map_view: str) -> dict:
    if catalog is None or catalog.empty:
        return {"view": map_view, "display_count": 0, "total_count": 0}
    df = catalog.dropna(subset=["longitude", "latitude", "mag"])
    total = int(len(df))
    if map_view == "m4":
        display = int((df["mag"].astype(float) >= 4.0).sum())
    else:
        display = total
    return {"view": map_view, "display_count": display, "total_count": total}


# ============================================================================
# 四种输入模式
# ============================================================================

def _parse_time(s: str) -> datetime:
    """支持 ISO8601 with/without Z."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)


def resolve_mainshock_manual(args) -> MainShock:
    return mainshock_from_manual(
        latitude=args.lat, longitude=args.lon,
        magnitude=args.mag, time_utc=_parse_time(args.time),
        depth_km=args.depth, place=args.place or "",
        mag_type=args.mag_type, event_id=args.event_id or "manual",
    )


def resolve_mainshock_eventid(args) -> MainShock:
    print(f"查询 USGS eventid={args.event_id} ...")
    return fetch_mainshock_by_id(args.event_id)


def resolve_mainshock_recent(args) -> MainShock:
    print(f"拉取近 {args.recent_days} 天 M≥{args.recent_min_mag} 地震列表 ...")
    df = fetch_recent_large_events(days=args.recent_days,
                                   min_magnitude=args.recent_min_mag,
                                   limit=30)
    if df.empty:
        raise RuntimeError("USGS 近期无符合条件的地震事件")
    # 默认取最大震级
    idx = df["mag"].idxmax()
    row = df.loc[idx]
    print(f"\n找到 {len(df)} 个候选事件，自动选取最大事件：")
    print(f"  time: {row['time']}, mag: {row['mag']}, "
          f"place: {row.get('place', '')}")
    print(f"  event_id: {row['id']}")
    print(f"\n候选事件列表（按时间倒序）：")
    for _, r in df.head(10).iterrows():
        print(f"  {r['time']}  M{r['mag']:.1f}  {r.get('place', '')}  [{r['id']}]")
    return mainshock_from_manual(
        latitude=row["latitude"], longitude=row["longitude"],
        magnitude=row["mag"], time_utc=_parse_time(row["time"]),
        depth_km=row["depth"], place=row.get("place", ""),
        mag_type=str(row.get("magType", "Mw")).upper(),
        event_id=row["id"],
    )


def resolve_mainshocks_batch(args) -> list[MainShock]:
    """从 CSV 读取多行主震。"""
    shocks = []
    with open(args.csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            try:
                shocks.append(mainshock_from_csv_row(row))
            except Exception as e:
                print(f"  ⚠ 第 {i} 行解析失败：{e} —— 跳过")
    if not shocks:
        raise RuntimeError(f"CSV 文件 {args.csv} 中无有效主震记录")
    print(f"从 CSV 读取 {len(shocks)} 个主震事件")
    return shocks


# ============================================================================
# argparse
# ============================================================================

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quake_report",
        description="USGS 地震一键自动产出图件与报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # 模式
    p.add_argument("--mode", choices=["manual", "eventid", "recent", "batch"],
                   default="manual",
                   help="震中信息来源模式（默认 manual）")

    # manual 模式
    p.add_argument("--lat", type=float, help="震中纬度（manual 模式必填）")
    p.add_argument("--lon", type=float, help="震中经度（manual 模式必填）")
    p.add_argument("--mag", type=float, help="震级（manual 模式必填）")
    p.add_argument("--time", type=str,
                   help="发震时间 UTC，ISO8601 格式如 '2026-06-25T14:17:00Z'（manual 模式必填）")
    p.add_argument("--depth", type=float, default=10.0,
                   help="震源深度 km（默认 10.0）")
    p.add_argument("--place", type=str, default="",
                   help="震中地名（可选）")
    p.add_argument("--mag-type", type=str, default="M",
                   help="震级类型（默认 M）")

    # eventid 模式
    p.add_argument("--event-id", type=str, help="USGS eventid（eventid 模式必填）")

    # recent 模式
    p.add_argument("--recent-days", type=int, default=30,
                   help="拉取近 N 天事件（recent 模式，默认 30）")
    p.add_argument("--recent-min-mag", type=float, default=6.0,
                   help="拉取事件的最小震级（recent 模式，默认 6.0）")

    # batch 模式
    p.add_argument("--csv", type=str, help="批量 CSV 文件路径（batch 模式必填）")

    # 通用查询参数
    p.add_argument("--radius-km", type=float, default=200.0,
                   help="历史地震查询半径 km（默认 200）")
    p.add_argument("--start-time", type=str, default=None,
                   help="起始时间 ISO8601（默认 1900-01-01）")
    p.add_argument("--end-time", type=str, default=None,
                   help="结束时间 ISO8601（默认主震前 1 秒，避免把余震计入历史背景）")
    p.add_argument("--min-mag", type=float, default=3.0,
                   help="最小震级（默认 3.0）")

    # 输出参数
    p.add_argument("--slug", type=str, default=None,
                   help="输出文件名（不含扩展名，默认自动生成）")
    p.add_argument("--fig-num", type=str, default="1",
                   help="图编号字符串（默认 '1'）")
    p.add_argument("--title-zh", type=str, default=None, help="报告中文标题")
    p.add_argument("--title-en", type=str, default=None, help="报告英文标题")
    p.add_argument("--source-text", type=str, default=None, help="原始速报/短信文本，simple 报告首段会原文引用")
    p.add_argument("--output-dir", type=str, default=DOWNLOAD_DIR,
                   help=f"输出目录（默认 {DOWNLOAD_DIR}）")
    p.add_argument("--no-pdf", action="store_true",
                   help="不生成 PDF（默认会生成）")
    p.add_argument("--report-level", type=str, default="simple",
                   choices=["simple", "medium", "full"],
                   help="报告复杂度：simple 最简模板（默认）| medium 原简版 | full 完整扩展")
    p.add_argument("--no-extended", action="store_true",
                   help="兼容旧参数：等同 --report-level medium")
    p.add_argument("--tz", type=str, default="utc",
                   choices=["utc", "utc8", "cn", "both"],
                   help="时区显示模式：utc（默认）| utc8/cn（北京时间）| both（同时显示 UTC 和北京时间）")
    p.add_argument("--map-view", type=str, default="mag",
                   choices=["mag", "m4", "time"],
                   help="地图点显示：mag 全量按震级 | m4 仅显示 M≥4 | time 按时间着色")
    p.add_argument("--json-summary", type=str, default=None,
                   help="把生成结果摘要写入 JSON 文件")

    return p


def main(argv=None):
    args = build_argparser().parse_args(argv)

    # 解析时间参数
    start_time = _parse_time(args.start_time) if args.start_time else None
    end_time = _parse_time(args.end_time) if args.end_time else None

    # 解析主震
    if args.mode == "manual":
        if not all([args.lat is not None, args.lon is not None,
                    args.mag is not None, args.time]):
            print("ERROR: manual 模式需要 --lat --lon --mag --time 四个参数", file=sys.stderr)
            return 1
        shocks = [resolve_mainshock_manual(args)]
    elif args.mode == "eventid":
        if not args.event_id:
            print("ERROR: eventid 模式需要 --event-id 参数", file=sys.stderr)
            return 1
        shocks = [resolve_mainshock_eventid(args)]
    elif args.mode == "recent":
        shocks = [resolve_mainshock_recent(args)]
    elif args.mode == "batch":
        if not args.csv:
            print("ERROR: batch 模式需要 --csv 参数", file=sys.stderr)
            return 1
        shocks = resolve_mainshocks_batch(args)
    else:
        print(f"ERROR: 未知模式 {args.mode}", file=sys.stderr)
        return 1
    shocks = apply_place_override(shocks, args.place)

    # 逐个生成
    all_results = []
    for i, ms in enumerate(shocks, 1):
        if len(shocks) > 1:
            print(f"\n\n>>> 处理第 {i}/{len(shocks)} 个事件 <<<")
        slug = args.slug
        if len(shocks) > 1 and slug:
            slug = f"{slug}_{i:03d}"
        report_level = "medium" if args.no_extended else args.report_level
        result = generate_one(
            ms,
            radius_km=args.radius_km,
            start_time=start_time,
            end_time=end_time,
            min_magnitude=args.min_mag,
            fig_num=args.fig_num,
            slug=slug,
            title_zh=args.title_zh,
            title_en=args.title_en,
            source_text=args.source_text,
            output_dir=args.output_dir,
            also_pdf=not args.no_pdf,
            report_level=report_level,
            tz=args.tz,
            map_view=args.map_view,
        )
        all_results.append(result)

    # JSON 摘要
    if args.json_summary:
        summary = []
        for r in all_results:
            summary.append({
                "event_id": r["mainshock"].event_id,
                "latitude": r["mainshock"].latitude,
                "longitude": r["mainshock"].longitude,
                "depth_km": r["mainshock"].depth_km,
                "magnitude": r["mainshock"].magnitude,
                "mag_type": r["mainshock"].mag_type,
                "time_utc": r["mainshock"].time_utc.isoformat(),
                "place": r["mainshock"].place,
                "stats": {
                    "n3": r["stats"].n3, "n4": r["stats"].n4,
                    "n5": r["stats"].n5, "n6": r["stats"].n6,
                    "n7": r["stats"].n7, "n8": r["stats"].n8,
                    "use_since_1950": r["stats"].use_since_1950,
                    "total_count": r["stats"].total_count,
                    "mc_estimate": r["stats"].mc_estimate,
                    "mc_method": r["stats"].mc_method,
                    "query_limit_hit": r["stats"].query_limit_hit,
                    "query_limit": r["stats"].query_limit,
                },
                "mapMeta": r.get("map_meta", {}),
                "warnings": r.get("warnings", []),
                "files": {
                    "map": r["map_path"],
                    "catalog": r["catalog_path"],
                    "docx": r["docx_path"],
                    "pdf": r["pdf_path"],
                },
            })
        with open(args.json_summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\n摘要已写入 {args.json_summary}")

    print(f"\n{'='*70}")
    print(f"✅ 完成 {len(all_results)} 份报告")
    for r in all_results:
        print(f"  - {r['docx_path']}")
        if r["pdf_path"]:
            print(f"    PDF: {r['pdf_path']}")
    print(f"{'='*70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
