# USGS 地震历史情况一键自动报告生成器

> 从 USGS Earthquake Hazards Program 拉取历史地震目录，一键产出"震中周边历史地震分布图 + 完整 Word 报告 + PDF"，严格复刻参考模板风格（仿宋_GB2312 / 14pt / 2 字符首行缩进 / 居中页码页脚），并扩展为含封面、目录、主震概要、统计表、数据来源说明的中英双语完整报告。

## 功能特性

- **四种震中信息来源**
  - 手动输入：经纬度 + 震级 + 发震时间 + 可选地名/深度/震级类型
  - 按 eventid：USGS 事件唯一 ID（如 `us7000xxxx`），自动拉取完整参数
  - 拉取最新大震：列出近 30 天 M≥6.0 全球事件，自动选最大事件
  - 批量 CSV：一次跑多个事件
- **可调查询参数**：半径 km / 起始时间 / 结束时间 / 最小震级
- **地图要素全复刻**：黄色五角星震中、5 档红色震级圆、黑色断层线、海岸线+国界、200km 半径虚线圆、比例尺、中英双语图例
- **断层数据**：内置 GEM 全球活动断层数据库（13,696 条断层段），自动按 bbox 裁剪
- **报告结构**：封面 → 目录 → 一、主震概要 → 二、历史地震统计（模板 A/B 文字）→ 三、震中分布图 → 四、震级档位统计表 → 五、数据来源与方法说明
- **自动模板选择**：当 N7=N8=0 时自动切换为模板 B（自 1950 年以来）
- **最近事件 4 档分级**：M≥8 / 7-8 / 6-7 / 5-6，缺失档位自动跳过
- **PDF 同步生成**：docx 生成后用 LibreOffice 转 PDF
- **Web UI**：Next.js 单页应用，三种模式切换，实时显示生成进度与结果预览

## 文件结构

```
项目根目录/
├── scripts/
│   ├── quake_report.py             # CLI 入口（软链接 → cli.py）
│   └── quake_report/
│       ├── cli.py                  # argparse + 四种模式分发
│       └── core/
│           ├── usgs_client.py      # USGS FDSN API + 主震/目录/统计
│           ├── fault_loader.py     # GEM shapefile 加载与裁剪
│           ├── map_renderer.py     # cartopy + matplotlib 出图
│           ├── narrative_builder.py # 中英双语叙述模板
│           └── docx_builder.py     # python-docx + LibreOffice PDF
├── data/gem_faults/                # GEM 全球活动断层 shapefile
├── src/                            # Next.js 16 前端
│   ├── app/page.tsx                # 主页表单
│   ├── app/api/quake/generate/     # POST 生成接口
│   ├── app/api/quake/recent/       # GET 近期大震列表
│   └── app/download/[...path]/     # 静态文件下载代理
└── download/                       # 生成的图件与报告输出目录
```

## CLI 使用

### 模式 1：手动输入参数

```bash
python3 scripts/quake_report.py \
    --mode manual \
    --lat 41.5 --lon 142.5 --mag 7.0 \
    --time "2026-06-25T14:17:00Z" \
    --place "Honshu, Japan" \
    --slug japan_honshu_M7.0 \
    --fig-num 1
```

### 模式 2：按 USGS eventid

```bash
python3 scripts/quake_report.py --mode eventid --event-id us6000t8pa
```

### 模式 3：拉取近 30 天最大事件

```bash
python3 scripts/quake_report.py --mode recent
```

### 模式 4：批量 CSV

```csv
latitude,longitude,magnitude,time,depth,place,event_id
36.4731,70.7644,6.1,2026-06-27T13:34:52Z,199,Afghanistan,us6000t8pa
5.2392,125.1965,6.5,2026-06-26T11:34:41Z,40,Philippines,us6000t8ec
```

```bash
python3 scripts/quake_report.py --mode batch --csv events.csv
```

### 通用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--radius-km` | 200 | 历史地震查询半径 |
| `--start-time` | 1900-01-01 | 起始时间 ISO8601 |
| `--end-time` | 当前 | 结束时间 ISO8601 |
| `--min-mag` | 3.0 | 最小震级 |
| `--fig-num` | 1 | 图编号字符串（可填 xxx 用于占位） |
| `--slug` | 自动 | 输出文件名前缀 |
| `--no-pdf` | false | 不生成 PDF |
| `--no-extended` | false | 精简模式（仅正文+图） |
| `--output-dir` | 项目根目录/download | 输出目录 |
| `--json-summary` | - | 把生成摘要写入 JSON |

## Web UI

启动 Next.js dev server（已在 `.zscripts/dev.sh` 中自动启动），访问主页：

- 左栏：选择模式 → 填写参数 → 点击"一键生成报告"
- 右栏：实时显示生成进度 → 主震概要卡片 → 分布图预览 → 下载按钮（Word / PDF / 原图）

## 输出说明

每次生成会产出 3 个文件（除 `--no-pdf` 外）：

| 文件 | 路径 |
|---|---|
| 分布图 | `{slug}_map.png` |
| Word 报告 | `{slug}_report.docx` |
| PDF 报告 | `{slug}_report.pdf` |

## 报告模板说明

### 模板 A（完整版）—— 当 N7>0 或 N8>0 时使用

> 据统计，在本次地震的震中周围200千米以内，发生3级以上地震{N3}次，4级以上地震为{N4}次，5级以上地震{N5}次，6级以上地震{N6}次，7级以上地震{N7}次，8级以上地震{N8}次。距离震中最近的8级及以上地震为UTC时间...发生的Mw {M8}地震，震中距离约...千米。距离震中最近的7级-8级地震为...。距震中最近的6-7级地震为...。距震中最近的5-6级地震为...。震中周边历史地震分布图如图1所示。

### 模板 B（简化版）—— 当 N7=N8=0 时使用

> 据统计，自1950年以来，在本次地震的震中周围200千米以内，发生3级以上地震{N3}次，4级以上地震为{N4}次，5级以上地震{N5}次，6级以上地震{N6}次，7级以上地震{N7}次。距震中最近的6-7级地震为...。距震中最近的5-6级地震为...。震中周边历史地震分布图如图1所示。

## 数据源

- **历史地震目录**：USGS FDSN Web Service https://earthquake.usgs.gov/fdsnws/event/1/
- **活动断层**：GEM Global Active Faults Database https://github.com/GEMScienceTools/gem-global-active-faults
- **海岸线/国界**：Natural Earth（通过 cartopy 调用）

## 技术栈

- Python 3.12
- cartopy 0.25 / matplotlib 3.11
- python-docx 1.2
- pandas 2.2 / requests 2.32
- LibreOffice（docx → PDF）
- Next.js 16 / TypeScript 5 / Tailwind 4 / shadcn/ui
