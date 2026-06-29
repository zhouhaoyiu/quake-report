"use client";

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  Globe2,
  MapPin,
  Clock,
  Activity,
  Download,
  FileText,
  Image as ImageIcon,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Search,
  Zap,
  Layers,
  Calendar,
  Moon,
  Sun,
  RotateCcw,
  BookOpen,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Mode = "manual" | "eventid" | "recent";
type SourcePanel = "catalog" | "input";
type MapView = "mag" | "m4" | "time";
type TimezoneMode = "utc" | "utc8" | "both";

interface SavedSettings {
  radiusKm: string;
  minMag: string;
  figNum: string;
  noPdf: boolean;
  noExtended: boolean;
  tz: TimezoneMode;
  mapView: MapView;
  darkMode: boolean;
}

const SETTINGS_KEY = "quake-report-settings-v1";
const DEFAULT_SETTINGS: SavedSettings = {
  radiusKm: "200",
  minMag: "3.0",
  figNum: "1",
  noPdf: false,
  noExtended: false,
  tz: "utc8",
  mapView: "mag",
  darkMode: false,
};

const MAP_VIEW_OPTIONS: [MapView, string][] = [
  ["mag", "全量点"],
  ["m4", "M4+"],
  ["time", "时间着色"],
];

function readSavedSettings(): SavedSettings & { ready: boolean } {
  if (typeof window === "undefined") return { ...DEFAULT_SETTINGS, ready: false };

  try {
    const saved = window.localStorage.getItem(SETTINGS_KEY);
    if (!saved) return { ...DEFAULT_SETTINGS, ready: true };
    const data = JSON.parse(saved);
    return {
      radiusKm: data.radiusKm ? String(data.radiusKm) : DEFAULT_SETTINGS.radiusKm,
      minMag: data.minMag ? String(data.minMag) : DEFAULT_SETTINGS.minMag,
      figNum: data.figNum ? String(data.figNum) : DEFAULT_SETTINGS.figNum,
      noPdf: typeof data.noPdf === "boolean" ? data.noPdf : DEFAULT_SETTINGS.noPdf,
      noExtended: typeof data.noExtended === "boolean" ? data.noExtended : DEFAULT_SETTINGS.noExtended,
      tz: data.tz === "utc" || data.tz === "utc8" || data.tz === "both" ? data.tz : DEFAULT_SETTINGS.tz,
      mapView:
        data.mapView === "mag" || data.mapView === "m4" || data.mapView === "time"
          ? data.mapView
          : DEFAULT_SETTINGS.mapView,
      darkMode: typeof data.darkMode === "boolean" ? data.darkMode : DEFAULT_SETTINGS.darkMode,
      ready: true,
    };
  } catch {
    return { ...DEFAULT_SETTINGS, ready: true };
  }
}

interface GenResult {
  ok: boolean;
  files?: { map: string | null; catalog?: string | null; docx: string | null; pdf: string | null };
  fileNames?: { map: string | null; catalog?: string | null; docx: string | null; pdf: string | null };
  fileRefs?: {
    map?: ReportFileRef | null;
    catalog?: ReportFileRef | null;
    docx?: ReportFileRef | null;
    pdf?: ReportFileRef | null;
  };
  mainshock?: any;
  stats?: any;
  mapMeta?: { view: MapView; display_count: number; total_count: number };
  warnings?: string[];
  canPdf?: boolean;
  cacheHit?: boolean;
  note?: string;
  error?: string;
}

interface ReportFileRef {
  id: string;
  fileName: string;
  mime: string;
  size: number;
  url: string;
  downloadUrl: string;
}

interface RecentEvent {
  eventId: string;
  time: string;
  latitude: number;
  longitude: number;
  depth: number;
  mag: number;
  magType: string;
  place: string;
}

interface CatalogStatus {
  ok: boolean;
  rows?: number;
  lastSyncUtc?: string;
  lastEventTime?: string;
  minMagnitude?: number;
}

export default function Home() {
  const { toast } = useToast();
  const [initialSettings] = useState(readSavedSettings);
  const [mode, setMode] = useState<Mode>("manual");
  const [sourcePanel, setSourcePanel] = useState<SourcePanel>("input");

  // manual 模式参数
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [mag, setMag] = useState("");
  const [time, setTime] = useState("");
  const [depth, setDepth] = useState("10");
  const [place, setPlace] = useState("");
  const [magType, setMagType] = useState("Mw");

  // eventid 模式
  const [eventId, setEventId] = useState("");

  // recent 模式
  const [recentEvents, setRecentEvents] = useState<RecentEvent[]>([]);
  const [recentLoading, setRecentLoading] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string>("");
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogSearchQuery, setCatalogSearchQuery] = useState("");
  const [catalogSearchLoading, setCatalogSearchLoading] = useState(false);
  const [catalogSearchResults, setCatalogSearchResults] = useState<RecentEvent[]>([]);
  const [catalogSearchError, setCatalogSearchError] = useState("");
  const [catalogSearchPage, setCatalogSearchPage] = useState(1);
  const [catalogPageInput, setCatalogPageInput] = useState("1");
  const [catalogSearchTotal, setCatalogSearchTotal] = useState(0);
  const [catalogSearchNote, setCatalogSearchNote] = useState("");
  const [selectedCatalogEvent, setSelectedCatalogEvent] = useState<RecentEvent | null>(null);

  // 通用查询参数
  const [radiusKm, setRadiusKm] = useState(initialSettings.radiusKm);
  const [minMag, setMinMag] = useState(initialSettings.minMag);
  const [figNum, setFigNum] = useState(initialSettings.figNum);
  const [slug, setSlug] = useState("");
  const [noPdf, setNoPdf] = useState(initialSettings.noPdf);
  const [noExtended, setNoExtended] = useState(initialSettings.noExtended);
  const [tz, setTz] = useState<TimezoneMode>(initialSettings.tz);
  const [mapView, setMapView] = useState<MapView>(initialSettings.mapView);

  // 生成状态
  const [loading, setLoading] = useState(false);
  const [countLoading, setCountLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("正在从 USGS 拉取地震目录...");
  const [catalogCount, setCatalogCount] = useState<number | null>(null);
  const [progress, setProgress] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [generationStep, setGenerationStep] = useState<{ step?: number; total?: number; queuePosition?: number }>({});
  const [mapPreview, setMapPreview] = useState<{ url: string; fileName?: string; meta?: GenResult["mapMeta"] } | null>(null);
  const [cacheNote, setCacheNote] = useState("");
  const [result, setResult] = useState<GenResult | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfStatus, setPdfStatus] = useState("");
  const [darkMode, setDarkMode] = useState(initialSettings.darkMode);
  const [settingsReady, setSettingsReady] = useState(initialSettings.ready);
  const [catalogStatus, setCatalogStatus] = useState<CatalogStatus | null>(null);
  const lastGenerateRef = useRef<{ key: string; result: GenResult; count: number | null; expires: number } | null>(null);
  const selectedRecentEvent = useMemo(
    () => recentEvents.find((item) => item.eventId === selectedEventId),
    [recentEvents, selectedEventId]
  );
  const selectedCatalogMatches = useMemo(
    () => selectedCatalogEvent?.eventId === eventId.trim(),
    [selectedCatalogEvent, eventId]
  );
  const queuedEvent = useMemo(
    () => (mode === "recent" ? selectedRecentEvent : mode === "eventid" && selectedCatalogMatches ? selectedCatalogEvent : null),
    [mode, selectedRecentEvent, selectedCatalogMatches, selectedCatalogEvent]
  );
  const queuedEventLabel = mode === "recent" ? "最新" : "目录";
  const mapViewLabel = mapView === "m4" ? "隐藏 M3-M4" : mapView === "time" ? "按时间着色" : "全量按震级";
  const tzLabel = tz === "utc8" ? "北京时间" : tz === "both" ? "UTC+北京时间" : "UTC";
  const catalogPageSize = 10;
  const catalogPageCount = Math.max(1, Math.ceil(catalogSearchTotal / catalogPageSize));
  const safeCatalogPage = Math.min(catalogSearchPage, catalogPageCount);
  const catalogResultStart = catalogSearchResults.length ? (safeCatalogPage - 1) * catalogPageSize + 1 : 0;
  const catalogResultEnd = catalogResultStart + catalogSearchResults.length - 1;
  const catalogPageNumbers = useMemo(() => {
    const start = Math.max(1, Math.min(safeCatalogPage - 2, catalogPageCount - 4));
    return Array.from({ length: Math.min(5, catalogPageCount) }, (_, index) => start + index);
  }, [safeCatalogPage, catalogPageCount]);
  const defaultSlugPlaceholder = useMemo(() => {
    const yyyymm = (value: string) => {
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return "YYYYMM";
      return `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
    };

    if (mode === "manual") {
      const la = Number(lat);
      const lo = Number(lon);
      const m = Number(mag);
      if (time && Number.isFinite(la) && Number.isFinite(lo) && Number.isFinite(m)) {
        return `${yyyymm(time)}_M${m.toFixed(1)}_${la.toFixed(2)}_${lo.toFixed(2)}`;
      }
      return "YYYYMM_M震级_纬度_经度";
    }

    if (mode === "recent" && selectedRecentEvent) {
      return `${yyyymm(selectedRecentEvent.time)}_${selectedRecentEvent.eventId}_M${selectedRecentEvent.mag.toFixed(1)}`;
    }

    if (mode === "eventid" && selectedCatalogMatches && selectedCatalogEvent) {
      return `${yyyymm(selectedCatalogEvent.time)}_${selectedCatalogEvent.eventId}_M${selectedCatalogEvent.mag.toFixed(1)}`;
    }

    return eventId.trim() ? `YYYYMM_${eventId.trim()}_M震级` : "YYYYMM_eventid_M震级";
  }, [mode, lat, lon, mag, time, selectedRecentEvent, selectedCatalogMatches, selectedCatalogEvent, eventId]);
  const catalogSearchChips = useMemo(
    () => catalogSearchQuery.trim().split(/\s+/).filter(Boolean).slice(0, 8),
    [catalogSearchQuery]
  );

  useLayoutEffect(() => {
    if (!settingsReady) setSettingsReady(true);
  }, [settingsReady]);

  useEffect(() => {
    if (!settingsReady) return;
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ radiusKm, minMag, figNum, tz, mapView, noPdf, noExtended, darkMode })
    );
  }, [settingsReady, radiusKm, minMag, figNum, tz, mapView, noPdf, noExtended, darkMode]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
    return () => document.documentElement.classList.remove("dark");
  }, [darkMode]);

  useEffect(() => {
    setCatalogPageInput(String(safeCatalogPage));
  }, [safeCatalogPage]);

  useEffect(() => {
    fetch("/api/quake/catalog-status")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.ok) setCatalogStatus(data);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const q = catalogSearchQuery.trim();
    if (q.length < 2) {
      setCatalogSearchLoading(false);
      setCatalogSearchResults([]);
      setCatalogSearchError("");
      setCatalogSearchTotal(0);
      setCatalogSearchNote("");
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setCatalogSearchLoading(true);
      setCatalogSearchError("");
      try {
        const r = await fetch(`/api/quake/search?q=${encodeURIComponent(q)}&page=${catalogSearchPage}`, {
          signal: controller.signal,
        });
        const j = await r.json();
        if (!j.ok) throw new Error(j.error || "搜索失败");
        setCatalogSearchResults(j.events || []);
        setCatalogSearchTotal(j.total || 0);
        setCatalogSearchNote(j.note || "");
      } catch (e: any) {
        if (e?.name !== "AbortError") {
          setCatalogSearchError(e?.message || String(e));
          setCatalogSearchResults([]);
          setCatalogSearchTotal(0);
          setCatalogSearchNote("");
        }
      } finally {
        if (!controller.signal.aborted) {
          setCatalogSearchLoading(false);
        }
      }
    }, 450);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [catalogSearchQuery, catalogSearchPage]);

  const submitCatalogSearch = useCallback(() => {
    setCatalogSearchPage(1);
    setCatalogSearchQuery(catalogSearch);
  }, [catalogSearch]);

  const jumpCatalogPage = useCallback(() => {
    const page = Math.floor(Number(catalogPageInput));
    if (!Number.isFinite(page)) return;
    setCatalogSearchPage(Math.min(catalogPageCount, Math.max(1, page)));
  }, [catalogPageInput, catalogPageCount]);

  const resetGeneratedResult = useCallback(() => {
    setResult(null);
    setCatalogCount(null);
    setProgress(0);
    setElapsedSec(0);
    setGenerationStep({});
    setMapPreview(null);
    setCacheNote("");
  }, []);

  const handleModeChange = useCallback((value: string) => {
    setMode(value as Mode);
    resetGeneratedResult();
  }, [resetGeneratedResult]);

  const chooseRecentEvent = useCallback((ev: RecentEvent) => {
    setSelectedEventId(ev.eventId);
    setSelectedCatalogEvent(null);
    resetGeneratedResult();
  }, [resetGeneratedResult]);

  const chooseCatalogSearchEvent = useCallback((ev: RecentEvent) => {
    setSourcePanel("input");
    setMode("eventid");
    setEventId(ev.eventId);
    setSelectedEventId("");
    setSelectedCatalogEvent(ev);
    resetGeneratedResult();
    toast({
      title: "已填入事件",
      description: `Event ID：${ev.eventId}`,
    });
  }, [resetGeneratedResult, toast]);

  function resetSettings() {
    setRadiusKm("200");
    setMinMag("3.0");
    setFigNum("1");
    setNoPdf(false);
    setNoExtended(false);
    setTz("utc8");
    setMapView("mag");
    setDarkMode(false);
    setCatalogCount(null);
    localStorage.removeItem(SETTINGS_KEY);
    toast({ title: "已恢复默认配置" });
  }

  function buildRequestBody() {
    const body: any = {
      mode,
      radiusKm: Number(radiusKm),
      minMag: Number(minMag),
      figNum,
      slug: slug || undefined,
      noPdf,
      noExtended,
      tz,
      mapView,
    };

    if (mode === "manual") {
      if (!lat || !lon || !mag || !time) {
        toast({
          variant: "destructive",
          title: "参数不全",
          description: "请填写纬度、经度、震级、发震时间",
        });
        return null;
      }
      body.lat = Number(lat);
      body.lon = Number(lon);
      body.mag = Number(mag);
      body.time = time;
      if (depth) body.depth = Number(depth);
      if (place) body.place = place;
      if (magType) body.magType = magType;
    } else if (mode === "eventid") {
      if (!eventId) {
        toast({
          variant: "destructive",
          title: "缺少 eventid",
          description: "请填写 USGS eventid",
        });
        return null;
      }
      body.eventId = eventId;
    } else if (mode === "recent") {
      if (!selectedEventId) {
        toast({
          variant: "destructive",
          title: "未选择事件",
          description: "请先加载并选择一个近期事件",
        });
        return null;
      }
      body.mode = "eventid";
      body.eventId = selectedEventId;
    }

    return body;
  }

  async function estimateCatalogCount() {
    const body = buildRequestBody();
    if (!body) return;
    setCountLoading(true);
    setCatalogCount(null);
    try {
      const cr = await fetch("/api/quake/count", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const cj = await cr.json();
      if (!cj.ok || typeof cj.count !== "number") throw new Error(cj.error || "预估失败");
      setCatalogCount(cj.count);
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: "预估失败",
        description: publicError(e?.message || String(e)),
      });
    } finally {
      setCountLoading(false);
    }
  }

  // ---- 加载近 30 天大震 ----
  async function loadRecentEvents() {
    setRecentLoading(true);
    try {
      const r = await fetch("/api/quake/recent?days=30&minMag=6.0&limit=30");
      const j = await r.json();
      if (j.ok) {
        setRecentEvents(j.events);
        if (j.events.length > 0) {
          const latest = j.events.reduce((a: RecentEvent, b: RecentEvent) =>
            Date.parse(a.time) > Date.parse(b.time) ? a : b
          );
          chooseRecentEvent(latest);
          toast({
            title: `找到 ${j.events.length} 个事件`,
            description: `已自动选取最新事件：M${latest.mag} ${latest.place}${j.cacheHit ? "（缓存）" : ""}`,
          });
        }
      } else {
        toast({
          variant: "destructive",
          title: "拉取失败",
          description: publicError(j.error || "未知错误"),
        });
      }
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: "拉取失败",
        description: publicError(e?.message || String(e)),
      });
    } finally {
      setRecentLoading(false);
    }
  }

  // ---- 生成报告 ----
  async function generate() {
    if (loading) {
      toast({ title: "正在生成", description: "当前任务尚未完成，请稍候" });
      return;
    }
    const body = buildRequestBody();
    if (!body) return;
    const requestKey = JSON.stringify(body);
    const now = Date.now();
    const cached = lastGenerateRef.current;
    if (cached?.key === requestKey && cached.expires > now) {
      setResult(cached.result);
      setCatalogCount(cached.count);
      setMapPreview(null);
      setCacheNote("参数未变，已复用最近一次生成结果");
      toast({ title: "已复用结果", description: "参数未变化，可直接下载" });
      return;
    }
    setLoading(true);
    setResult(null);
    setCatalogCount(null);
    setMapPreview(null);
    setCacheNote("");
    setElapsedSec(0);
    setGenerationStep({});
    setProgress(3);
    setLoadingMessage("正在估算目录事件数量...");
    try {
      try {
        const cr = await fetch("/api/quake/count", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const cj = await cr.json();
        if (cj.ok && typeof cj.count === "number") {
          if (cj.count > 30000) {
            const ok = window.confirm(
              `预计目录事件 ${cj.count.toLocaleString()} 条，出图和报告会明显变慢。是否继续生成？`
            );
            if (!ok) {
              setLoading(false);
              setProgress(0);
              return;
            }
          }
          setCatalogCount(cj.count);
          setCacheNote(cj.cacheHit ? "USGS 数量预估来自缓存" : "USGS 数量预估已刷新");
          setProgress(10);
          setLoadingMessage(`预计目录事件 ${cj.count.toLocaleString()} 条，正在生成全量图和报告...`);
        } else {
          setLoadingMessage("正在生成全量图和报告...");
        }
      } catch {
        setLoadingMessage("正在生成全量图和报告...");
      }

      const r = await fetch("/api/quake/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, stream: true }),
      });
      const j = await readGenerateStream(r);
      setResult(j);
      if (j.ok) {
        setProgress(100);
        lastGenerateRef.current = {
          key: requestKey,
          result: j,
          count: catalogCount ?? j.stats?.total_count ?? j.stats?.n3 ?? null,
          expires: Date.now() + 10 * 60_000,
        };
        toast({
          title: j.cacheHit ? "已复用结果" : "生成成功",
          description: j.cacheHit ? "参数未变化，可直接下载" : "报告与图件已生成，可下载",
        });
      } else {
        toast({
          variant: "destructive",
          title: "生成失败",
          description: publicError(j.error),
        });
      }
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: "请求失败",
        description: publicError(e?.message || String(e)),
      });
    } finally {
      setLoading(false);
    }
  }

  async function readGenerateStream(r: Response): Promise<GenResult> {
    const contentType = r.headers.get("content-type") || "";
    if (!r.body || !contentType.includes("application/x-ndjson")) {
      return await r.json();
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const raw of lines) {
        if (!raw.trim()) continue;
        const event = JSON.parse(raw);
        if (typeof event.progress === "number") {
          setProgress(Math.max(10, event.progress));
        }
        if (typeof event.elapsedSec === "number") {
          setElapsedSec(event.elapsedSec);
        }
        if (typeof event.queuePosition === "number") {
          setGenerationStep((prev) => ({ ...prev, queuePosition: event.queuePosition }));
        }
        if (typeof event.step === "number" || typeof event.total === "number") {
          setGenerationStep((prev) => ({ ...prev, step: event.step, total: event.total }));
        }
        if (event.message) {
          setLoadingMessage(event.message);
        }
        if (event.type === "map_preview" && event.map) {
          setMapPreview({ url: event.map, fileName: event.fileName });
        }
        if (event.type === "done") {
          return event.result;
        }
      }
    }

    return { ok: false, error: "生成中断：未收到完成状态" };
  }

  function downloadDataUrl(dataUrl: string, fileName: string) {
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function downloadBlob(blob: Blob, fileName: string) {
    const url = URL.createObjectURL(blob);
    downloadDataUrl(url, fileName);
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  async function downloadReportFile(url: string | null | undefined, fileName: string, title: string) {
    if (!url) return;
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || "文件已过期，请重新生成报告");
      }
      downloadBlob(await r.blob(), fileName);
    } catch (e: any) {
      toast({
        variant: "destructive",
        title,
        description: publicError(e?.message || String(e)),
      });
    }
  }

  async function downloadPdf() {
    if (!result?.files?.docx) return;
    if (result.files.pdf) {
      await downloadReportFile(result.files.pdf, result.fileNames?.pdf || "report.pdf", "PDF 下载失败");
      return;
    }
    setPdfLoading(true);
    setPdfStatus("正在启动 PDF 转换...");
    try {
      const r = await fetch("/api/quake/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docxFileId: result.fileRefs?.docx?.id,
          docxDataUrl: result.fileRefs?.docx?.id ? undefined : result.files.docx,
          fileName: result.fileNames?.docx || "report.docx",
        }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || "PDF 转换失败");
      }
      setPdfStatus("PDF 已生成，正在下载...");
      const blob = await r.blob();
      const fileName = (result.fileNames?.docx || "report.docx").replace(/\.docx$/i, ".pdf");
      const objectUrl = URL.createObjectURL(blob);
      setResult((prev) => prev ? {
        ...prev,
        files: {
          map: prev.files?.map || null,
          catalog: prev.files?.catalog || null,
          docx: prev.files?.docx || null,
          pdf: objectUrl,
        },
        fileNames: {
          map: prev.fileNames?.map || null,
          catalog: prev.fileNames?.catalog || null,
          docx: prev.fileNames?.docx || null,
          pdf: fileName,
        },
      } : prev);
      downloadBlob(blob, fileName);
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: "PDF 转换失败",
        description: publicError(e?.message || String(e)),
      });
    } finally {
      setPdfLoading(false);
      setPdfStatus("");
    }
  }

  function publicError(message?: string) {
    if (!message) return "生成失败，请检查输入参数或稍后重试";
    const internalErrorPatterns = [
      /(?:^|\s)\/(?:[\w.-]+\/){1,}[\w.-]+/,
      /Traceback|File "|line \d+|column \d+|char \d+/i,
      /\bstdout\b|\bstderr\b|\.py\b/i,
      /ModuleNotFoundError|No module named|JSONDecodeError|SyntaxError/i,
    ];
    if (internalErrorPatterns.some((pattern) => pattern.test(message))) {
      return "生成失败，请检查输入参数、网络连接或稍后重试";
    }
    return message;
  }

  function formatSeconds(value: number) {
    if (!Number.isFinite(value) || value <= 0) return "0s";
    if (value < 60) return `${value.toFixed(1)}s`;
    const min = Math.floor(value / 60);
    const sec = Math.round(value % 60);
    return `${min}m ${sec}s`;
  }

  function formatSyncTime(value?: string) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function catalogStatusTitle(status: CatalogStatus) {
    return [
      `最近同步：${formatSyncTime(status.lastSyncUtc) || "未知"}`,
      `现有事件：${status.rows == null ? "未知" : `${status.rows.toLocaleString()} 条`}`,
      `目录下限：M≥${status.minMagnitude ?? 3}`,
      `最新事件：${status.lastEventTime || "未知"}`,
      "官方同步：USGS FDSN Event Web Service",
      "https://earthquake.usgs.gov/fdsnws/event/1/query",
    ].join("\n");
  }

  const generationControls = (
    <div className="mb-3 rounded-xl border border-[#ded4c6] bg-[#fffdf8] p-3 text-left dark:border-[#3a332c] dark:bg-[#1c1814]">
      {queuedEvent && (
        <div className="mb-2 rounded-lg border border-[#ded4c6] bg-[#fffaf2] px-3 py-2 dark:border-[#3a332c] dark:bg-[#211c17]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[#76695d] dark:text-[#b7aa9b]">当前选中</span>
            <span className="font-medium text-[#2d241c] dark:text-[#f4eee5]">
              M{queuedEvent.mag.toFixed(1)} {queuedEvent.place}
            </span>
            <Badge variant="outline" className="h-5 bg-[#2d241c] text-[#fff8ee] border-[#2d241c] dark:bg-[#f4eee5] dark:text-[#171411] dark:border-[#f4eee5]">
              {queuedEventLabel}
            </Badge>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-[#76695d] dark:text-[#b7aa9b]">
            <span>{queuedEvent.time.slice(0, 16).replace("T", " ")}</span>
            <span>{queuedEvent.latitude.toFixed(2)}°, {queuedEvent.longitude.toFixed(2)}°</span>
            <span>{queuedEvent.depth.toFixed(1)} km</span>
          </div>
        </div>
      )}

      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#2d241c] dark:text-[#f4eee5]">
        <Globe2 className="w-4 h-4 text-[#5a4b3f] dark:text-[#d8cbbb]" />
        查询与输出参数
      </div>
      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-[110px_96px_96px_minmax(240px,1fr)_170px]">
        <div className="w-28">
          <Label htmlFor="radius" className="text-xs">查询半径 km</Label>
          <Input id="radius" className="h-8" placeholder="200" value={radiusKm} onChange={(e) => setRadiusKm(e.target.value)} />
        </div>
        <div className="w-24">
          <Label htmlFor="minMag" className="text-xs">最小震级</Label>
          <Input id="minMag" className="h-8" placeholder="3.0" value={minMag} onChange={(e) => setMinMag(e.target.value)} />
        </div>
        <div className="w-24">
          <Label htmlFor="figNum" className="text-xs">图编号</Label>
          <Input id="figNum" className="h-8" placeholder="1" value={figNum} onChange={(e) => setFigNum(e.target.value)} />
        </div>
        <div className="min-w-[260px] flex-1">
          <Label htmlFor="slug" className="text-xs">输出文件名 (不含扩展名)</Label>
          <Input id="slug" className="h-8" placeholder={defaultSlugPlaceholder} value={slug} onChange={(e) => setSlug(e.target.value)} />
        </div>
        <div className="w-44">
          <Label htmlFor="tz" className="text-xs flex items-center gap-1">
            <Clock className="w-3 h-3" />
            时间显示时区
          </Label>
          <Select value={tz} onValueChange={(v) => setTz(v as typeof tz)}>
            <SelectTrigger id="tz" className="h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="utc8">北京时间 (UTC+8)</SelectItem>
              <SelectItem value="utc">UTC</SelectItem>
              <SelectItem value="both">同时显示 UTC 与北京时间</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div className="min-w-[260px] flex-1">
          <Label htmlFor="mapView" className="text-xs">地图显示</Label>
          <div id="mapView" className="grid h-8 grid-cols-3 rounded-md bg-[#efe6d8] p-0.5 text-xs dark:bg-[#2b251f]">
            {MAP_VIEW_OPTIONS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setMapView(value)}
                className={`rounded px-2 transition ${mapView === value ? "bg-[#2d241c] text-[#fff8ee] shadow-sm dark:bg-[#f4eee5] dark:text-[#171411]" : "text-[#6f6256] hover:bg-[#fffaf2] dark:text-[#b7aa9b] dark:hover:bg-[#211c17]"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex h-8 min-w-[132px] items-center justify-between gap-2 rounded-md border border-[#ded4c6] bg-[#fffaf2] px-3 dark:border-[#3a332c] dark:bg-[#211c17]">
            <Label htmlFor="noPdf" className="text-xs">跳过 PDF</Label>
            <Switch id="noPdf" checked={noPdf} onCheckedChange={setNoPdf} />
        </div>
        <div className="flex h-8 min-w-[220px] items-center justify-between gap-2 rounded-md border border-[#ded4c6] bg-[#fffaf2] px-3 dark:border-[#3a332c] dark:bg-[#211c17]">
            <Label htmlFor="noExtended" className="text-xs">简版报告</Label>
            <Switch id="noExtended" checked={noExtended} onCheckedChange={setNoExtended} />
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8"
          onClick={estimateCatalogCount}
          disabled={countLoading || loading}
        >
          {countLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          预估数量
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-8"
          onClick={resetSettings}
          disabled={loading}
        >
          <RotateCcw className="w-4 h-4" />
          默认
        </Button>
        <Button
          className="h-8 min-w-[150px] flex-1 bg-[#2d241c] text-sm font-semibold text-[#fff8ee] hover:bg-[#3a2d23] sm:flex-none dark:bg-[#f4eee5] dark:text-[#171411] dark:hover:bg-white"
          onClick={generate}
          disabled={loading}
        >
          <Zap className="w-4 h-4 mr-2" />
          生成报告
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 rounded-md bg-[#fffaf2] px-2 py-1.5 text-xs text-[#76695d] dark:bg-[#211c17] dark:text-[#b7aa9b]">
        <span className="font-medium text-[#5a4b3f] dark:text-[#d8cbbb]">当前配置</span>
        <span>半径 {radiusKm || "-"} km</span>
        <span>M≥{minMag || "-"}</span>
        <span>地图：{mapViewLabel}</span>
        <span>{noPdf ? "跳过 PDF" : "生成 PDF"}</span>
        <span>时区：{tzLabel}</span>
        <span>目录量：{catalogCount == null ? "未预估" : `${catalogCount.toLocaleString()} 条`}</span>
      </div>
      <p className="mt-1 text-xs text-[#76695d] dark:text-[#b7aa9b]">
        图编号用于报告图题；地图显示只影响图面表达，统计和表格仍使用完整目录。
      </p>
    </div>
  );

  return (
    <div className={`${darkMode ? "dark" : ""} min-h-screen pb-20 lg:h-screen lg:overflow-hidden lg:pb-0 flex flex-col bg-[#f7f1e8] text-[#2d241c] dark:bg-[#171411] dark:text-[#f4eee5]`}>
      {/* ===== Header ===== */}
      <header className="border-b border-[#ded4c6] bg-[#fbf7ef]/95 backdrop-blur sticky top-0 z-30 dark:border-[#3a332c] dark:bg-[#171411]/95">
        <div className="max-w-[1680px] mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[#2d241c] flex items-center justify-center dark:bg-[#f4eee5]">
              <Activity className="w-5 h-5 text-[#fff8ee] dark:text-[#171411]" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-[#2d241c] dark:text-[#f4eee5]">
                地震活动报告生成器
              </h1>
              <p className="text-xs text-[#76695d] dark:text-[#b7aa9b]">
                多源目录核对 · 活动断层背景 · Word/PDF 输出
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/guide"
              className="inline-flex h-9 items-center gap-1 rounded-md border border-[#ded4c6] bg-[#fffaf2] px-3 text-xs font-medium text-[#4f4237] hover:bg-[#f5ecdf] dark:border-[#3a332c] dark:bg-[#211c17] dark:text-[#e8ddcf] dark:hover:bg-[#2b251f]"
            >
              <BookOpen className="h-3.5 w-3.5" />
              使用教程
            </Link>
            <span className="hidden xl:inline text-xs text-[#76695d] dark:text-[#b7aa9b]">
              © 2026 周浩宇
            </span>
            <div className="hidden md:flex items-center gap-2">
              {catalogStatus?.lastSyncUtc && (
                <Badge
                  variant="outline"
                  title={catalogStatusTitle(catalogStatus)}
                  className="bg-[#fffaf2] text-[#4f4237] border-[#ded4c6] dark:bg-[#211c17] dark:text-[#e8ddcf] dark:border-[#3a332c]"
                >
                  <Clock className="w-3 h-3 mr-1" />
                  目录同步 {formatSyncTime(catalogStatus.lastSyncUtc)}
                </Badge>
              )}
              <Badge variant="outline" className="bg-[#fffaf2] text-[#4f4237] border-[#ded4c6] dark:bg-[#211c17] dark:text-[#e8ddcf] dark:border-[#3a332c]">
                <Calendar className="w-3 h-3 mr-1" />
                USGS FDSN
              </Badge>
              <Badge variant="outline" className="bg-[#fffaf2] text-[#4f4237] border-[#ded4c6] dark:bg-[#211c17] dark:text-[#e8ddcf] dark:border-[#3a332c]">
                <Globe2 className="w-3 h-3 mr-1" />
                EMSC
              </Badge>
              <Badge variant="outline" className="bg-[#fffaf2] text-[#4f4237] border-[#ded4c6] dark:bg-[#211c17] dark:text-[#e8ddcf] dark:border-[#3a332c]">
                <Layers className="w-3 h-3 mr-1" />
                GEM
              </Badge>
            </div>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={darkMode ? "切换浅色模式" : "切换深色模式"}
              onClick={() => setDarkMode((value) => !value)}
            >
              {darkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </header>

      {/* ===== Main ===== */}
      <main className="flex-1 min-h-0 max-w-[1680px] w-full mx-auto px-3 py-2 sm:px-4 sm:py-3 grid grid-cols-1 lg:grid-cols-[560px_minmax(0,1fr)] gap-3 lg:overflow-hidden">
        {/* 左侧：参数表单 */}
        <section className="space-y-2 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-1">
          <Card className="shadow-[0_1px_0_rgba(45,36,28,0.04)] border-[#ded4c6] bg-[#fffaf2] gap-2 py-3 lg:h-full lg:min-h-0 dark:border-[#3a332c] dark:bg-[#211c17]">
            <CardHeader className="px-4 pb-0">
              <CardTitle className="text-sm flex items-center gap-2">
                <MapPin className="w-4 h-4 text-[#5a4b3f] dark:text-[#d8cbbb]" />
                震中信息来源
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 lg:flex lg:min-h-0 lg:flex-1">
              <Tabs value={sourcePanel} onValueChange={(value) => setSourcePanel(value as SourcePanel)} className="lg:min-h-0 lg:flex-1">
                <TabsList className="grid grid-cols-2 w-full bg-[#efe6d8] text-[#6f6256] dark:bg-[#2b251f] dark:text-[#b7aa9b]">
                  <TabsTrigger value="input" className="text-xs data-[state=active]:bg-[#2d241c] data-[state=active]:text-[#fff8ee] dark:data-[state=active]:bg-[#f4eee5] dark:data-[state=active]:text-[#171411]">
                    输入方式
                  </TabsTrigger>
                  <TabsTrigger value="catalog" className="text-xs data-[state=active]:bg-[#2d241c] data-[state=active]:text-[#fff8ee] dark:data-[state=active]:bg-[#f4eee5] dark:data-[state=active]:text-[#171411]">
                    全量目录
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="catalog" className="mt-2">
                  <div className="rounded-xl border border-[#ded4c6] bg-[#fffdf8] p-2.5 dark:border-[#3a332c] dark:bg-[#1c1814]">
                    <Label htmlFor="catalogSearch" className="text-xs font-medium">
                      全量目录搜索
                    </Label>
                    <div className="mt-2 flex gap-2">
                      <div className="relative flex-1">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#76695d] dark:text-[#b7aa9b]" />
                        <Input
                          id="catalogSearch"
                          value={catalogSearch}
                          onChange={(e) => setCatalogSearch(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") submitCatalogSearch();
                          }}
                          placeholder="例：us6000t7zp / 2008 M7 Sichuan / 10.44,-68.47 r=200"
                          className="pl-9"
                        />
                      </div>
                      <Button
                        type="button"
                        onClick={submitCatalogSearch}
                        disabled={catalogSearchLoading || catalogSearch.trim().length < 2}
                        className="h-9 px-4 bg-[#2d241c] text-[#fff8ee] hover:bg-[#3a2d23] dark:bg-[#f4eee5] dark:text-[#171411]"
                      >
                        {catalogSearchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                        搜索
                      </Button>
                      {(catalogSearch || catalogSearchQuery) && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => {
                            setCatalogSearch("");
                            setCatalogSearchQuery("");
                            setCatalogSearchPage(1);
                          }}
                          className="h-9 px-3"
                        >
                          清空
                        </Button>
                      )}
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-[#76695d] dark:text-[#b7aa9b]">
                      输入 Event ID 可直接定位；也可用“年份 震级 地区”或“纬度,经度 r=半径km”搜索。结果按时间倒序分页显示，每页 10 条。
                    </p>
                    {catalogSearchQuery.trim().length >= 2 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {catalogSearchChips.map((part) => (
                          <Badge key={part} variant="outline" className="bg-[#fffaf2] dark:bg-[#211c17]">
                            {part}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {catalogSearchQuery.trim().length >= 2 && (
                      <div className="mt-3 rounded-lg border border-[#ded4c6] bg-[#fffaf2] dark:border-[#3a332c] dark:bg-[#211c17]">
                        {catalogSearchLoading && (
                          <div className="flex items-center gap-2 px-3 py-3 text-xs text-[#76695d] dark:text-[#b7aa9b]">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            正在搜索目录...
                          </div>
                        )}
                        {!catalogSearchLoading && catalogSearchError && (
                          <div className="px-3 py-3 text-xs text-red-600">
                            {publicError(catalogSearchError)}
                          </div>
                        )}
                        {!catalogSearchLoading && !catalogSearchError && catalogSearchResults.length === 0 && (
                          <div className="px-3 py-3 text-xs text-[#76695d] dark:text-[#b7aa9b]">
                            未找到匹配事件。可尝试输入年份、震级阈值、坐标半径或 USGS Event ID。
                          </div>
                        )}
                        {!catalogSearchLoading && !catalogSearchError && catalogSearchResults.length > 0 && (
                          <div className="border-b border-[#ded4c6] bg-[#fffaf2] px-3 py-2 text-xs text-[#76695d] dark:border-[#3a332c] dark:bg-[#211c17] dark:text-[#b7aa9b]">
                            <div className="flex items-center justify-between gap-2">
                              <span>
                                共 {catalogSearchTotal} 条，显示 {catalogResultStart}-{catalogResultEnd}
                              </span>
                              {catalogPageCount > 1 && <span>第 {safeCatalogPage}/{catalogPageCount} 页</span>}
                            </div>
                            {catalogSearchNote && <div className="mt-1">{catalogSearchNote}</div>}
                          </div>
                        )}
                        {!catalogSearchLoading && !catalogSearchError && catalogSearchResults.map((ev) => (
                          <CatalogEventButton
                            key={ev.eventId}
                            event={ev}
                            onChoose={chooseCatalogSearchEvent}
                          />
                        ))}
                        {!catalogSearchLoading && !catalogSearchError && catalogPageCount > 1 && (
                          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#ded4c6] bg-[#fffaf2] px-3 py-2 dark:border-[#3a332c] dark:bg-[#211c17]">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={safeCatalogPage <= 1}
                              onClick={() => setCatalogSearchPage((page) => Math.max(1, page - 1))}
                            >
                              上一页
                            </Button>
                            <div className="flex gap-1">
                              {catalogPageNumbers.map((page) => (
                                <Button
                                  key={page}
                                  type="button"
                                  size="sm"
                                  variant={page === safeCatalogPage ? "default" : "outline"}
                                  className="h-8 w-8 px-0"
                                  onClick={() => setCatalogSearchPage(page)}
                                >
                                  {page}
                                </Button>
                              ))}
                            </div>
                            <div className="flex items-center gap-1 text-xs text-[#76695d] dark:text-[#b7aa9b]">
                              <span>跳至</span>
                              <Input
                                aria-label="跳转页码"
                                type="number"
                                min={1}
                                max={catalogPageCount}
                                value={catalogPageInput}
                                onChange={(e) => setCatalogPageInput(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") jumpCatalogPage();
                                }}
                                className="h-8 w-16 px-2 text-center"
                              />
                              <span>/ 共 {catalogPageCount} 页</span>
                              <Button type="button" size="sm" variant="outline" onClick={jumpCatalogPage}>
                                跳转
                              </Button>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={safeCatalogPage >= catalogPageCount}
                              onClick={() => setCatalogSearchPage((page) => Math.min(catalogPageCount, page + 1))}
                            >
                              下一页
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </TabsContent>

                <TabsContent value="input" className="mt-2 lg:min-h-0">
              <Tabs value={mode} onValueChange={handleModeChange} className="lg:min-h-0 lg:h-full">
                <TabsList className="grid grid-cols-3 w-full bg-[#efe6d8] text-[#6f6256] dark:bg-[#2b251f] dark:text-[#b7aa9b]">
                  <TabsTrigger value="manual" className="text-xs data-[state=active]:bg-[#2d241c] data-[state=active]:text-[#fff8ee] dark:data-[state=active]:bg-[#f4eee5] dark:data-[state=active]:text-[#171411]">
                    手动输入
                  </TabsTrigger>
                  <TabsTrigger value="eventid" className="text-xs data-[state=active]:bg-[#2d241c] data-[state=active]:text-[#fff8ee] dark:data-[state=active]:bg-[#f4eee5] dark:data-[state=active]:text-[#171411]">
                    USGS Event ID
                  </TabsTrigger>
                  <TabsTrigger value="recent" className="text-xs data-[state=active]:bg-[#2d241c] data-[state=active]:text-[#fff8ee] dark:data-[state=active]:bg-[#f4eee5] dark:data-[state=active]:text-[#171411]">
                    近期大震
                  </TabsTrigger>
                </TabsList>

                {/* manual 模式 */}
                <TabsContent value="manual" className="space-y-2 mt-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div>
                      <Label htmlFor="lat" className="text-xs">纬度 Latitude</Label>
                      <Input
                        id="lat"
                        placeholder="例：10.4351"
                        value={lat}
                        onChange={(e) => setLat(e.target.value)}
                      />
                    </div>
                    <div>
                      <Label htmlFor="lon" className="text-xs">经度 Longitude</Label>
                      <Input
                        id="lon"
                        placeholder="例：-68.4716"
                        value={lon}
                        onChange={(e) => setLon(e.target.value)}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-[#76695d] dark:text-[#b7aa9b]">
                    使用十进制度：纬度北纬为正、南纬为负；经度东经为正、西经为负。例：委内瑞拉 10.4351, -68.4716。
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div>
                      <Label htmlFor="mag" className="text-xs">震级 Magnitude</Label>
                      <Input
                        id="mag"
                        placeholder="7.0"
                        value={mag}
                        onChange={(e) => setMag(e.target.value)}
                      />
                    </div>
                  </div>
                  <div>
                    <Label htmlFor="time" className="text-xs">
                      发震时间 UTC (ISO8601)
                    </Label>
                    <Input
                      id="time"
                      placeholder="2026-06-25T14:17:00Z"
                      value={time}
                      onChange={(e) => setTime(e.target.value)}
                    />
                  </div>
                  <details open className="rounded-lg border border-[#ded4c6] bg-[#fffdf8] p-2 text-xs dark:border-[#3a332c] dark:bg-[#1c1814]">
                    <summary className="cursor-pointer font-medium text-[#5a4b3f] dark:text-[#d8cbbb]">
                      高级参数：深度、震级类型、地名
                    </summary>
                    <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <div>
                        <Label htmlFor="depth" className="text-xs">深度 km</Label>
                        <Input
                          id="depth"
                          placeholder="10"
                          value={depth}
                          onChange={(e) => setDepth(e.target.value)}
                        />
                      </div>
                      <div>
                        <Label htmlFor="magType" className="text-xs">震级类型</Label>
                        <Select value={magType} onValueChange={setMagType}>
                          <SelectTrigger id="magType">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="Mw">Mw (矩震级)</SelectItem>
                            <SelectItem value="Ms">Ms (面波震级)</SelectItem>
                            <SelectItem value="Mb">Mb (体波震级)</SelectItem>
                            <SelectItem value="Ml">Ml (近震震级)</SelectItem>
                            <SelectItem value="Mww">Mww (W-phase)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label htmlFor="place" className="text-xs">地名 (可选)</Label>
                        <Input
                          id="place"
                          placeholder="Honshu, Japan"
                          value={place}
                          onChange={(e) => setPlace(e.target.value)}
                        />
                      </div>
                    </div>
                  </details>
                </TabsContent>

                {/* eventid 模式 */}
                <TabsContent value="eventid" className="space-y-2 mt-3">
                  <div>
                    <Label htmlFor="eventId" className="text-xs">
                      USGS Event ID
                    </Label>
                    <Input
                      id="eventId"
                      placeholder="us7000xxxx"
                      value={eventId}
                      onChange={(e) => {
                        setEventId(e.target.value);
                        setSelectedCatalogEvent(null);
                      }}
                    />
                    <p className="text-xs text-[#76695d] mt-1 dark:text-[#b7aa9b]">
                      形如 <code className="bg-[#efe6d8] px-1 rounded dark:bg-[#2b251f]">us7000ndeb</code>，可在 USGS
                      事件页面 URL 末段找到。
                    </p>
                  </div>
                </TabsContent>

                {/* recent 模式 */}
                <TabsContent value="recent" className="space-y-2 mt-2 lg:min-h-0 lg:flex lg:flex-col">
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full h-9"
                    onClick={loadRecentEvents}
                    disabled={recentLoading}
                  >
                    {recentLoading ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Search className="w-4 h-4 mr-2" />
                    )}
                    拉取近 30 天 M≥6.0 地震
                  </Button>
                  {recentEvents.length > 0 && (
                    <div className="max-h-[min(52vh,520px)] overflow-hidden border rounded-md border-[#ded4c6] lg:min-h-0 lg:flex-1 lg:max-h-none dark:border-[#3a332c]">
                      <Table containerClassName="max-h-[min(52vh,520px)] overflow-y-auto overflow-x-hidden lg:h-full lg:max-h-none">
                        <TableHeader className="sticky top-0 z-10 bg-[#fffaf2] dark:bg-[#211c17]">
                          <TableRow className="text-xs">
                            <TableHead className="w-7 px-2"></TableHead>
                            <TableHead className="w-[118px] px-2">时间</TableHead>
                            <TableHead className="w-[74px] px-2">震级</TableHead>
                            <TableHead className="px-2">位置</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {recentEvents.map((ev) => (
                            <RecentEventRow
                              key={ev.eventId}
                              event={ev}
                              selected={selectedEventId === ev.eventId}
                              onChoose={chooseRecentEvent}
                            />
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </TabsContent>
              </Tabs>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>

        </section>

        {/* 右侧：结果展示 */}
        <section className="lg:min-h-0">
          <Card className="shadow-[0_1px_0_rgba(45,36,28,0.04)] border-[#ded4c6] bg-[#fffaf2] gap-2 py-3 min-h-[420px] sm:min-h-[600px] lg:h-full lg:min-h-0 dark:border-[#3a332c] dark:bg-[#211c17]">
            <CardHeader className="px-4 pb-0 sm:px-6">
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#5a4b3f] dark:text-[#d8cbbb]" />
                生成结果
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 sm:px-6 lg:min-h-0 lg:overflow-y-auto">
              {!loading && generationControls}
              {!result && !loading && (
                  <div className="flex flex-col items-center justify-center py-12 sm:py-20 text-center">
                    <div className="w-16 h-16 rounded-full bg-[#efe6d8] flex items-center justify-center mb-4 dark:bg-[#2b251f]">
                      <Globe2 className="w-8 h-8 text-[#9b8d7f] dark:text-[#807469]" />
                    </div>
                    <p className="text-[#5a4b3f] dark:text-[#d8cbbb]">
                      选择左侧事件并确认上方参数，点击「生成报告」
                    </p>
                    <p className="text-xs text-[#9b8d7f] mt-1 dark:text-[#807469]">
                      报告将包含事件概况、数据来源、震级分布、代表性地震、分布图和数据口径
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 w-full max-w-3xl mt-6 text-left">
                      <InfoTile icon={<Calendar className="w-3 h-3" />} label="主目录" value="USGS FDSN" />
                      <InfoTile icon={<Globe2 className="w-3 h-3" />} label="辅助核对" value="EMSC" />
                      <InfoTile icon={<Layers className="w-3 h-3" />} label="构造背景" value="GEM 断层" />
                      <InfoTile icon={<FileText className="w-3 h-3" />} label="输出" value="Word / PDF" />
                    </div>
                  </div>
                )}

                {loading && (
                  <div className="space-y-4">
                    <div className="rounded-xl border border-[#ded4c6] bg-[#fffdf8] p-4 dark:border-[#3a332c] dark:bg-[#1c1814]">
                      <div className="flex items-start gap-3">
                        <Loader2 className="mt-1 h-5 w-5 animate-spin text-[#5a4b3f] dark:text-[#d8cbbb]" />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="font-medium text-[#2d241c] dark:text-[#f4eee5]">{loadingMessage}</p>
                            {generationStep.step && generationStep.total && (
                              <Badge variant="outline">第 {generationStep.step}/{generationStep.total} 步</Badge>
                            )}
                            {generationStep.queuePosition && generationStep.queuePosition > 1 && (
                              <Badge variant="outline">排队第 {generationStep.queuePosition} 个</Badge>
                            )}
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#76695d] dark:text-[#b7aa9b]">
                            <span>已用 {formatSeconds(elapsedSec)}</span>
                            <span>预计目录 {catalogCount == null ? "读取中" : `${catalogCount.toLocaleString()} 条`}</span>
                            {cacheNote && <span>{cacheNote}</span>}
                          </div>
                        </div>
                      </div>
                      <div className="h-2 rounded-full bg-[#efe6d8] overflow-hidden dark:bg-[#2b251f]">
                        <div
                          className="h-full bg-[#2d241c] transition-all duration-300 dark:bg-[#f4eee5]"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <div className="mt-2 text-xs text-[#76695d] text-right dark:text-[#b7aa9b]">
                        {progress}%
                      </div>
                    </div>
                    {mapPreview && (
                      <div className="rounded-xl border border-[#ded4c6] bg-white p-2 dark:border-[#3a332c] dark:bg-[#171411]">
                        <div className="mb-2 flex items-center justify-between text-xs text-[#76695d] dark:text-[#b7aa9b]">
                          <span>分布图预览已就绪，报告仍在写入</span>
                          <a href={mapPreview.url} download={mapPreview.fileName || "map.png"} className="flex items-center gap-1 text-rose-600 hover:underline">
                            <Download className="h-3 w-3" />
                            原图
                          </a>
                        </div>
                        <img
                          src={mapPreview.url}
                          alt="震中周围地震分布图预览"
                          loading="lazy"
                          decoding="async"
                          className="max-h-[45vh] w-full rounded-md object-contain"
                        />
                      </div>
                    )}
                    {!mapPreview && catalogCount != null && (
                      <div className="rounded-xl border border-dashed border-[#ded4c6] bg-[#fffdf8] p-4 text-sm text-[#76695d] dark:border-[#3a332c] dark:bg-[#1c1814] dark:text-[#b7aa9b]">
                        <div className="flex items-center gap-2 font-medium text-[#5a4b3f] dark:text-[#d8cbbb]">
                          <ImageIcon className="h-4 w-4" />
                          分布图准备中
                        </div>
                        <p className="mt-1 text-xs">
                          预计目录 {catalogCount.toLocaleString()} 条，地图模式：{mapViewLabel}。图件生成后会自动显示预览。
                        </p>
                      </div>
                    )}
                    <p className="text-xs text-[#76695d] dark:text-[#b7aa9b]">
                      全量统计和全量图件继续使用完整目录；地图显示方式只影响图面表达。
                    </p>
                  </div>
                )}

                {result && !result.ok && (
                  <div className="space-y-3">
                    <div className="flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-lg">
                      <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <p className="font-semibold text-red-700">生成失败</p>
                        <p className="text-sm text-red-600 mt-1">{publicError(result.error)}</p>
                      </div>
                    </div>
                  </div>
                )}

                {result && result.ok && (
                  <div className="space-y-4">
                    <div className="flex items-start gap-3 p-3 bg-green-50 border border-green-200 rounded-lg">
                      <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                      <div className="flex-1 text-sm text-green-700">
                        报告已生成。
                        {result.stats && (
                          <span className="ml-1">
                            统计：N3={result.stats.n3} · N4={result.stats.n4} · N5={result.stats.n5} ·
                            N6={result.stats.n6} · N7={result.stats.n7} · N8={result.stats.n8}
                          </span>
                        )}
                      </div>
                    </div>

                    {(result.mapMeta || result.warnings?.length) && (
                      <div className="rounded-lg border border-[#ded4c6] bg-[#fffdf8] px-3 py-2 text-xs text-[#76695d] dark:border-[#3a332c] dark:bg-[#1c1814] dark:text-[#b7aa9b]">
                        {result.mapMeta && (
                          <div>
                            图面点数 {result.mapMeta.display_count.toLocaleString()} / 统计全量 {result.mapMeta.total_count.toLocaleString()} 条
                            <span className="ml-2">模式：{mapViewLabel}</span>
                          </div>
                        )}
                        {result.stats?.mc_estimate && (
                          <div className="mt-1">目录完整性提示：Mc≈{Number(result.stats.mc_estimate).toFixed(1)}，统计口径不变。</div>
                        )}
                        {result.warnings?.map((warning, index) => (
                          <div key={index} className="mt-1 text-amber-700 dark:text-amber-300">{warning}</div>
                        ))}
                      </div>
                    )}

                    {result.stats && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                        <InfoTile
                          icon={<Activity className="w-3 h-3" />}
                          label="目录事件"
                          value={`${result.stats.total_count ?? result.stats.n3 ?? "-"} 条`}
                        />
                        <InfoTile icon={<Activity className="w-3 h-3" />} label="M5+" value={`${result.stats.n5 ?? 0} 条`} />
                        <InfoTile icon={<Activity className="w-3 h-3" />} label="M6+" value={`${result.stats.n6 ?? 0} 条`} />
                        <InfoTile icon={<Activity className="w-3 h-3" />} label="M7+" value={`${result.stats.n7 ?? 0} 条`} />
                      </div>
                    )}

                    {/* 主震概要 */}
                    {result.mainshock && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                        <InfoTile
                          icon={<Clock className="w-3 h-3" />}
                          label="发震时间 UTC"
                          value={result.mainshock.time_utc?.slice(0, 16).replace("T", " ") || "-"}
                        />
                        <InfoTile
                          icon={<MapPin className="w-3 h-3" />}
                          label="震中"
                          value={`${result.mainshock.latitude?.toFixed(2)}°, ${result.mainshock.longitude?.toFixed(2)}°`}
                        />
                        <InfoTile
                          icon={<Activity className="w-3 h-3" />}
                          label="震级"
                          value={`${result.mainshock.mag_type || "Mw"} ${result.mainshock.magnitude?.toFixed(1)}`}
                        />
                        <InfoTile
                          icon={<Layers className="w-3 h-3" />}
                          label="深度 km"
                          value={result.mainshock.depth_km?.toFixed(1) || "-"}
                        />
                      </div>
                    )}

                    {/* 分布图预览 */}
                    {result.files?.map && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-sm font-medium text-[#5a4b3f] flex items-center gap-1 dark:text-[#d8cbbb]">
                            <ImageIcon className="w-4 h-4" />
                            震中周围地震分布图
                          </p>
                          <a
                            href={result.files.map}
                            download={result.fileNames?.map || "map.png"}
                            className="text-xs text-rose-600 hover:underline flex items-center gap-1"
                          >
                            <Download className="w-3 h-3" />
                            原图
                          </a>
                        </div>
                        <div className="border rounded-lg overflow-hidden bg-white border-[#ded4c6] dark:border-[#3a332c]">
                          <img
                            src={result.files.map}
                            alt="震中周围地震分布图"
                            loading="lazy"
                            decoding="async"
                            className="w-full h-auto"
                          />
                        </div>
                      </div>
                    )}

                    {/* 下载按钮 */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      {result.files?.catalog && (
                        <button
                          type="button"
                          onClick={() => downloadReportFile(result.files?.catalog, result.fileNames?.catalog || "catalog.csv", "目录 CSV 下载失败")}
                          className="flex items-center justify-center gap-2 h-11 border border-[#ded4c6] bg-white text-[#2d241c] hover:bg-[#fff8ee] rounded-md text-sm font-medium transition dark:border-[#3a332c] dark:bg-[#211c17] dark:text-[#f4eee5] dark:hover:bg-[#2b251f]"
                        >
                          <Download className="w-4 h-4" />
                          下载目录 CSV
                        </button>
                      )}
                      {result.files?.docx && (
                        <button
                          type="button"
                          onClick={() => downloadReportFile(result.files?.docx, result.fileNames?.docx || "report.docx", "Word 下载失败")}
                          className="flex items-center justify-center gap-2 h-11 bg-[#2d241c] hover:bg-[#3a2d23] text-[#fff8ee] rounded-md text-sm font-medium transition dark:bg-[#f4eee5] dark:text-[#171411] dark:hover:bg-white"
                        >
                          <FileText className="w-4 h-4" />
                          下载 Word (.docx)
                        </button>
                      )}
                      {result.canPdf && result.files?.docx && (
                        <button
                          type="button"
                          onClick={downloadPdf}
                          disabled={pdfLoading}
                          className="flex items-center justify-center gap-2 h-11 bg-red-600 hover:bg-red-700 disabled:opacity-60 text-white rounded-md text-sm font-medium transition"
                        >
                          {pdfLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                          {result.files?.pdf ? "下载 PDF" : "转换并下载 PDF"}
                        </button>
                      )}
                    </div>

                  </div>
                )}
            </CardContent>
          </Card>
        </section>
      </main>

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[#ded4c6] bg-[#fbf7ef]/95 p-3 backdrop-blur lg:hidden dark:border-[#3a332c] dark:bg-[#171411]/95">
        <Button
          className="h-11 w-full bg-[#2d241c] text-sm font-semibold text-[#fff8ee] hover:bg-[#3a2d23] dark:bg-[#f4eee5] dark:text-[#171411] dark:hover:bg-white"
          onClick={generate}
          disabled={loading}
        >
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Zap className="mr-2 h-4 w-4" />}
          {loading ? `生成中 ${progress}%` : "生成报告"}
        </Button>
      </div>

      {/* ===== Footer ===== */}
      <footer className="border-t border-[#ded4c6] bg-[#fbf7ef]/80 backdrop-blur mt-auto dark:border-[#3a332c] dark:bg-[#171411]/80">
        <div className="max-w-[1680px] mx-auto px-4 py-3 flex flex-col md:flex-row items-center justify-between gap-2 text-xs text-[#76695d] dark:text-[#b7aa9b]">
          <div className="flex items-center gap-2">
            <Calendar className="w-3 h-3" />
            数据源：USGS FDSN · EMSC/SeismicPortal · GEM Global Active Faults · Natural Earth/天地图
          </div>
          <div>目录覆盖 1900 至今 · 默认 M≥3.0 · 距离按震中大圆距离计算</div>
        </div>
      </footer>
    </div>
  );
}

function formatEventTime(value: string) {
  return value.slice(0, 16).replace("T", " ");
}

const CatalogEventButton = memo(function CatalogEventButton({
  event,
  onChoose,
}: {
  event: RecentEvent;
  onChoose: (event: RecentEvent) => void;
}) {
  const place = event.place || `${event.latitude.toFixed(2)}°, ${event.longitude.toFixed(2)}°`;

  return (
    <button
      type="button"
      onClick={() => onChoose(event)}
      className="block w-full border-b border-[#ded4c6] px-3 py-2.5 text-left last:border-b-0 hover:bg-[#f5ecdf] focus:outline-none focus:ring-2 focus:ring-[#2d241c] dark:border-[#3a332c] dark:hover:bg-[#2b251f] dark:focus:ring-[#f4eee5]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-[#76695d] dark:text-[#b7aa9b]">
              {formatEventTime(event.time)}
            </span>
            <span className="text-xs text-[#9b8d7f] dark:text-[#807469]">
              {event.depth.toFixed(1)} km
            </span>
          </div>
          <div className="mt-1 text-sm leading-snug text-[#2d241c] dark:text-[#f4eee5]">
            {place}
          </div>
          <div className="mt-1 font-mono text-xs text-[#76695d] dark:text-[#b7aa9b]">
            {event.latitude.toFixed(2)}°, {event.longitude.toFixed(2)}°
          </div>
        </div>
        <Badge variant={event.mag >= 7 ? "destructive" : event.mag >= 6 ? "default" : "secondary"} className="shrink-0">
          M{event.mag.toFixed(1)}
        </Badge>
      </div>
      <div className="mt-1 flex justify-end">
        <span className="font-mono text-xs text-[#76695d] dark:text-[#b7aa9b]">
          {event.eventId}
        </span>
      </div>
    </button>
  );
});

const RecentEventRow = memo(function RecentEventRow({
  event,
  selected,
  onChoose,
}: {
  event: RecentEvent;
  selected: boolean;
  onChoose: (event: RecentEvent) => void;
}) {
  return (
    <TableRow
      className={`h-9 cursor-pointer ${
        selected
          ? "bg-[#2d241c] text-[#fff8ee] hover:bg-[#2d241c] dark:bg-[#f4eee5] dark:text-[#171411] dark:hover:bg-[#f4eee5]"
          : "hover:bg-[#f5ecdf] dark:hover:bg-[#2b251f]"
      }`}
      onClick={() => onChoose(event)}
    >
      <TableCell className="px-2 py-2">
        {selected && (
          <CheckCircle2 className="w-4 h-4 text-[#fff8ee] dark:text-[#171411]" />
        )}
      </TableCell>
      <TableCell className="px-2 py-2 text-xs font-mono">
        {formatEventTime(event.time)}
      </TableCell>
      <TableCell className="px-2 py-2">
        <Badge
          variant={
            event.mag >= 7
              ? "destructive"
              : event.mag >= 6.5
              ? "default"
              : "secondary"
          }
        >
          M{event.mag.toFixed(1)}
        </Badge>
      </TableCell>
      <TableCell className="px-2 py-2 whitespace-normal break-words">
        <span className="block text-xs leading-snug" title={event.place}>
          {event.place}
        </span>
      </TableCell>
    </TableRow>
  );
});

const InfoTile = memo(function InfoTile({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="bg-[#fffdf8] border border-[#ded4c6] rounded-md p-2 dark:bg-[#1c1814] dark:border-[#3a332c]">
      <div className="text-[#76695d] flex items-center gap-1 mb-0.5 dark:text-[#b7aa9b]">
        {icon}
        {label}
      </div>
      <div className="font-mono text-[#2d241c] text-xs whitespace-normal break-words dark:text-[#f4eee5]">{value}</div>
    </div>
  );
});
