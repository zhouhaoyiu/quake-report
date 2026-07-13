"""地震活动分析报告 DOCX 生成器。"""
from __future__ import annotations

import os
import signal
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Twips, RGBColor, Emu

from .usgs_client import MainShock, CatalogStats, normalize_mag_type
from .formatting import format_km
from .narrative_builder import (
    build_narrative_zh,
    build_mainshock_summary_zh_v2,
)
from .supplemental_sources import SupplementalData
from .map_renderer import nearest_city_rows


# ============================================================================
# 字体 & 样式常量
# ============================================================================

# DOCX 字体名固定写入，避免本地/服务器因已安装字体不同而生成不同格式。
FANGSONG_FONT_NAMES = [
    "SimSun", "Songti SC", "Noto Serif CJK SC", "Noto Sans CJK SC", "Noto Sans SC",
    "STHeiti", "Heiti SC", "仿宋_GB2312", "FangSong_GB2312", "仿宋", "FangSong", "STFangsong",
]
HEITI_FONT_NAMES = [
    "SimSun", "Songti SC", "Noto Serif CJK SC", "Noto Sans CJK SC", "Noto Sans SC",
]
REPORT_BLUE = RGBColor(0x1F, 0x4E, 0x79)
MUTED_GRAY = RGBColor(0x66, 0x66, 0x66)
LIGHT_BLUE = "EAF2F8"
LIGHT_GRAY = "F3F5F7"
REPORT_MAP_WIDTH_CM = 14.2

_CHART_FONT = None


@lru_cache(maxsize=1)
def _available_docx_fonts() -> set[str]:
    known_font_paths = {
        "Noto Sans CJK SC": [
            str(Path.home() / "Library/Fonts/NotoSansCJKsc-Regular.otf"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto/NotoSansCJK-Regular.ttc",
        ],
        "Noto Sans SC": [
            str(Path.home() / "Library/Fonts/NotoSansSC-Regular.otf"),
        ],
        "STHeiti": [
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
        ],
        "Songti SC": [
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ],
        "SimSun": [
            str(Path.home() / "Library/Fonts/simsun.ttc"),
        ],
        "SimHei": [
            str(Path.home() / "Library/Fonts/simhei.ttf"),
        ],
    }
    available = {f.name for f in fm.fontManager.ttflist}
    for family, paths in known_font_paths.items():
        for path in paths:
            if os.path.exists(path):
                try:
                    fm.fontManager.addfont(path)
                except Exception:
                    pass
                available.add(family)
                break
    return available


def _resolve_docx_font(font_names) -> str:
    return font_names[0]


def _chart_font():
    global _CHART_FONT
    if _CHART_FONT is not None:
        return _CHART_FONT
    for path in [
        str(Path.home() / "Library/Fonts/simsun.ttc"),
        "/usr/local/share/fonts/quake-report/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        str(Path.home() / "Library/Fonts/NotoSansCJKsc-Regular.otf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]:
        if os.path.exists(path):
            fm.fontManager.addfont(path)
            _CHART_FONT = fm.FontProperties(fname=path)
            return _CHART_FONT
    _CHART_FONT = fm.FontProperties(family="DejaVu Sans")
    return _CHART_FONT


def _set_run_font(run, font_names, size_pt=None, bold=False, color=None):
    """设置 run 的中英文字体（eastAsia 与 ascii 分别设）。"""
    rpr = run._element.get_or_add_rPr()
    # 字体
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    primary = _resolve_docx_font(tuple(font_names))
    run.font.name = primary
    rfonts.set(qn("w:ascii"), "Times New Roman")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")
    rfonts.set(qn("w:cs"), "Times New Roman")
    rfonts.set(qn("w:eastAsia"), primary)

    # 字号
    if size_pt is not None:
        run.font.size = Pt(size_pt)

    if bold:
        run.bold = True

    if color:
        run.font.color.rgb = color


def _set_paragraph_first_line_indent_chars(paragraph, chars=2):
    """设置首行缩进 N 个字符（用 firstLineChars 属性，匹配 WPS 习惯）。"""
    pPr = paragraph._element.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    # firstLineChars 单位：百分之一字符
    ind.set(qn("w:firstLineChars"), str(chars * 100))
    # 同步设 firstLine（twips），14pt 字号下 2 字符约 560 twips
    ind.set(qn("w:firstLine"), str(chars * 280))


def _set_paragraph_line_spacing_exact(paragraph, pt: float):
    """设置固定行距（pt）。"""
    pPr = paragraph._element.get_or_add_pPr()
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    # line 单位：twips（1/20 pt）
    spacing.set(qn("w:line"), str(int(pt * 20)))
    spacing.set(qn("w:lineRule"), "exact")


def _set_table_no_borders(table):
    """让表格无边框（用于封面布局）。"""
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "none")
        b.set(qn("w:sz"), "0")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "auto")
        borders.append(b)
    tblPr.append(borders)


def _set_auto_spacing(paragraph, *, before=0, after=6, line=1.18):
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = line


def _set_cell_shading(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_cell_margins(cell, top=80, bottom=80, start=120, end=120):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in {"top": top, "bottom": bottom, "start": start, "end": end}.items():
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_table_width(table, width_twips: int = 9360):
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(width_twips))
    tbl_w.set(qn("w:type"), "dxa")
    table.allow_autofit = False


def _set_table_borders(table, color: str = "D6DDE6", size: str = "6"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def _repeat_table_header(table):
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:tblHeader")) is None:
        tr_pr.append(OxmlElement("w:tblHeader"))


def _keep_row_together(row):
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def _write_cell(cell, text, *, bold=False, size=9.5, align=WD_ALIGN_PARAGRAPH.LEFT, fill=None, color=None):
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    _set_cell_margins(cell)
    if fill:
        _set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    p.alignment = align
    _set_auto_spacing(p, before=0, after=0, line=1.08)
    p.text = ""
    run = p.add_run(str(text))
    _set_run_font(run, HEITI_FONT_NAMES if bold else FANGSONG_FONT_NAMES, size_pt=size, bold=bold, color=color)


def _add_report_heading(doc, text: str, level: int = 1):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.keep_with_next = True
    _set_auto_spacing(p, before=8 if level == 1 else 6, after=4, line=1.0)
    p_pr = p._element.get_or_add_pPr()
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), str(level - 1))
    p_pr.append(outline)
    run = p.add_run(text)
    _set_run_font(
        run,
        HEITI_FONT_NAMES,
        size_pt={1: 14, 2: 14, 3: 14}.get(level, 14),
        bold=True,
        color=REPORT_BLUE if level <= 2 else RGBColor(0x33, 0x33, 0x33),
    )
    return p


def _add_report_paragraph(doc, text: str, *, size=14, bold=False, color=None, line=1.0):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _set_auto_spacing(p, before=0, after=5, line=line)
    _set_paragraph_first_line_indent_chars(p, 2)
    run = p.add_run(text)
    _set_run_font(run, FANGSONG_FONT_NAMES, size_pt=size, bold=bold, color=color)
    return p


def _add_key_points_box(doc, points):
    table = doc.add_table(rows=len(points), cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_width(table)
    _set_table_borders(table, color="E1E7EE", size="4")
    for i, (label, text) in enumerate(points):
        cell = table.cell(i, 0)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_cell_margins(cell, top=90, bottom=90, start=140, end=140)
        _set_cell_shading(cell, "F7F9FB" if i == 0 else "FFFFFF")
        p = cell.paragraphs[0]
        p.text = ""
        _set_auto_spacing(p, before=0, after=0, line=1.12)
        label_run = p.add_run(f"{label}：")
        _set_run_font(label_run, HEITI_FONT_NAMES, size_pt=9.8, bold=True, color=REPORT_BLUE)
        text_run = p.add_run(text)
        _set_run_font(text_run, FANGSONG_FONT_NAMES, size_pt=9.8)
    p = doc.add_paragraph()
    _set_auto_spacing(p, before=2, after=4, line=1.0)
    return table


def _add_table(doc, headers, rows, *, widths_cm=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    _set_table_width(table)
    _set_table_borders(table)
    for i, header in enumerate(headers):
        _write_cell(table.rows[0].cells[i], header, bold=True, size=9.2, align=WD_ALIGN_PARAGRAPH.CENTER, fill=LIGHT_BLUE)
    _repeat_table_header(table)
    _keep_row_together(table.rows[0])
    for row in rows:
        row_obj = table.add_row()
        _keep_row_together(row_obj)
        cells = row_obj.cells
        for i, value in enumerate(row):
            align = WD_ALIGN_PARAGRAPH.CENTER if i == 0 or isinstance(value, (int, float)) else WD_ALIGN_PARAGRAPH.LEFT
            _write_cell(cells[i], value, size=9.0, align=align)
    if widths_cm:
        for row in table.rows:
            for i, width in enumerate(widths_cm):
                row.cells[i].width = Cm(width)
    p = doc.add_paragraph()
    _set_auto_spacing(p, before=2, after=4, line=1.0)
    return table


def _fmt_catalog_time(value, tz: str = "utc8") -> str:
    dt = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(dt):
        return str(value)
    if tz in ("utc8", "cn"):
        return (dt.tz_convert(None) + pd.Timedelta(hours=8)).strftime("%Y-%m-%d %H:%M UTC+8")
    if tz == "both":
        utc = dt.tz_convert(None)
        bj = utc + pd.Timedelta(hours=8)
        return f"{utc:%Y-%m-%d %H:%M UTC}\n{bj:%Y-%m-%d %H:%M UTC+8}"
    return dt.tz_convert(None).strftime("%Y-%m-%d %H:%M UTC")


def _event_rows(df, *, tz: str, limit: int = 8):
    rows = []
    for _, row in df.head(limit).iterrows():
        rows.append([
            _fmt_catalog_time(row.get("time"), tz),
            f"{float(row.get('mag', 0)):.1f}",
            normalize_mag_type(row.get("magType", row.get("magtype", ""))),
            f"{float(row.get('depth', 0)):.1f}",
            f"{float(row.get('dist_km', 0)):.1f}",
            str(row.get("place", ""))[:52],
        ])
    return rows


def _decade_rows(catalog_df):
    if catalog_df.empty:
        return []
    df = catalog_df.copy()
    t = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df[t.notna()].copy()
    if df.empty:
        return []
    df["decade"] = (t[t.notna()].dt.year // 10 * 10).astype(int).astype(str) + "s"
    grouped = df.groupby("decade")["mag"].agg(
        total="count",
        m5plus=lambda s: int((s >= 5).sum()),
        max_mag="max",
    )
    rows = []
    for decade, row in grouped.tail(8).iterrows():
        rows.append([decade, int(row["total"]), int(row["m5plus"]), f"{float(row['max_mag']):.1f}"])
    return rows


def _depth_rows(catalog_df):
    if catalog_df.empty or "depth" not in catalog_df:
        return []
    bins = [
        ("0-30 km", lambda s: (s >= 0) & (s < 30)),
        ("30-70 km", lambda s: (s >= 30) & (s < 70)),
        ("70-300 km", lambda s: (s >= 70) & (s < 300)),
        (">=300 km", lambda s: s >= 300),
    ]
    depth = pd.to_numeric(catalog_df["depth"], errors="coerce")
    mag = pd.to_numeric(catalog_df["mag"], errors="coerce")
    rows = []
    for label, mask_fn in bins:
        mask = mask_fn(depth)
        if not mask.any():
            rows.append([label, 0, 0, "—"])
            continue
        rows.append([
            label,
            int(mask.sum()),
            int(((mag >= 5) & mask).sum()),
            f"{float(mag[mask].max()):.1f}",
        ])
    return rows


def _catalog_date_range(catalog_df, tz: str) -> str:
    if catalog_df.empty or "time" not in catalog_df:
        return "无可用目录记录"
    t = pd.to_datetime(catalog_df["time"], utc=True, errors="coerce").dropna()
    if t.empty:
        return f"{len(catalog_df)} 条事件"
    start = _fmt_catalog_time(t.min(), tz).split()[0]
    end = _fmt_catalog_time(t.max(), tz).split()[0]
    return f"{len(catalog_df)} 条事件；{start} 至 {end}"


def _figure_source_note(stats: CatalogStats, radius_km: float, tz: str) -> str:
    min_mag = stats.query.min_magnitude if stats.query else 3.0
    return (
        f"图件来源：USGS FDSN 历史目录；统计范围：震中 {format_km(radius_km)} km，M≥{min_mag:g}；"
        f"全量统计 {stats.total_count} 条；时间按{_tz_name(tz)}显示。"
    )


def _tz_name(tz: str) -> str:
    if tz in ("utc8", "cn"):
        return "北京时间"
    if tz == "both":
        return "UTC 和北京时间"
    return "UTC"


def _event_brief(row, tz: str) -> str:
    if row is None:
        return "无"
    mag = float(row.get("mag", 0))
    dist = float(row.get("dist_km", 0))
    place = str(row.get("place", "")).strip()
    place_part = f"，{place[:40]}" if place else ""
    return f"M{mag:.1f}，{_fmt_catalog_time(row.get('time'), tz)}，距震中 {dist:.1f} km{place_part}"


def _emsc_summary_rows(supplemental: SupplementalData | None, tz: str):
    if not supplemental:
        return []
    if supplemental.emsc_error:
        return [["EMSC/SeismicPortal", "辅助目录不可用", _public_source_status(supplemental.emsc_error)]]
    df = supplemental.emsc_catalog
    if df.empty:
        return [["EMSC/SeismicPortal", "辅助目录", "未返回符合条件事件"]]
    largest = df.sort_values(["mag", "dist_km"], ascending=[False, True]).iloc[0]
    nearest = df.sort_values(["dist_km", "mag"], ascending=[True, False]).iloc[0]
    limit_note = "；达到返回上限" if supplemental.emsc_limited else ""
    return [
        ["EMSC/SeismicPortal", "返回事件数", f"{len(df)} 条{limit_note}"],
        ["最大震级辅助记录", "仅用于交叉核对", _event_brief(largest, tz)],
        ["最近辅助记录", "仅用于交叉核对", _event_brief(nearest, tz)],
    ]


def _public_source_status(value: str) -> str:
    raw = str(value or "")
    if "Expecting value" in raw or "line " in raw or "char " in raw:
        return "服务返回为空或格式异常，本次未纳入辅助核对"
    return raw[:80] if raw else "本次未纳入辅助核对"


def _prepare_catalog_columns(catalog_df):
    if catalog_df.empty:
        return catalog_df
    df = catalog_df.copy()
    df["_time_dt"] = pd.to_datetime(df.get("time"), utc=True, errors="coerce")
    df["_mag_num"] = pd.to_numeric(df.get("mag"), errors="coerce")
    df["_dist_num"] = pd.to_numeric(df.get("dist_km"), errors="coerce")
    return df


def _make_report_charts(catalog_df, output_docx_path: str, tz: str):
    if catalog_df.empty:
        return []
    df = _prepare_catalog_columns(catalog_df) if "_mag_num" not in catalog_df.columns else catalog_df.copy()
    df = df.dropna(subset=["_mag_num"])
    if df.empty:
        return []

    out_dir = os.path.dirname(os.path.abspath(output_docx_path))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(output_docx_path))[0]
    charts = []
    plt.rcParams["axes.unicode_minus"] = False
    chart_font = _chart_font()

    time_df = df.dropna(subset=["_time_dt"]).sort_values("_time_dt")
    if not time_df.empty:
        if tz in ("utc8", "cn", "both"):
            x = time_df["_time_dt"].dt.tz_convert(None) + pd.Timedelta(hours=8)
            xlabel = "时间 (UTC+8)"
        else:
            x = time_df["_time_dt"].dt.tz_convert(None)
            xlabel = "时间 (UTC)"
        path = os.path.join(out_dir, f"{stem}_magnitude_time.png")
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.scatter(x, time_df["_mag_num"], s=22, c="#c62828", alpha=0.75, edgecolors="white", linewidths=0.4)
        ax.set_title("历史地震震级-时间分布", fontsize=12, fontweight="bold", fontproperties=chart_font)
        ax.set_xlabel(xlabel, fontproperties=chart_font)
        ax.set_ylabel("震级 M", fontproperties=chart_font)
        ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.65)
        fig.autofmt_xdate(rotation=25)
        fig.tight_layout()
        fig.savefig(path, dpi=200, facecolor="white")
        plt.close(fig)
        charts.append((path, "历史地震震级-时间分布"))

    dist_df = df.dropna(subset=["_dist_num"]).sort_values("_dist_num")
    if not dist_df.empty:
        path = os.path.join(out_dir, f"{stem}_magnitude_distance.png")
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.scatter(dist_df["_dist_num"], dist_df["_mag_num"], s=24, c="#1f78b4", alpha=0.75, edgecolors="white", linewidths=0.4)
        ax.set_title("历史地震震级-距离分布", fontsize=12, fontweight="bold", fontproperties=chart_font)
        ax.set_xlabel("距震中距离 (km)", fontproperties=chart_font)
        ax.set_ylabel("震级 M", fontproperties=chart_font)
        ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.65)
        fig.tight_layout()
        fig.savefig(path, dpi=200, facecolor="white")
        plt.close(fig)
        charts.append((path, "历史地震震级-距离分布"))
    return charts


# ============================================================================
# 页脚（页码字段）
# ============================================================================

def _set_footer_page_number(section, format_switch: str = "arabic"):
    """给 section 的页脚插入居中 PAGE 字段。

    format_switch: 'arabic' 或 'ROMAN'（大写罗马数字）
    """
    footer = section.footer
    footer.is_linked_to_previous = False
    # 清空已有内容
    for p in footer.paragraphs:
        p._element.getparent().remove(p._element)
    p = footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = p.add_run()
    _set_run_font(run, FANGSONG_FONT_NAMES, size_pt=9)

    # PAGE 字段
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" PAGE \\* {format_switch} \\* MERGEFORMAT "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._element.append(fld_begin)
    run._element.append(instr)
    run._element.append(fld_sep)
    run._element.append(fld_end)


def _suppress_footer_page_number(section):
    """封面不显示页码。"""
    footer = section.footer
    footer.is_linked_to_previous = False
    for p in footer.paragraphs:
        p._element.getparent().remove(p._element)
    # 添加一个空段落（页脚必须有内容才不会被继承）
    p = footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


# ============================================================================
# 页码起始
# ============================================================================

def _set_section_page_number_start(section, start: int = 1):
    """让 section 页码从 start 开始。"""
    sectPr = section._sectPr
    pgNumType = sectPr.find(qn("w:pgNumType"))
    if pgNumType is None:
        pgNumType = OxmlElement("w:pgNumType")
        sectPr.append(pgNumType)
    pgNumType.set(qn("w:start"), str(start))
    # 不设 fmt，避免冲突 —— fmt 用 footer 字段控制


# ============================================================================
# 段落辅助函数
# ============================================================================

def _add_body_paragraph(doc, text: str, *, font_names=None, size_pt=14,
                        indent_chars=2, line_pt=None, bold=False,
                        align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    """添加一个正文段落（四号，2字符首行缩进，单倍行距，两端对齐）。"""
    if font_names is None:
        font_names = FANGSONG_FONT_NAMES
    p = doc.add_paragraph()
    p.alignment = align
    if indent_chars > 0:
        _set_paragraph_first_line_indent_chars(p, indent_chars)
    if line_pt is None:
        _set_auto_spacing(p, before=0, after=0, line=1.0)
    else:
        _set_paragraph_line_spacing_exact(p, line_pt)
    run = p.add_run(text)
    _set_run_font(run, font_names, size_pt=size_pt, bold=bold)
    return p


def _add_heading(doc, text: str, level: int = 1):
    """添加章节标题（宋体加粗）。"""
    sizes = {1: 14, 2: 14, 3: 14}
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _set_auto_spacing(p, before=6, after=4, line=1.0)
    # 在大纲级别（让目录能识别）
    pPr = p._element.get_or_add_pPr()
    outlineLvl = OxmlElement("w:outlineLvl")
    outlineLvl.set(qn("w:val"), str(level - 1))
    pPr.append(outlineLvl)
    # style = "Heading1" 之类
    style_id = f"Heading{level}"
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is None:
        pStyle = OxmlElement("w:pStyle")
        pPr.insert(0, pStyle)
    pStyle.set(qn("w:val"), style_id)

    run = p.add_run(text)
    _set_run_font(run, HEITI_FONT_NAMES, size_pt=sizes.get(level, 14), bold=True,
                  color=RGBColor(0, 0, 0))
    return p


def _add_centered_paragraph(doc, text: str, *, font_names=None, size_pt=12,
                            bold=False, line_pt=24.0):
    """添加居中段落（用于图注、标题等）。"""
    if font_names is None:
        font_names = FANGSONG_FONT_NAMES
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_paragraph_line_spacing_exact(p, line_pt)
    run = p.add_run(text)
    _set_run_font(run, font_names, size_pt=size_pt, bold=bold)
    return p


def _source_text_intro(source_text: str | None) -> str:
    text = " ".join((source_text or "").split()).strip()
    if not text:
        return ""
    return text if text.startswith("据") else f"据{text}"


def _add_image_centered(doc, image_path: str, width_cm: float = 14.5):
    """添加居中图片。

    注意：图片所在段落不能用固定行距（exact），否则图片会被裁剪成一行高。
    使用单倍行距（line=240, lineRule=auto）让段落自适应图片高度。
    """
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    # 单倍行距 + auto 让段落按图片高度自动撑开
    pPr = p._element.get_or_add_pPr()
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:line"), "240")
    spacing.set(qn("w:lineRule"), "auto")
    # 段前段后留一点空隙
    spacing.set(qn("w:before"), "120")
    spacing.set(qn("w:after"), "120")
    run = p.add_run()
    run.add_picture(image_path, width=Cm(width_cm))
    return p


# ============================================================================
# 目录
# ============================================================================

def _add_toc(doc):
    """插入 Word 自动目录字段。打开时需手动刷新（右键 → 更新域）。"""
    p = doc.add_paragraph()
    pPr = p._element.get_or_add_pPr()
    # 用 w:pStyle 让它属于 TOC 区域
    pStyle = OxmlElement("w:pStyle")
    pStyle.set(qn("w:val"), "TOC1")
    pPr.append(pStyle)

    run = p.add_run()
    _set_run_font(run, FANGSONG_FONT_NAMES, size_pt=12)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")

    placeholder_run = p.add_run("[请在 Word/WPS 中右键此处选择「更新域」以生成目录]")
    _set_run_font(placeholder_run, FANGSONG_FONT_NAMES, size_pt=11,
                  color=RGBColor(0x99, 0x99, 0x99))

    fld_end_run = p.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    fld_end_run._element.append(fld_end)

    # 把 begin / instr / sep 放在第一个 run 里
    run._element.append(fld_begin)
    run._element.append(instr)
    run._element.append(fld_sep)


# ============================================================================
# 封面
# ============================================================================

def _add_cover_page(doc, mainshock: MainShock, title_zh: str, title_en: str, tz: str = "utc"):
    """添加封面页。封面单独占一页，不显示页码。"""
    # 标题（上方留白）—— 适度，避免溢出
    for _ in range(2):
        p = doc.add_paragraph()
        _set_paragraph_line_spacing_exact(p, 24.0)

    # 中文主标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_paragraph_line_spacing_exact(p, 36.0)
    run = p.add_run(title_zh)
    _set_run_font(run, HEITI_FONT_NAMES, size_pt=22, bold=True,
                  color=RGBColor(0x1a, 0x1a, 0x1a))

    # 英文副标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_paragraph_line_spacing_exact(p, 28.0)
    run = p.add_run(title_en)
    _set_run_font(run, HEITI_FONT_NAMES, size_pt=13, bold=False,
                  color=RGBColor(0x55, 0x55, 0x55))

    # 中间留白
    for _ in range(3):
        p = doc.add_paragraph()
        _set_paragraph_line_spacing_exact(p, 22.0)

    # 震中基本信息表
    table = doc.add_table(rows=4, cols=2)
    table.alignment = 1  # center
    _set_table_no_borders(table)

    # 根据时区模式构造发震时间字符串
    if tz == "utc":
        time_label = "发震时间 / Time (UTC)"
        time_value = mainshock.time_str + "\n" + mainshock.time_str_en
    elif tz in ("utc8", "cn"):
        time_label = "发震时间 / Time (UTC+8)"
        time_value = mainshock.time_bj_str + "\n" + mainshock.time_bj_str_en
    else:  # both
        time_label = "发震时间 / Time (UTC & UTC+8)"
        time_value = (
            f"UTC：{mainshock.time_str}\n"
            f"北京时间：{mainshock.time_bj_str}"
        )

    info_rows = [
        (time_label, time_value),
        ("震中位置 / Epicenter",
         f"{mainshock.latitude:.2f}°{'S' if mainshock.latitude < 0 else 'N'}, "
         f"{abs(mainshock.longitude):.2f}°{'W' if mainshock.longitude < 0 else 'E'}"),
        ("震级 / Magnitude", f"{mainshock.mag_type} {mainshock.magnitude:.1f}"),
        ("震源深度 / Depth", f"{mainshock.depth_km:.1f} km"),
    ]
    for i, (k, v) in enumerate(info_rows):
        c1 = table.cell(i, 0)
        c2 = table.cell(i, 1)
        # 左列：标签
        p1 = c1.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r1 = p1.add_run(k)
        _set_run_font(r1, HEITI_FONT_NAMES, size_pt=12, bold=True)
        # 右列：值
        p2 = c2.paragraphs[0]
        p2.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r2 = p2.add_run(v)
        _set_run_font(r2, FANGSONG_FONT_NAMES, size_pt=12)
        # 设置列宽
        c1.width = Cm(5.5)
        c2.width = Cm(8.5)

    # 底部留白 + 编制信息
    for _ in range(3):
        p = doc.add_paragraph()
        _set_paragraph_line_spacing_exact(p, 22.0)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_paragraph_line_spacing_exact(p, 24.0)
    r = p.add_run(f"数据来源：USGS Earthquake Hazards Program\n"
                  f"Data Source: USGS Earthquake Hazards Program")
    _set_run_font(r, FANGSONG_FONT_NAMES, size_pt=10,
                  color=RGBColor(0x66, 0x66, 0x66))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_paragraph_line_spacing_exact(p, 24.0)
    r = p.add_run(f"生成日期：{datetime.now().strftime('%Y-%m-%d')}")
    _set_run_font(r, FANGSONG_FONT_NAMES, size_pt=10,
                  color=RGBColor(0x66, 0x66, 0x66))


# ============================================================================
# 主构建函数
# ============================================================================

def build_report(
    mainshock: MainShock,
    stats: CatalogStats,
    catalog_df,
    map_image_path: str,
    output_docx_path: str,
    *,
    fig_num: str = "1",
    title_zh: Optional[str] = None,
    title_en: Optional[str] = None,
    radius_km: float = 200.0,
    include_extended_chapters: bool = True,
    report_level: str | None = None,
    tz: str = "utc",
    supplemental: SupplementalData | None = None,
    removed_mainshock_count: int = 0,
    catalog_warnings: list[str] | None = None,
    source_text: str | None = None,
) -> str:
    """构建更紧凑的分析型 docx 报告。"""
    if report_level is None:
        report_level = "full" if include_extended_chapters else "medium"
    elif report_level not in {"simple", "medium", "full"}:
        report_level = "simple"
    include_extended_chapters = report_level == "full"
    catalog_df = _prepare_catalog_columns(catalog_df)
    if title_zh is None:
        place_short = (mainshock.place.split(",")[0].strip() if mainshock.place else "震中区")[:20]
        spacer = " " if place_short.isascii() else ""
        title_time = mainshock.time_utc + timedelta(hours=8) if tz in ("utc8", "cn", "both") else mainshock.time_utc
        title_zh = (
            f"{title_time.year}年{title_time.month}月{title_time.day}日"
            f"{spacer}{place_short} {mainshock.mag_type}{mainshock.magnitude:.1f} 地震 震中区历史地震活动分析"
        )
    doc = Document()

    style_normal = doc.styles["Normal"]
    style_normal.font.name = "Times New Roman"
    style_normal.font.size = Pt(14)
    rpr = style_normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("ascii", "hAnsi", "cs"):
        rfonts.set(qn(f"w:{attr}"), "Times New Roman")
    rfonts.set(qn("w:eastAsia"), FANGSONG_FONT_NAMES[0])

    section = doc.sections[0]
    section.page_height = Twips(16838)  # A4 override for Chinese report delivery
    section.page_width = Twips(11906)
    section.top_margin = Cm(1.75)
    section.bottom_margin = Cm(1.7)
    section.left_margin = Cm(1.85)
    section.right_margin = Cm(1.85)
    section.footer_distance = Cm(0.9)
    _set_section_page_number_start(section, start=1)
    _set_footer_page_number(section, format_switch="arabic")

    # Title block
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_auto_spacing(p, before=0, after=4, line=1.0)
    run = p.add_run(title_zh)
    title_color = RGBColor(0, 0, 0) if report_level == "simple" else REPORT_BLUE
    _set_run_font(run, HEITI_FONT_NAMES, size_pt=16, bold=True, color=title_color)

    if report_level == "simple":
        intro = _source_text_intro(source_text) or build_mainshock_summary_zh_v2(mainshock, tz=tz)
        _add_report_paragraph(doc, intro, size=14, line=1.0)
        _add_report_paragraph(
            doc,
            build_narrative_zh(
                mainshock,
                stats,
                fig_num=fig_num,
                radius_km=radius_km,
                mag_type=mainshock.mag_type,
                tz=tz,
            ),
            size=14,
            line=1.0,
        )
        _add_image_centered(doc, map_image_path, width_cm=REPORT_MAP_WIDTH_CM)
        _add_centered_paragraph(
            doc,
            f"图 {fig_num} 震中周围历史地震分布图",
            font_names=FANGSONG_FONT_NAMES,
            size_pt=10.5,
            bold=True,
            line_pt=16.0,
        )
        os.makedirs(os.path.dirname(os.path.abspath(output_docx_path)), exist_ok=True)
        doc.save(output_docx_path)
        return output_docx_path

    _add_table(
        doc,
        ["项目", "内容", "项目", "内容"],
        [[
            "发震时间",
            mainshock.time_bj_str if tz in ("utc8", "cn") else mainshock.time_str,
            "震级",
            f"{mainshock.mag_type} {mainshock.magnitude:.1f}",
        ], [
            "震中",
            f"{mainshock.latitude:.2f}°{'S' if mainshock.latitude < 0 else 'N'}, "
            f"{abs(mainshock.longitude):.2f}°{'W' if mainshock.longitude < 0 else 'E'}",
            "深度",
            f"{mainshock.depth_km:.1f} km",
        ], [
            "统计半径",
            f"{format_km(radius_km)} km",
            "主目录",
            "USGS FDSN",
        ]],
        widths_cm=[3.0, 5.2, 3.0, 5.2],
    )

    if removed_mainshock_count > 0:
        mainshock_filter = f"已剔除与本次地震高度一致的记录 {removed_mainshock_count} 条"
    elif mainshock.event_id not in ("manual", "csv"):
        mainshock_filter = "已按 USGS eventid 从历史目录中排除主震"
    else:
        mainshock_filter = "没有发现可以明确剔除的主震重复记录"

    largest_event = None if catalog_df.empty else catalog_df.sort_values(["mag", "dist_km"], ascending=[False, True]).iloc[0]
    fault_point = "GEM 活动断层数据未给出可用最近距离"
    if supplemental and supplemental.nearest_fault_distance_km is not None:
        fault_point = (
            f"GEM 制图范围内有 {supplemental.fault_count} 条活动断层段，"
            f"最近断层距震中约 {supplemental.nearest_fault_distance_km:.1f} km"
        )
    _add_key_points_box(
        doc,
        [
            (
                "统计结论",
                f"以 USGS 为统计口径，震中 {format_km(radius_km)} km 范围内共有 {stats.total_count} 条记录"
                f"（{mainshock_filter}），其中 M5+ {stats.n5} 条、M6+ {stats.n6} 条、M7+ {stats.n7} 条。",
            ),
            ("代表性事件", f"目录内最大震级记录为 {_event_brief(largest_event, tz)}。"),
            ("构造背景", f"{fault_point}。EMSC/SeismicPortal 只用于辅助核对，不并入 USGS 统计。"),
        ],
    )

    _add_report_heading(doc, "一、事件概况", level=1)
    _add_report_paragraph(doc, _source_text_intro(source_text) or build_mainshock_summary_zh_v2(mainshock, tz=tz))

    _add_report_heading(doc, "二、数据来源", level=1)
    emsc_count = len(supplemental.emsc_catalog) if supplemental and not supplemental.emsc_catalog.empty else 0
    emsc_status = (
        f"{emsc_count} 条辅助事件"
        if supplemental and not supplemental.emsc_error
        else _public_source_status(supplemental.emsc_error) if supplemental and supplemental.emsc_error else "未查询"
    )
    if supplemental and supplemental.emsc_limited:
        emsc_status += "；达到返回上限"
    fault_status = "未加载"
    if supplemental:
        if supplemental.nearest_fault_distance_km is not None:
            fault_status = f"{supplemental.fault_count} 条断层段；最近约 {supplemental.nearest_fault_distance_km:.1f} km"
        else:
            fault_status = f"{supplemental.fault_count} 条断层段"
    _add_table(
        doc,
        ["数据层", "说明", "本次结果"],
        [
            ["USGS FDSN 事件目录", "主统计来源，统计事件数量、震级、年代分布和代表性事件", _catalog_date_range(catalog_df, tz)],
            ["EMSC/Seismic Portal FDSN", "辅助核对事件覆盖；不并入 USGS 统计，防止重复计数", emsc_status],
            ["GEM Global Active Faults", "显示活动断层，估算最近断层距离", fault_status],
            ["天地图 1:100万 BOUL / Natural Earth", "中国区域使用国内 1:100万 BOUL 边界；国外使用 Natural Earth 底图和城市", "用于地图绘制"],
        ],
        widths_cm=[4.2, 7.2, 5.0],
    )

    emsc_rows = _emsc_summary_rows(supplemental, tz)
    if emsc_rows:
        _add_report_heading(doc, "辅助目录核对", level=2)
        _add_table(
            doc,
            ["来源", "项目", "结果"],
            emsc_rows,
            widths_cm=[4.0, 4.2, 8.2],
        )

    _add_report_heading(doc, "三、数量分布", level=1)
    narrative_zh = build_narrative_zh(
        mainshock, stats, fig_num=fig_num, radius_km=radius_km, mag_type=mainshock.mag_type, tz=tz
    )
    _add_report_paragraph(doc, narrative_zh)

    mag_values = pd.to_numeric(catalog_df.get("mag"), errors="coerce") if not catalog_df.empty else pd.Series(dtype=float)

    def _mag_interval_mask(low: float, high: float | None = None):
        mask = mag_values >= low
        if high is not None:
            mask &= mag_values < high
        return mask

    def _mag_interval_count(low: float, high: float | None = None) -> int:
        if catalog_df.empty:
            return 0
        return int(_mag_interval_mask(low, high).sum())

    def _nearest_mag_interval(low: float, high: float | None = None):
        if catalog_df.empty:
            return None
        sub = catalog_df[_mag_interval_mask(low, high)]
        if sub.empty:
            return None
        return sub.loc[sub["dist_km"].idxmin()]

    def _bin_row(label, count, nearest):
        if nearest is None:
            return [label, count, "—", "—"]
        return [label, count, f"{float(nearest['dist_km']):.1f}", _fmt_catalog_time(nearest["time"], tz)]

    _add_table(
        doc,
        ["震级档", "分档事件数", "最近距离 km", "最近事件时间"],
        [
            _bin_row("M≥8", _mag_interval_count(8), _nearest_mag_interval(8)),
            _bin_row("7≤M<8", _mag_interval_count(7, 8), _nearest_mag_interval(7, 8)),
            _bin_row("6≤M<7", _mag_interval_count(6, 7), _nearest_mag_interval(6, 7)),
            _bin_row("5≤M<6", _mag_interval_count(5, 6), _nearest_mag_interval(5, 6)),
            _bin_row("4≤M<5", _mag_interval_count(4, 5), _nearest_mag_interval(4, 5)),
            _bin_row("3≤M<4", _mag_interval_count(3, 4), _nearest_mag_interval(3, 4)),
        ],
        widths_cm=[3.0, 2.6, 3.4, 7.4],
    )

    depth_rows = _depth_rows(catalog_df)
    if depth_rows:
        _add_report_heading(doc, "按震源深度统计", level=2)
        _add_table(
            doc,
            ["深度范围", "事件数", "M5+ 数量", "最大震级"],
            depth_rows,
            widths_cm=[3.2, 3.0, 3.0, 3.0],
        )

    decade_rows = _decade_rows(catalog_df)
    if decade_rows:
        _add_report_heading(doc, "按年代统计", level=2)
        _add_table(
            doc,
            ["年代", "事件数", "M5+ 数量", "最大震级"],
            decade_rows,
            widths_cm=[3.2, 3.0, 3.0, 3.0],
        )

    if include_extended_chapters and not catalog_df.empty:
        _add_report_heading(doc, "四、代表性地震", level=1)
        _add_report_heading(doc, "最大震级地震", level=2)
        largest = catalog_df.sort_values(["mag", "dist_km"], ascending=[False, True])
        _add_table(
            doc,
            ["日期", "M", "类型", "深度 km", "距震中 km", "位置"],
            _event_rows(largest, tz=tz, limit=5),
            widths_cm=[3.4, 1.0, 1.2, 1.5, 1.8, 7.5],
        )

        near_m5 = catalog_df[catalog_df["mag"] >= 5.0].sort_values(["dist_km", "mag"], ascending=[True, False])
        if not near_m5.empty:
            _add_report_heading(doc, "距震中最近的 M5+ 地震", level=2)
            _add_table(
                doc,
                ["日期", "M", "类型", "深度 km", "距震中 km", "位置"],
                _event_rows(near_m5, tz=tz, limit=5),
                widths_cm=[3.4, 1.0, 1.2, 1.5, 1.8, 7.5],
            )

    _add_report_heading(doc, "五、空间分布与构造背景", level=1)
    if supplemental and supplemental.nearest_fault_distance_km is not None:
        _add_report_paragraph(
            doc,
            f"GEM 数据在制图范围内包含 {supplemental.fault_count} 条活动断层段。"
            f"按断层折线顶点粗略估算，最近的断层为 {supplemental.nearest_fault_name}，"
            f"距震中约 {supplemental.nearest_fault_distance_km:.1f} km。"
            "这个距离只说明区域构造位置，不能当作震源破裂面到断层面的精确距离。"
        )
    else:
        _add_report_paragraph(doc, "地图已叠加 GEM 活动断层数据；本次没有得到可靠的最近断层距离。")

    city_rows = nearest_city_rows(mainshock.latitude, mainshock.longitude, radius_km)
    if city_rows:
        _add_report_heading(doc, "附近主要城市参考", level=2)
        _add_table(
            doc,
            ["城市", "距震中 km", "坐标"],
            city_rows,
            widths_cm=[5.0, 3.2, 4.8],
        )

    _add_image_centered(doc, map_image_path, width_cm=REPORT_MAP_WIDTH_CM)
    _add_centered_paragraph(doc, f"图 {fig_num} 震中周围历史地震分布图",
                            font_names=FANGSONG_FONT_NAMES, size_pt=10.5, bold=True, line_pt=16.0)
    _add_centered_paragraph(doc, _figure_source_note(stats, radius_km, tz),
                            font_names=FANGSONG_FONT_NAMES, size_pt=7.5, line_pt=11.0)

    if include_extended_chapters:
        chart_num = int(fig_num) + 1 if str(fig_num).isdigit() else 2
        for chart_path, caption in _make_report_charts(catalog_df, output_docx_path, tz):
            _add_image_centered(doc, chart_path, width_cm=15.0)
            _add_centered_paragraph(doc, f"图{chart_num} {caption}",
                                    font_names=FANGSONG_FONT_NAMES, size_pt=10.5, bold=True, line_pt=16.0)
            _add_centered_paragraph(doc, _figure_source_note(stats, radius_km, tz),
                                    font_names=FANGSONG_FONT_NAMES, size_pt=7.5, line_pt=11.0)
            chart_num += 1

    if include_extended_chapters:
        _add_report_heading(doc, "六、数据质量与口径", level=1)
        quality_rows = [
            ["统计口径", "USGS FDSN 为唯一计数来源；EMSC 仅辅助核对，不并入统计。"],
            ["时间范围", _catalog_date_range(catalog_df, tz)],
            ["震级阈值", f"目录查询下限为 M≥{stats.query.min_magnitude if stats.query else 3.0:g}；早期中小震记录完整性弱于现代仪器时期。"],
            ["目录完整性震级", f"Mc≈{stats.mc_estimate:.1f}；{stats.mc_method}" if stats.mc_estimate is not None else stats.mc_method or "事件数不足，未估计"],
            ["主震去重", mainshock_filter],
            ["空间距离", "表内距离为震中间大圆距离；断层距离为区域构造背景估算，不代表破裂面精确距离。"],
        ]
        if stats.query_limit_hit:
            quality_rows.append(["USGS 查询上限", f"返回记录达到 {stats.query_limit} 条上限；统计可能低于真实目录量，需提高最小震级或缩小半径复核。"])
        for warning in catalog_warnings or []:
            quality_rows.append(["数据提示", warning])
        _add_table(doc, ["检查项", "说明"], quality_rows, widths_cm=[3.5, 12.8])
        _add_report_paragraph(
            doc,
            "本报告的事件数量、震级分布和年代统计均以 USGS FDSN 目录为准。"
            "EMSC/Seismic Portal 用来检查区域内是否还有可参考的事件记录。"
            "同一地震在不同机构目录中可能有不同编号、震级类型和更新时间，因此 EMSC 记录不并入 USGS 统计。"
            "早期目录对中小地震的记录不如现代仪器时期完整，20 世纪上半叶的 M3-M5 事件可能偏少。"
            "文中距离均为震中间大圆距离；构造解释还需要结合震源机制、速度模型和本地台网目录。"
        )

    # 保存
    os.makedirs(os.path.dirname(os.path.abspath(output_docx_path)), exist_ok=True)
    doc.save(output_docx_path)
    return output_docx_path


# ============================================================================
# PDF 转换
# ============================================================================

def convert_docx_to_pdf(docx_path: str, output_dir: str = None, timeout: int = 120) -> str:
    """用 LibreOffice 把 docx 转 pdf。"""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(docx_path))
    office = (
        os.environ.get("LIBREOFFICE_BIN")
        or shutil.which("libreoffice")
        or shutil.which("soffice")
        or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    )
    if not os.path.exists(office):
        raise RuntimeError("未找到 LibreOffice/soffice，无法转换 PDF")
    cmd = [office, "--headless", "--convert-to", "pdf",
           "--outdir", output_dir, docx_path]
    with tempfile.TemporaryDirectory(prefix="quake-lo-") as home:
        env = os.environ.copy()
        env["HOME"] = home
        env["UserInstallation"] = f"file://{home}/profile"
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
            proc.communicate()
            raise RuntimeError("LibreOffice 转换超时，请稍后重试")
        if proc.returncode != 0:
            msg = (stderr or stdout or "").strip().splitlines()[-1:] or ["LibreOffice 转换失败"]
            raise RuntimeError(msg[0])
    pdf_path = os.path.join(output_dir,
                            os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF 文件未生成：{pdf_path}")
    return pdf_path
