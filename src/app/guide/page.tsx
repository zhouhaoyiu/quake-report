import Link from "next/link";
import type { ReactNode } from "react";
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  MapPin,
  Search,
  Settings,
} from "lucide-react";

const quickStart = [
  ["1. 选择事件来源", "已有 USGS 编号就用 Event ID；没有编号可粘贴测定文本；应急演示可用近期大震。"],
  ["2. 核对主震参数", "确认时间、经纬度、震级、深度和报告地震名称。文本缺年份时，先看候选事件再决定。"],
  ["3. 保持默认参数", "默认半径 200 km、M≥3.0、最简报告适合先跑通流程。需要更多统计再提高复杂度。"],
  ["4. 生成并下载", "生成中会显示预计目录量和阶段。完成后先下载 Word；需要 PDF 时再点击 PDF 下载。"],
];

const inputModes = [
  ["近期大震", "适合快速生成报告或现场演示。系统从 USGS 拉取近 30 天较大地震，默认选最新事件。"],
  ["USGS Event ID", "适合你已经知道事件编号的情况，例如 us6000t8pa。编号可从 USGS 事件页面 URL 末尾复制。"],
  ["测定文本自动提取", "可粘贴“中国地震台网正式测定……”这类文字。系统会提取时间、位置、震级、深度和地点。"],
  ["手动输入", "适合没有 Event ID 的历史事件。纬度北正南负，经度东正西负，发震时间使用 UTC。"],
  ["全量目录搜索", "适合查找历史事件。可输入 Event ID、年份地区、震级或坐标半径；结果每页 10 条。"],
];

const searchExamples = [
  "us6000t8pa",
  "2008 M7 China",
  "2026 M6 Japan",
  "10.44,-68.47 r=200",
];

const params = [
  ["查询半径 km", "以主震震中为圆心统计历史地震。建议先用 200；半径过大时事件多，生成会变慢。"],
  ["最小震级", "默认 M≥3.0。如果事件太多，可先改成 4.0 或 5.0 试跑。"],
  ["图编号", "只影响报告图题，例如“图1”。一般保留默认值 1。"],
  ["输出文件名", "可留空，系统会按年月、事件编号和震级自动生成。"],
  ["时间显示时区", "影响报告正文和统计表的时间显示。国内汇报建议用北京时间。"],
  ["地图显示", "全量点显示所有目录事件；M4+ 隐藏小震；时间着色按事件时间上色。统计始终使用全量目录。"],
  ["报告复杂度", "最简为默认模板；中等保留正文和分布图；完整会加入更多统计表和扩展分析。"],
  ["内网/本地目录", "设置中开启后，服务端优先使用本地 SQLite 目录；本地目录不可用时自动回到 USGS。"],
];

const notes = [
  ["统计口径", "事件数量、震级分布和代表性事件以 USGS FDSN 为准。EMSC 只做辅助核对，不并入统计。"],
  ["地图点数", "图上会标出“图面点数 / 统计全量点数”。地图模式只影响显示，不改统计结果。"],
  ["CSV 目录", "生成报告时会同步导出目录 CSV。dist_km 为数字列，便于在 WPS 或 Excel 中按距离排序。"],
  ["Mc 提示", "Mc 是目录完整性震级的近似提示，用来提醒早期小震可能不完整，不是严格研究结论。"],
  ["国内边界", "中国区域使用国内官方边界数据。缺少边界数据时，系统不会用非官方国界线替代。"],
];

const problems = [
  ["生成很慢", "先看预计目录数量。上万条会慢，可提高最小震级或缩小半径。"],
  ["没有 PDF", "PDF 是按需转换。先生成报告，再点击「下载 PDF」。"],
  ["搜索不到事件", "换 Event ID 或减少关键词。地区关键词基于 USGS 返回候选筛选，地名写法可能不同。"],
  ["文本信息不全", "系统会尽量按已提取的信息查候选。一个候选都没有时，补全表单后仍可按当前输入生成。"],
  ["候选看起来不一致", "中文地点不会作为硬过滤；有经纬度时优先按震中位置、震级和时间匹配 USGS 事件。"],
  ["报告里 EMSC 不可用", "这不影响主统计。USGS 仍是主目录，EMSC 只是辅助核对。"],
];

const bulletinExamples = [
  "中国地震台网正式测定：06月25日06时30分，在日本本州东部附近海域(北纬40.20度，东经142.40度)发生6.9级地震，震源深度50公里。",
  "中国地震台网正式测定：12月06日02时44分，在美国加利福尼亚州北部沿岸近海(北纬40.40度，西经125.00度)发生7.0级地震，震源深度10公里。",
];

export default function GuidePage() {
  return (
    <main className="min-h-screen bg-[#f7f1e8] text-[#2d241c]">
      <header className="sticky top-0 z-20 border-b border-[#ded4c6] bg-[#fbf7ef]/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <Link href="/" className="flex min-w-0 items-center gap-2 sm:gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#2d241c]">
              <Activity className="h-5 w-5 text-[#fff8ee]" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold">使用教程</h1>
              <p className="hidden truncate text-xs text-[#76695d] sm:block">地震活动报告生成器 · © 2026 周浩宇</p>
            </div>
          </Link>
          <Link
            href="/"
            className="inline-flex h-9 shrink-0 items-center gap-1 whitespace-nowrap rounded-md border border-[#ded4c6] bg-[#fffaf2] px-3 text-xs font-medium hover:bg-[#f5ecdf]"
          >
            <ArrowLeft className="h-3.5 w-3.5 shrink-0" />
            返回生成器
          </Link>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-4 py-5">
        <div className="mb-4 rounded-xl border border-[#ded4c6] bg-[#fffaf2] p-5">
          <h2 className="text-xl font-semibold">推荐生成流程</h2>
          <p className="mt-2 text-sm leading-6 text-[#5a4b3f]">
            目标是快速产出可复核的历史地震活动报告。先确认事件，再确认目录范围，最后下载 Word、PDF 和目录 CSV。
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
          <div className="space-y-4">
            <Panel icon={<CheckCircle2 className="h-4 w-4" />} title="基本流程">
              <div className="grid gap-3 sm:grid-cols-2">
                {quickStart.map(([title, body]) => (
                  <CardItem key={title} title={title} body={body} />
                ))}
              </div>
            </Panel>

            <Panel icon={<MapPin className="h-4 w-4" />} title="事件怎么填">
              <div className="grid gap-3 sm:grid-cols-2">
                {inputModes.map(([title, body]) => (
                  <CardItem key={title} title={title} body={body} />
                ))}
              </div>
            </Panel>

            <Panel icon={<Search className="h-4 w-4" />} title="测定文本和候选确认">
              <div className="space-y-3">
                <p className="text-sm leading-6 text-[#5a4b3f]">
                  粘贴测定文本后，系统会自动写入表单。原文缺年份或字段不全时，会按已提取的震中、震级、时间和地点查候选事件；确认候选后用 Event ID 生成。
                </p>
                <div className="space-y-2">
                  {bulletinExamples.map((example) => (
                    <code key={example} className="block whitespace-pre-wrap break-words rounded-md border border-[#ded4c6] bg-[#fffdf8] px-3 py-2 text-xs leading-5">
                      {example}
                    </code>
                  ))}
                </div>
              </div>
            </Panel>

            <Panel icon={<Settings className="h-4 w-4" />} title="参数怎么理解">
              <div className="divide-y divide-[#ded4c6] rounded-lg border border-[#ded4c6] bg-[#fffdf8]">
                {params.map(([title, body]) => (
                  <Row key={title} title={title} body={body} />
                ))}
              </div>
            </Panel>

            <Panel icon={<FileText className="h-4 w-4" />} title="报告结果怎么看">
              <div className="grid gap-3 sm:grid-cols-2">
                {notes.map(([title, body]) => (
                  <CardItem key={title} title={title} body={body} />
                ))}
              </div>
            </Panel>
          </div>

          <aside className="space-y-4">
            <Panel icon={<Search className="h-4 w-4" />} title="搜索示例">
              <div className="space-y-2">
                {searchExamples.map((example) => (
                  <code key={example} className="block rounded-md border border-[#ded4c6] bg-[#fffdf8] px-3 py-2 text-sm">
                    {example}
                  </code>
                ))}
              </div>
            </Panel>

            <Panel icon={<Clock className="h-4 w-4" />} title="时间和坐标">
              <p className="text-sm leading-6 text-[#5a4b3f]">
                手动输入时，发震时间填 UTC，例如 2026-06-25T14:17:00Z。纬度北纬为正、南纬为负；经度东经为正、西经为负。
              </p>
            </Panel>

            <Panel icon={<Download className="h-4 w-4" />} title="下载顺序">
              <p className="text-sm leading-6 text-[#5a4b3f]">
                生成完成后先下载 Word。PDF 不会提前生成，点击「下载 PDF」后才转换，这样页面不会因为 PDF 卡住。
              </p>
            </Panel>

            <Panel icon={<AlertCircle className="h-4 w-4" />} title="常见问题">
              <div className="space-y-3">
                {problems.map(([title, body]) => (
                  <CardItem key={title} title={title} body={body} />
                ))}
              </div>
            </Panel>
          </aside>
        </div>
      </section>
    </main>
  );
}

function Panel({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="min-w-0 rounded-xl border border-[#ded4c6] bg-[#fffaf2] p-4">
      <h2 className="mb-3 flex min-w-0 items-center gap-2 text-base font-semibold">
        {icon}
        {title}
      </h2>
      {children}
    </section>
  );
}

function CardItem({ title, body }: { title: string; body: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-[#ded4c6] bg-[#fffdf8] p-3">
      <div className="mb-1 text-sm font-semibold">{title}</div>
      <p className="break-words text-sm leading-6 text-[#5a4b3f]">{body}</p>
    </div>
  );
}

function Row({ title, body }: { title: string; body: string }) {
  return (
    <div className="grid min-w-0 gap-1 p-3 sm:grid-cols-[140px_1fr]">
      <div className="text-sm font-semibold">{title}</div>
      <p className="break-words text-sm leading-6 text-[#5a4b3f]">{body}</p>
    </div>
  );
}
