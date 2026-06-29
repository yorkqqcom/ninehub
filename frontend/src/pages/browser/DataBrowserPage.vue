<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { apiRequest } from "@/api/client";
import type {
  BrowserAuditItem,
  BrowserExecuteResponse,
  BrowserIndicatorRef,
  BrowserMetaResponse,
  BrowserTemplateItem,
  BrowserTemplateResponse,
  BrowserWatchlistItem,
} from "@/api/types";
import BrowserDataToolbar from "@/components/browser/BrowserDataToolbar.vue";
import BrowserIndicatorBasket from "@/components/browser/BrowserIndicatorBasket.vue";
import BrowserIndicatorPicker from "@/components/browser/BrowserIndicatorPicker.vue";
import BrowserDimensionPicker from "@/components/browser/BrowserDimensionPicker.vue";
import BrowserReadinessPanel from "@/components/browser/BrowserReadinessPanel.vue";
import {
  resolveDragRejectMessage,
  type DragRejectReason,
} from "@/components/browser/browserDragUtils";
import { INDICATOR_LIMIT } from "@/components/browser/indicatorUtils";
import PageHeader from "@/components/PageHeader.vue";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { disposeAndReinitChart, ensureChartInstance } from "@/utils/echartsTheme";

type IndicatorPick = { id: string; adjust?: string };
type WizardStep = "scope" | "indicators" | "time";

const WIZARD_STEPS: { key: WizardStep; label: string; num: number }[] = [
  { key: "scope", label: "选范围", num: 1 },
  { key: "indicators", label: "选指标", num: 2 },
  { key: "time", label: "选时间", num: 3 },
];

const route = useRoute();
const router = useRouter();
const ui = useUiStore();
const auth = useAuthStore();

const meta = ref<BrowserMetaResponse | null>(null);
const userTemplates = ref<BrowserTemplateResponse[]>([]);
const userWatchlists = ref<BrowserWatchlistItem[]>([]);
const loadingMeta = ref(false);
const loadingData = ref(false);
const wizardStep = ref<WizardStep>("scope");
const universeMode = ref<"preset" | "custom">("preset");
const customCodesText = ref("");
const asOfDate = ref(new Date().toISOString().slice(0, 10));
const timeMode = ref<"single" | "multi">("single");
const multiDatesText = ref("");
const selectedDimension = ref("all_ab");
const financialAlign = ref<"independent" | "unified">("independent");
const unifiedEndDate = ref("");
const selectedIndicators = ref<IndicatorPick[]>([]);
const universeCount = ref<number | null>(null);
const universeEstimate = ref(false);
const universeSampleCodes = ref<string[]>([]);
const universeWarnings = ref<string[]>([]);
const forceRefresh = ref(false);
const cacheHit = ref(false);
const result = ref<BrowserExecuteResponse | null>(null);
const viewMode = ref<"table" | "chart">("table");
const chartType = ref<"bar" | "scatter" | "line">("bar");
const chartXKey = ref<string | null>(null);
const chartYKey = ref<string | null>(null);
const chartRef = ref<HTMLDivElement | null>(null);
let chartInst: import("echarts").ECharts | null = null;
const page = ref(1);
const pageSize = ref(50);
const aggScope = ref<"full" | "page">("full");
const drillFilter = ref<string | null>(null);
const sortCol = ref<string | null>(null);
const sortAsc = ref(true);
const modalOpen = ref(false);
const modalType = ref<"template" | "watchlist">("template");
const modalName = ref("");
const exportFormat = ref<"csv" | "xlsx">("csv");
const exportJobId = ref<number | null>(null);
const exportDownloadUrl = ref<string | null>(null);
const showAudit = ref(false);
const auditItems = ref<BrowserAuditItem[]>([]);

const flatIndicators = computed(() => meta.value?.indicators_flat ?? []);
const indicatorTree = computed(() => meta.value?.indicator_tree ?? []);
const dimensions = computed(() => meta.value?.dimensions ?? []);
const systemTemplates = computed(() => meta.value?.system_templates ?? []);

const selectedDimensionLabel = computed(() => {
  if (universeMode.value === "custom") {
    const n = parseCustomCodes(customCodesText.value).length;
    return n ? `自定义 (${n} 只)` : "自定义代码";
  }
  if (selectedDimension.value.startsWith("watchlist:")) {
    const id = Number(selectedDimension.value.split(":")[1]);
    const wl = userWatchlists.value.find((w) => w.id === id);
    return wl ? wl.name : "自选股";
  }
  return dimensions.value.find((d) => d.id === selectedDimension.value)?.label ?? selectedDimension.value;
});

const extractSummary = computed(() => {
  const n = universeCount.value ?? 0;
  const m = selectedIndicators.value.length;
  if (!n || !m) return "";
  return `预计 ${universeEstimate.value ? "约 " : ""}${n.toLocaleString()} 只 × ${m} 指标`;
});

const selectedIndicatorIds = computed(() => selectedIndicators.value.map((s) => s.id));

const selectedSummaryLabels = computed(() => {
  const labels = selectedIndicators.value.slice(0, 4).map((s) => indicatorLabel(s.id));
  const suffix = selectedIndicators.value.length > 4 ? "…" : "";
  return labels.join("、") + suffix;
});

const pageRangeLabel = computed(() => {
  if (!result.value) return "";
  const start = (page.value - 1) * pageSize.value + 1;
  const end = Math.min(page.value * pageSize.value, result.value.total);
  return `${start}-${end} / ${result.value.total.toLocaleString()}`;
});

const wizardStepLabel = computed(
  () => WIZARD_STEPS.find((s) => s.key === wizardStep.value)?.label ?? "",
);

const timeStepDateLabel = computed(() => {
  if (timeMode.value === "multi") {
    const dates = parseMultiDates();
    return dates.length ? dates.join(", ") : "—";
  }
  return asOfDate.value;
});

const WIZARD_ORDER: WizardStep[] = ["scope", "indicators", "time"];

const wizardPrevStep = computed(() => {
  const i = WIZARD_ORDER.indexOf(wizardStep.value);
  return i > 0 ? WIZARD_ORDER[i - 1]! : null;
});

const wizardNextStep = computed(() => {
  const i = WIZARD_ORDER.indexOf(wizardStep.value);
  return i < WIZARD_ORDER.length - 1 ? WIZARD_ORDER[i + 1]! : null;
});

const wizardPrevLabel = computed(
  () => WIZARD_STEPS.find((s) => s.key === wizardPrevStep.value)?.label ?? "",
);

const wizardNextLabel = computed(
  () => WIZARD_STEPS.find((s) => s.key === wizardNextStep.value)?.label ?? "",
);

function isStepComplete(step: WizardStep): boolean {
  if (step === "scope") return (universeCount.value ?? 0) > 0;
  if (step === "indicators") return selectedIndicators.value.length > 0;
  if (timeMode.value === "multi") return parseMultiDates().length > 0;
  return Boolean(asOfDate.value);
}

function goWizardStep(step: WizardStep) {
  if (step === "time" && !selectedIndicators.value.length) {
    ui.showMessage("请先在「选指标」添加至少 1 项指标", "info");
    wizardStep.value = "indicators";
    return;
  }
  wizardStep.value = step;
}

function stepStatus(step: WizardStep): "active" | "done" | "pending" {
  const currentIdx = WIZARD_ORDER.indexOf(wizardStep.value);
  const stepIdx = WIZARD_ORDER.indexOf(step);
  if (stepIdx === currentIdx) return "active";
  if (stepIdx < currentIdx && isStepComplete(step)) return "done";
  return "pending";
}

const numericResultColumns = computed(() =>
  (result.value?.columns ?? []).filter((c) => c.type === "number" && c.id !== "stock_code"),
);

function parseCustomCodes(text: string): string[] {
  return text
    .split(/[\n,;\s]+/)
    .map((c) => c.trim())
    .filter(Boolean);
}

function buildUniverse() {
  if (universeMode.value === "custom") {
    return { type: "custom" as const, codes: parseCustomCodes(customCodesText.value) };
  }
  if (selectedDimension.value.startsWith("watchlist:")) {
    return {
      type: "watchlist" as const,
      watchlist_id: Number(selectedDimension.value.split(":")[1]),
    };
  }
  return { type: "preset" as const, preset: selectedDimension.value };
}

const maxPage = computed(() =>
  result.value ? Math.max(1, Math.ceil(result.value.total / pageSize.value)) : 1,
);

const displayRows = computed(() => {
  let rows = [...(result.value?.items ?? [])];
  if (drillFilter.value) {
    rows = rows.filter((r) => String(r.stock_code) === drillFilter.value);
  }
  return rows;
});

const pageAggregations = computed(() => {
  if (!result.value || aggScope.value === "full") return result.value?.aggregations ?? [];
  const cols = result.value.columns.filter((c) => c.type === "number").map((c) => c.id);
  return cols.map((col_id) => {
    const nums = displayRows.value
      .map((r) => r[col_id])
      .filter((v) => v != null && !Number.isNaN(Number(v)))
      .map(Number);
    if (!nums.length) return { column_id: col_id, count: 0 };
    return {
      column_id: col_id,
      sum: nums.reduce((a, b) => a + b, 0),
      avg: nums.reduce((a, b) => a + b, 0) / nums.length,
      min: Math.min(...nums),
      max: Math.max(...nums),
      count: nums.length,
    };
  });
});

async function loadMeta() {
  loadingMeta.value = true;
  try {
    const [m, tpls, wls] = await Promise.all([
      apiRequest<BrowserMetaResponse>("/api/v1/query/browser/meta"),
      apiRequest<BrowserTemplateResponse[]>("/api/v1/query/browser/templates"),
      apiRequest<BrowserWatchlistItem[]>("/api/v1/query/browser/watchlists"),
    ]);
    meta.value = m;
    userTemplates.value = tpls.filter((t) => !t.is_system);
    userWatchlists.value = wls;
    if (!(m.indicators_flat?.length)) {
      ui.showMessage("指标列表为空，请确认 P0 数据已激活并重启后端", "error");
    }
  } catch {
    ui.showMessage("加载指标元数据失败，请检查 API 是否在线", "error");
  } finally {
    loadingMeta.value = false;
  }
}

async function previewUniverse() {
  const body = { universe: buildUniverse() };
  const res = await apiRequest<{
    stock_count: number;
    is_estimate: boolean;
    sample_codes: string[];
    warnings: string[];
  }>("/api/v1/query/browser/universe/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
  universeCount.value = res.stock_count;
  universeEstimate.value = res.is_estimate;
  universeSampleCodes.value = res.sample_codes ?? [];
  universeWarnings.value = res.warnings ?? [];
}

function parseMultiDates(): string[] {
  return multiDatesText.value
    .split(/[\n,;\s]+/)
    .map((d) => d.trim())
    .filter(Boolean)
    .slice(0, 5);
}

function toggleIndicator(ind: BrowserIndicatorRef) {
  if (!ind.available) return;
  if (selectedIndicators.value.some((s) => s.id === ind.id)) {
    removeIndicator(ind.id);
    return;
  }
  if (selectedIndicators.value.length >= INDICATOR_LIMIT) {
    ui.showMessage(`指标数已达上限 ${INDICATOR_LIMIT}`, "error");
    return;
  }
  if (timeMode.value === "multi" && ind.freq === "period") {
    ui.showMessage("多截面模式不支持期频指标", "info");
  }
  selectedIndicators.value.push({
    id: ind.id,
    adjust: ind.supports_adjust ? "none" : undefined,
  });
}

function removeIndicator(id: string) {
  selectedIndicators.value = selectedIndicators.value.filter((s) => s.id !== id);
}

function onDragRejected(reason: DragRejectReason) {
  ui.showMessage(resolveDragRejectMessage(reason), reason === "duplicate" ? "info" : "error");
}

function indicatorMeta(id: string) {
  return flatIndicators.value.find((i) => i.id === id);
}

function indicatorLabel(id: string) {
  return indicatorMeta(id)?.label ?? id;
}

function buildTemplatePayload() {
  return {
    universe: buildUniverse(),
    indicators: selectedIndicators.value,
    as_of_date: asOfDate.value,
    financial_align: financialAlign.value,
    unified_end_date: unifiedEndDate.value || undefined,
    dates: timeMode.value === "multi" ? parseMultiDates() : undefined,
  };
}

function buildQueryBody() {
  const body: Record<string, unknown> = {
    universe: buildUniverse(),
    as_of_date: asOfDate.value,
    indicators: selectedIndicators.value,
    skip: (page.value - 1) * pageSize.value,
    limit: pageSize.value,
    include_aggregations: true,
    financial_align: financialAlign.value,
    force_refresh: forceRefresh.value,
  };
  if (financialAlign.value === "unified" && unifiedEndDate.value) {
    body.unified_end_date = unifiedEndDate.value;
  }
  if (timeMode.value === "multi") {
    const dates = parseMultiDates();
    if (dates.length) body.dates = dates;
  }
  if (sortCol.value) {
    body.sort = { column: sortCol.value, direction: sortAsc.value ? "asc" : "desc" };
  }
  return body;
}

async function runQuery() {
  if (!selectedIndicators.value.length) return;
  loadingData.value = true;
  drillFilter.value = null;
  try {
    result.value = await apiRequest<BrowserExecuteResponse>("/api/v1/query/browser/execute", {
      method: "POST",
      body: JSON.stringify(buildQueryBody()),
    });
    cacheHit.value = Boolean(result.value.cache_hit);
    if (result.value.meta.as_of_date !== result.value.meta.effective_date) {
      ui.showMessage(
        `截面日 ${result.value.meta.as_of_date} 已调整为 ${result.value.meta.effective_date}`,
        "info",
      );
    }
    if (result.value.warnings?.length) {
      ui.showMessage(result.value.warnings.map((w) => w.reason).join("；"), "info");
    }
    syncUrl();
    if (viewMode.value === "chart") await nextTick(() => renderChart());
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    loadingData.value = false;
    forceRefresh.value = false;
  }
}

function syncUrl() {
  router.replace({
    query: {
      ...route.query,
      date: asOfDate.value,
      dim: selectedDimension.value,
      page: String(page.value),
      align: financialAlign.value,
    },
  });
}

function loadTemplatePayload(
  payload: {
    universe?: { preset?: string; type?: string; codes?: string[]; watchlist_id?: number };
    indicators?: IndicatorPick[];
    as_of_date?: string;
    financial_align?: "independent" | "unified";
    unified_end_date?: string;
    dates?: string[];
  },
  mode: "replace" | "append" = "replace",
) {
  const u = payload.universe;
  if (u?.type === "custom" && u.codes?.length) {
    universeMode.value = "custom";
    customCodesText.value = u.codes.join("\n");
  } else if (u?.type === "watchlist" && u.watchlist_id) {
    universeMode.value = "preset";
    selectedDimension.value = `watchlist:${u.watchlist_id}`;
  } else if (u?.preset) {
    universeMode.value = "preset";
    selectedDimension.value = u.preset;
  }
  if (payload.as_of_date) asOfDate.value = payload.as_of_date;
  if (payload.financial_align) financialAlign.value = payload.financial_align;
  if (payload.unified_end_date) unifiedEndDate.value = payload.unified_end_date;
  if (payload.dates?.length) {
    timeMode.value = "multi";
    multiDatesText.value = payload.dates.join("\n");
  }
  const inds = payload.indicators ?? [];
  if (mode === "replace") selectedIndicators.value = [...inds];
  else {
    for (const i of inds) {
      if (!selectedIndicators.value.some((s) => s.id === i.id)) {
        selectedIndicators.value.push(i);
      }
    }
  }
  previewUniverse();
}

function loadSystemTemplate(tpl: BrowserTemplateItem, mode: "replace" | "append" = "replace") {
  loadTemplatePayload(tpl.payload as Parameters<typeof loadTemplatePayload>[0], mode);
}

function loadUserTemplate(tpl: BrowserTemplateResponse, mode: "replace" | "append" = "replace") {
  loadTemplatePayload(tpl.payload as Parameters<typeof loadTemplatePayload>[0], mode);
}

function openSaveModal(type: "template" | "watchlist") {
  modalType.value = type;
  modalName.value = "";
  modalOpen.value = true;
}

async function confirmSaveModal() {
  const name = modalName.value.trim();
  if (!name) return;
  modalOpen.value = false;
  if (modalType.value === "template") {
    await apiRequest<BrowserTemplateResponse>("/api/v1/query/browser/templates", {
      method: "POST",
      body: JSON.stringify({ name, payload: buildTemplatePayload() }),
    });
    ui.showMessage("模板已保存", "success");
    await loadMeta();
  } else {
    await apiRequest("/api/v1/query/browser/watchlists", {
      method: "POST",
      body: JSON.stringify({ name, universe: buildUniverse() }),
    });
    ui.showMessage("证券池已保存", "success");
    userWatchlists.value = await apiRequest<BrowserWatchlistItem[]>(
      "/api/v1/query/browser/watchlists",
    );
  }
}

async function deleteUserTemplate(id: number) {
  await apiRequest(`/api/v1/query/browser/templates/${id}`, { method: "DELETE" });
  ui.showMessage("模板已删除", "success");
  await loadMeta();
}

async function deleteWatchlist(id: number) {
  await apiRequest(`/api/v1/query/browser/watchlists/${id}`, { method: "DELETE" });
  ui.showMessage("证券池已删除", "success");
  userWatchlists.value = await apiRequest<BrowserWatchlistItem[]>(
    "/api/v1/query/browser/watchlists",
  );
}

async function saveTemplate() {
  openSaveModal("template");
}

async function saveWatchlist() {
  if ((universeCount.value ?? 0) <= 0) {
    ui.showMessage("请先选择有效证券池", "error");
    return;
  }
  openSaveModal("watchlist");
}

async function shareQuery() {
  const payload = buildTemplatePayload();
  const res = await apiRequest<{ share_token: string }>("/api/v1/query/browser/share", {
    method: "POST",
    body: JSON.stringify({ payload }),
  });
  const url = `${window.location.origin}/data-browser?share=${res.share_token}&auto=1`;
  await navigator.clipboard.writeText(url);
  ui.showMessage("分享链接已复制（打开后自动提取）", "success");
}

async function pollExportJob(jobId: number) {
  exportJobId.value = jobId;
  exportDownloadUrl.value = null;
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const job = await apiRequest<{ status: string; result_json?: { download_url?: string } }>(
      `/api/v1/platform/jobs/${jobId}`,
    );
    if (job.status === "success") {
      exportDownloadUrl.value = job.result_json?.download_url ?? null;
      ui.showMessage("异步导出完成", "success");
      return;
    }
    if (job.status === "failed") {
      ui.showMessage("异步导出失败", "error");
      return;
    }
  }
}

async function exportCsv(asyncJob = false) {
  const body = {
    query: { ...buildQueryBody(), skip: 0, limit: 2000 },
    format: exportFormat.value,
    async_job: asyncJob,
  };
  const res = await apiRequest<{ content?: string; job_id?: number; download_url?: string }>(
    "/api/v1/query/browser/export",
    { method: "POST", body: JSON.stringify(body) },
  );
  if (res.job_id) {
    ui.showMessage(`异步导出任务 #${res.job_id} 已入队`, "success");
    pollExportJob(res.job_id);
    return;
  }
  if (res.download_url) {
    exportDownloadUrl.value = res.download_url;
    ui.showMessage("导出完成", "success");
    return;
  }
  if (!res.content) return;
  const blob = new Blob([res.content], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `browser_${asOfDate.value}.csv`;
  a.click();
}

async function loadAudits() {
  const res = await apiRequest<{ items: BrowserAuditItem[] }>(
    "/api/v1/query/browser/audit?limit=20",
  );
  auditItems.value = res.items;
  showAudit.value = true;
}

function forceRefreshQuery() {
  forceRefresh.value = true;
  runQuery();
}

function toggleSort(colId: string) {
  if (sortCol.value === colId) sortAsc.value = !sortAsc.value;
  else {
    sortCol.value = colId;
    sortAsc.value = true;
  }
  page.value = 1;
  runQuery();
}

function onPageSizeChange() {
  page.value = 1;
  runQuery();
}

function formatCell(val: unknown) {
  if (val == null) return "—";
  if (typeof val === "number") return val.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(val);
}

function formatStatValue(val: number | null | undefined) {
  if (val == null || Number.isNaN(val)) return "—";
  const abs = Math.abs(val);
  const maxFrac = abs >= 1000 ? 2 : abs >= 1 ? 2 : 4;
  return val.toLocaleString(undefined, { maximumFractionDigits: maxFrac });
}

async function renderChart() {
  if (!chartRef.value || !result.value?.items.length) return;
  chartInst = await ensureChartInstance(chartRef.value, chartInst, ui.theme);
  if (!chartInst) return;
  const numCols = numericResultColumns.value;
  if (!numCols.length) return;

  if (chartType.value === "scatter") {
    const xKey = chartXKey.value ?? numCols[0]?.id;
    const yKey = chartYKey.value ?? numCols[1]?.id ?? numCols[0]?.id;
    if (!xKey || !yKey) return;
    const xCol = numCols.find((c) => c.id === xKey);
    const yCol = numCols.find((c) => c.id === yKey);
    const points = result.value.items
      .map((r) => {
        const x = Number(r[xKey]);
        const y = Number(r[yKey]);
        if (Number.isNaN(x) || Number.isNaN(y)) return null;
        return { name: String(r.stock_code), value: [x, y] };
      })
      .filter(Boolean) as { name: string; value: [number, number] }[];
    chartInst.setOption({
      tooltip: {
        trigger: "item",
        formatter: (p: { name?: string; value?: [number, number] }) =>
          `${p.name}<br/>${xCol?.label}: ${p.value?.[0]}<br/>${yCol?.label}: ${p.value?.[1]}`,
      },
      xAxis: { type: "value", name: xCol?.label, scale: true },
      yAxis: { type: "value", name: yCol?.label, scale: true },
      series: [{ type: "scatter", data: points, symbolSize: 8 }],
    });
  } else if (chartType.value === "line" && result.value.meta.multi_date_mode) {
    const yKey = chartYKey.value ?? numCols[0]?.id;
    const yCol = numCols.find((c) => c.id === yKey);
    if (!yKey) return;
    const row = drillFilter.value
      ? result.value.items.find((r) => String(r.stock_code) === drillFilter.value)
      : result.value.items[0];
    if (!row) return;
    const dateCols = numCols.filter((c) => c.id.includes("@"));
    chartInst.setOption({
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: dateCols.map((c) => c.effective_date ?? c.label) },
      yAxis: { type: "value", name: yCol?.label },
      series: [
        {
          type: "line",
          data: dateCols.map((c) => Number(row[c.id] ?? 0)),
          smooth: true,
        },
      ],
    });
  } else {
    const yKey = chartYKey.value ?? numCols[0]?.id;
    const yCol = numCols.find((c) => c.id === yKey);
    if (!yKey) return;
    const top = result.value.items.slice(0, 20);
    chartInst.setOption({
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: top.map((r) => String(r.stock_code)),
        axisLabel: { rotate: 45 },
      },
      yAxis: { type: "value", name: yCol?.label },
      series: [{ type: "bar", data: top.map((r) => Number(r[yKey] ?? 0)) }],
    });
  }

  chartInst.off("click");
  chartInst.on("click", (params: unknown) => {
    const p = params as { name?: string; data?: { name?: string } | string };
    const code =
      p.name ??
      (typeof p.data === "object" && p.data?.name ? p.data.name : undefined);
    if (code) drillFilter.value = code;
  });
}

function prevPage() {
  if (page.value > 1) {
    page.value -= 1;
    runQuery();
  }
}

function nextPage() {
  if (page.value < maxPage.value) {
    page.value += 1;
    runQuery();
  }
}

watch(viewMode, async (m) => {
  if (m === "chart") {
    await nextTick();
    await renderChart();
  }
});

watch(chartType, async () => {
  if (viewMode.value === "chart") await renderChart();
});

watch([chartXKey, chartYKey], async () => {
  if (viewMode.value === "chart") await renderChart();
});

watch(
  () => ui.theme,
  async () => {
    if (!chartRef.value) return;
    chartInst = await disposeAndReinitChart(chartRef.value, chartInst, ui.theme);
    if (viewMode.value === "chart") await renderChart();
  },
);

watch(result, (r) => {
  const nums = (r?.columns ?? []).filter((c) => c.type === "number" && c.id !== "stock_code");
  if (!chartYKey.value && nums[0]) chartYKey.value = nums[0].id;
  if (!chartXKey.value && nums[1]) chartXKey.value = nums[1].id;
});

watch(selectedDimension, () => {
  if (universeMode.value === "preset") previewUniverse();
});
watch(universeMode, () => previewUniverse());
watch(customCodesText, () => {
  if (universeMode.value === "custom") previewUniverse();
});

onMounted(async () => {
  if (route.query.date) asOfDate.value = String(route.query.date);
  if (route.query.dim) selectedDimension.value = String(route.query.dim);
  if (route.query.page) page.value = Number(route.query.page) || 1;
  if (route.query.align) financialAlign.value = String(route.query.align) as "independent" | "unified";
  await auth.fetchMe().catch(() => undefined);
  await loadMeta();
  await previewUniverse();
  const tplId = route.query.tpl;
  if (tplId && meta.value) {
    const sysTpl = meta.value.system_templates.find((t) => t.id === tplId);
    if (sysTpl) {
      loadSystemTemplate(sysTpl, "replace");
    } else {
      const userTpl = userTemplates.value.find((t) => String(t.id) === String(tplId));
      if (userTpl) loadUserTemplate(userTpl, "replace");
    }
  }
  const share = route.query.share;
  const autoRun = route.query.auto === "1";
  if (share) {
    try {
      const payload = await apiRequest<Record<string, unknown>>(
        `/api/v1/query/browser/share/${share}`,
      );
      loadTemplatePayload(payload as Parameters<typeof loadTemplatePayload>[0], "replace");
      if (autoRun && selectedIndicators.value.length) {
        await runQuery();
      } else if (autoRun) {
        ui.showMessage("分享已加载，请点击提取数据", "info");
      }
    } catch {
      ui.showMessage("分享链接无效", "error");
    }
  }
});
</script>

<template>
  <div class="browser-page browser-page--wizard">
    <PageHeader
      title="数据浏览器"
      description="三选一提 · 灵活的数据提取与报表制作"
    />

    <BrowserReadinessPanel v-if="auth.isAdmin" compact />

    <nav class="browser-wizard" aria-label="提取步骤">
      <div class="browser-wizard__steps">
        <button
          v-for="step in WIZARD_STEPS"
          :key="step.key"
          type="button"
          class="browser-wizard__step"
          :class="stepStatus(step.key)"
          @click="goWizardStep(step.key)"
        >
          <span class="browser-wizard__num">{{ step.num }}</span>
          {{ step.label }}
        </button>
      </div>
      <div class="browser-wizard__bar">
        <div v-if="wizardPrevStep" class="browser-wizard__bar-start">
          <button
            type="button"
            class="btn btn--ghost btn--sm browser-wizard__nav-btn"
            @click="wizardStep = wizardPrevStep"
          >
            ← {{ wizardPrevLabel }}
          </button>
        </div>
        <div class="browser-wizard__bar-ctx">
          <span class="browser-tag browser-wizard__scope">{{ selectedDimensionLabel }}</span>
          <span v-if="universeCount != null" class="browser-wizard__meta">
            {{ universeEstimate ? "约 " : "" }}{{ universeCount.toLocaleString() }} 只
          </span>
          <template v-if="wizardStep !== 'scope'">
            <span class="browser-wizard__sep" aria-hidden="true">·</span>
            <span class="browser-wizard__meta">{{ selectedIndicators.length }} 项指标</span>
          </template>
          <template v-if="wizardStep === 'indicators' || wizardStep === 'time'">
            <span class="browser-wizard__sep" aria-hidden="true">·</span>
            <span class="browser-tag browser-wizard__date-tag" title="当前截面日期，可在「选时间」修改">
              {{ timeStepDateLabel }}
            </span>
          </template>
        </div>
        <div class="browser-wizard__bar-end">
          <button
            v-if="wizardStep === 'indicators' || wizardStep === 'time'"
            type="button"
            class="btn btn--primary browser-wizard__cta"
            :disabled="loadingData || !selectedIndicators.length"
            @click="runQuery"
          >
            提取数据
            <span v-if="extractSummary" class="browser-wizard__hint muted">{{ extractSummary }}</span>
            <span v-if="timeMode === 'single'" class="browser-wizard__hint muted">· 截面 {{ asOfDate }}</span>
          </button>
          <button
            v-if="wizardStep === 'scope'"
            type="button"
            class="btn btn--primary browser-wizard__cta"
            :disabled="(universeCount ?? 0) <= 0"
            @click="wizardStep = 'indicators'"
          >
            下一步：{{ wizardNextLabel }} →
          </button>
          <button
            v-else-if="wizardNextStep"
            type="button"
            class="btn btn--ghost btn--sm browser-wizard__nav-btn"
            @click="wizardStep = wizardNextStep"
          >
            {{ wizardNextLabel }} →
          </button>
        </div>
      </div>
    </nav>

    <div class="browser-step-host">
    <Transition name="browser-step" mode="out-in">
    <div
      :key="wizardStep"
      class="browser-layout"
      :class="{
        'browser-layout--triple': wizardStep === 'indicators',
        'browser-layout--split': wizardStep !== 'indicators',
      }"
    >
      <aside v-if="wizardStep !== 'indicators'" class="browser-side panel">
        <div class="panel__header browser-side__header">
          <span>{{ wizardStepLabel }}</span>
        </div>
        <div class="panel__body browser-side__body">
          <!-- ① 选范围 -->
          <template v-if="wizardStep === 'scope'">
            <div class="browser-scope-mode">
              <label class="browser-radio">
                <input v-model="universeMode" type="radio" value="preset" /> 预设范围
              </label>
              <label class="browser-radio">
                <input v-model="universeMode" type="radio" value="custom" /> 自定义代码
              </label>
            </div>

            <template v-if="universeMode === 'preset'">
              <BrowserDimensionPicker
                v-model="selectedDimension"
                :dimensions="dimensions"
                :categories="meta?.dimension_categories ?? {}"
              >
                <template #watchlists>
                  <div v-if="userWatchlists.length" class="browser-dim-group">
                    <div class="browser-tpl-section">自定义板块</div>
                    <ul class="browser-tree">
                      <li
                        v-for="wl in userWatchlists"
                        :key="wl.id"
                        class="browser-tree__item"
                        :class="{ active: selectedDimension === `watchlist:${wl.id}` }"
                      >
                        <span @click="selectedDimension = `watchlist:${wl.id}`">
                          {{ wl.name }}
                          <span class="muted">({{ wl.codes.length }})</span>
                        </span>
                        <button
                          type="button"
                          class="btn btn--ghost btn--sm"
                          @click.stop="deleteWatchlist(wl.id)"
                        >
                          删
                        </button>
                      </li>
                    </ul>
                  </div>
                </template>
              </BrowserDimensionPicker>
            </template>

            <template v-else>
              <textarea
                v-model="customCodesText"
                class="input browser-codes-input"
                placeholder="粘贴证券代码，支持换行/逗号分隔&#10;例：000001.SZ&#10;600900.SH"
                rows="8"
              />
            </template>

            <div v-if="universeCount != null" class="browser-universe-preview">
              预计 <strong>{{ universeEstimate ? "约 " : "" }}{{ universeCount.toLocaleString() }}</strong> 只证券
              <div v-if="universeSampleCodes.length" class="muted">
                样例：{{ universeSampleCodes.join(", ") }}
              </div>
              <div v-for="w in universeWarnings" :key="w" class="browser-warn">{{ w }}</div>
            </div>
          </template>

          <!-- ③ 选时间 -->
          <template v-else>
            <div class="browser-time-form">
              <label class="browser-field">
                <span>截面模式</span>
                <select v-model="timeMode" class="input">
                  <option value="single">单截面</option>
                  <option value="multi">多截面（实验，最多 5 日）</option>
                </select>
              </label>
              <label v-if="timeMode === 'single'" class="browser-field">
                <span>截面日期</span>
                <input v-model="asOfDate" type="date" class="input" />
              </label>
              <label v-else class="browser-field">
                <span>截面日期列表</span>
                <textarea
                  v-model="multiDatesText"
                  class="input browser-codes-input"
                  placeholder="每行一个日期&#10;2024-11-18&#10;2024-11-19"
                  rows="4"
                />
              </label>
              <p class="browser-field-hint muted">
                日频指标取该日或之前最近交易日；期频指标取最近报告期。
              </p>
              <label class="browser-field">
                <span>财报对齐</span>
                <select v-model="financialAlign" class="input">
                  <option value="independent">各指标独立对齐（推荐）</option>
                  <option value="unified">统一截止日</option>
                </select>
              </label>
              <label v-if="financialAlign === 'unified'" class="browser-field">
                <span>统一截止日</span>
                <input v-model="unifiedEndDate" type="date" class="input" />
              </label>
              <p class="browser-field-hint muted">
                当前为截面宽表模式；周/月/年频时序面板列为后续能力。
              </p>
              <p class="browser-field-hint muted">
                多截面模式仅支持日频指标；期频指标请使用单截面。
              </p>
            </div>
          </template>
        </div>
      </aside>

      <main
        class="browser-main"
        :class="{
          'browser-main--triple': wizardStep === 'indicators',
          'browser-main--split': wizardStep !== 'indicators',
        }"
      >
        <template v-if="wizardStep === 'indicators'">
          <div class="browser-triple-body panel">
            <section class="browser-triple-pane">
              <header class="browser-triple-pane__head">浏览指标</header>
              <BrowserIndicatorPicker
                embedded
                class="browser-triple-pane__content"
                :indicators-flat="flatIndicators"
                :indicator-tree="indicatorTree"
                :domains="meta?.domains ?? []"
                :selected-ids="selectedIndicatorIds"
                :loading="loadingMeta"
                :time-mode="timeMode"
                @pick="toggleIndicator"
              />
            </section>

            <section class="browser-triple-pane">
              <header class="browser-triple-pane__head">
                已选篮
                <span class="browser-triple-pane__badge">{{ selectedIndicators.length }}/40</span>
              </header>
              <BrowserIndicatorBasket
                v-model="selectedIndicators"
                embedded
                class="browser-triple-pane__content"
                :indicators-flat="flatIndicators"
                :system-templates="systemTemplates"
                :user-templates="userTemplates"
                :time-mode="timeMode"
                @load-system="loadSystemTemplate"
                @load-user="loadUserTemplate"
                @delete-user="deleteUserTemplate"
                @next-step="wizardStep = 'time'"
                @drag-rejected="onDragRejected"
              />
            </section>

            <section class="browser-triple-pane browser-triple-pane--data">
              <header class="browser-triple-pane__head">数据预览</header>
              <div class="browser-triple-pane__content browser-triple-data">
                <BrowserDataToolbar
                  :loading-data="loadingData"
                  :has-indicators="selectedIndicators.length > 0"
                  :cache-hit="cacheHit"
                  :has-result="!!result"
                  :export-format="exportFormat"
                  :view-mode="viewMode"
                  @refresh="forceRefreshQuery"
                  @export="exportCsv(false)"
                  @save-template="saveTemplate"
                  @share="shareQuery"
                  @update:export-format="exportFormat = $event"
                  @update:view-mode="viewMode = $event"
                />
                <div class="browser-data-region">
                  <div v-if="loadingMeta" class="muted browser-main-empty">加载元数据…</div>
                  <div v-else-if="loadingData" class="muted browser-main-empty">查询中…</div>
                  <div v-else-if="viewMode === 'table' && result" class="panel browser-table-panel">
                    <div class="panel__header">
                      <span>{{ result.total.toLocaleString() }} 行</span>
                      <span v-if="result.meta.date_adjusted" class="muted">
                        交易日 {{ result.meta.effective_date }}
                      </span>
                    </div>
                    <div class="panel__body table-scroll">
                      <table class="data-table">
                        <thead>
                          <tr>
                            <th
                              v-for="col in result.columns"
                              :key="col.id"
                              class="browser-th-sort"
                              @click="toggleSort(col.id)"
                            >
                              {{ col.label }}
                              <span v-if="sortCol === col.id">{{ sortAsc ? "↑" : "↓" }}</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="(row, idx) in displayRows" :key="idx">
                            <td
                              v-for="col in result.columns"
                              :key="col.id"
                              :class="{ numeric: col.type === 'number' }"
                            >
                              {{ formatCell(row[col.id]) }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div v-if="result.total > pageSize" class="pager">
                      <button type="button" class="btn btn--ghost btn--sm" :disabled="page <= 1" @click="prevPage">
                        上一页
                      </button>
                      <span class="pager__info">{{ pageRangeLabel }}</span>
                      <button
                        type="button"
                        class="btn btn--ghost btn--sm"
                        :disabled="page >= maxPage"
                        @click="nextPage"
                      >
                        下一页
                      </button>
                    </div>
                  </div>
                  <div v-else-if="viewMode === 'chart' && result" class="browser-chart-wrap">
                    <div v-if="numericResultColumns.length" class="browser-chart-controls">
                      <select v-model="chartYKey" class="input input--inline">
                        <option v-for="c in numericResultColumns" :key="c.id" :value="c.id">{{ c.label }}</option>
                      </select>
                    </div>
                    <div ref="chartRef" class="browser-chart" />
                  </div>
                  <p v-else class="muted browser-main-empty">
                    选好指标后点击「提取数据」，宽表将显示于此
                  </p>
                </div>
              </div>
            </section>
          </div>
        </template>

        <template v-else>
          <div class="browser-preview panel">
            <header class="browser-triple-pane__head browser-triple-pane--data">
              数据预览
              <span v-if="selectedIndicators.length" class="browser-triple-pane__badge">
                {{ selectedIndicators.length }} 项
              </span>
            </header>
            <div class="browser-triple-pane__content browser-triple-data">
              <button
                v-if="selectedIndicators.length"
                type="button"
                class="browser-ind-summary browser-ind-summary--inline"
                @click="wizardStep = 'indicators'"
              >
                已选 {{ selectedIndicators.length }} 项：{{ selectedSummaryLabels }} ▸
              </button>

              <BrowserDataToolbar
                :loading-data="loadingData"
                :has-indicators="selectedIndicators.length > 0"
                :has-universe="(universeCount ?? 0) > 0"
                :cache-hit="cacheHit"
                :has-result="!!result"
                :export-format="exportFormat"
                :view-mode="viewMode"
                extended
                :export-download-url="exportDownloadUrl"
                @refresh="forceRefreshQuery"
                @export="exportCsv(false)"
                @export-async="exportCsv(true)"
                @save-template="saveTemplate"
                @share="shareQuery"
                @save-watchlist="saveWatchlist"
                @load-audits="loadAudits"
                @update:export-format="exportFormat = $event"
                @update:view-mode="viewMode = $event"
              />

              <div class="browser-data-region">
        <div v-if="pageAggregations.length" class="browser-stats panel">
          <div class="browser-stats__head">
            <span class="browser-stats__title">统计</span>
            <select v-model="aggScope" class="input input--inline">
              <option value="full">全量</option>
              <option value="page">当前页</option>
            </select>
          </div>
          <div class="browser-stats__grid">
            <div v-for="agg in pageAggregations" :key="agg.column_id" class="browser-stats__card">
              <p class="browser-stats__card-label">{{ indicatorLabel(agg.column_id) }}</p>
              <div class="browser-stats__card-values">
                <span class="browser-stats__metric">
                  <span class="browser-stats__metric-key">avg</span>
                  <span class="browser-stats__metric-val numeric">{{ formatStatValue(agg.avg) }}</span>
                </span>
                <span class="browser-stats__metric">
                  <span class="browser-stats__metric-key">max</span>
                  <span class="browser-stats__metric-val numeric">{{ formatStatValue(agg.max) }}</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="drillFilter" class="browser-drill">
          图表下钻：{{ drillFilter }}
          <button type="button" class="btn btn--ghost btn--sm" @click="drillFilter = null">清除</button>
        </div>

        <div v-if="loadingMeta" class="muted browser-main-empty">加载元数据…</div>
        <div v-else-if="loadingData" class="muted browser-main-empty">查询中…</div>

        <div v-else-if="viewMode === 'table' && result" class="panel browser-table-panel">
          <div class="panel__header">
            <span>数据视图</span>
            <span v-if="result.meta.date_adjusted" class="muted">
              交易日 {{ result.meta.effective_date }}
            </span>
            <span class="panel__header-count numeric">{{ result.total.toLocaleString() }} 行</span>
          </div>
          <div class="panel__body table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th
                    v-for="col in result.columns"
                    :key="col.id"
                    class="browser-th-sort"
                    @click="toggleSort(col.id)"
                  >
                    {{ col.label }}
                    <span v-if="col.unit" class="muted">({{ col.unit }})</span>
                    <span v-if="col.effective_date" class="muted">[{{ col.effective_date }}]</span>
                    <span v-if="sortCol === col.id">{{ sortAsc ? "↑" : "↓" }}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in displayRows" :key="idx">
                  <td
                    v-for="col in result.columns"
                    :key="col.id"
                    :class="{ numeric: col.type === 'number' }"
                  >
                    {{ formatCell(row[col.id]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="result.total > pageSize" class="pager">
            <select v-model.number="pageSize" class="input input--inline" @change="onPageSizeChange">
              <option :value="50">50 条/页</option>
              <option :value="100">100 条/页</option>
              <option :value="200">200 条/页</option>
              <option :value="500">500 条/页</option>
            </select>
            <button type="button" class="btn btn--ghost btn--sm" :disabled="page <= 1" @click="prevPage">
              上一页
            </button>
            <span class="pager__info">{{ pageRangeLabel }} · 第 {{ page }} / {{ maxPage }} 页</span>
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="page >= maxPage"
              @click="nextPage"
            >
              下一页
            </button>
          </div>
        </div>

        <div v-else-if="viewMode === 'chart'" class="browser-chart-wrap">
          <div v-if="numericResultColumns.length" class="browser-chart-controls">
            <select v-model="chartType" class="input input--inline">
              <option value="bar">柱状图</option>
              <option value="scatter">散点图</option>
              <option v-if="result?.meta.multi_date_mode" value="line">折线图</option>
            </select>
            <template v-if="chartType === 'scatter'">
              <label class="browser-chart-label">X</label>
              <select v-model="chartXKey" class="input input--inline">
                <option v-for="c in numericResultColumns" :key="c.id" :value="c.id">{{ c.label }}</option>
              </select>
              <label class="browser-chart-label">Y</label>
              <select v-model="chartYKey" class="input input--inline">
                <option v-for="c in numericResultColumns" :key="c.id" :value="c.id">{{ c.label }}</option>
              </select>
            </template>
            <template v-else>
              <label class="browser-chart-label">指标</label>
              <select v-model="chartYKey" class="input input--inline">
                <option v-for="c in numericResultColumns" :key="c.id" :value="c.id">{{ c.label }}</option>
              </select>
            </template>
          </div>
          <div ref="chartRef" class="browser-chart" />
        </div>
        <p v-else class="muted browser-main-empty">
          <template v-if="wizardStep === 'scope'">
            在左侧选择证券范围，完成后点击顶栏「下一步：选指标」。
            <template v-if="universeCount != null">
              <br />
              当前范围：<strong>{{ selectedDimensionLabel }}</strong>，约
              {{ universeCount.toLocaleString() }} 只证券
            </template>
          </template>
          <template v-else-if="wizardStep === 'time'">
            在左侧配置截面日期，完成后点击顶栏「提取数据」。
          </template>
          <template v-else>完成三选后点击「提取数据」生成宽表报表</template>
        </p>
              </div>
            </div>
          </div>
        </template>
      </main>
    </div>
    </Transition>
    </div>

    <div v-if="modalOpen" class="browser-modal-backdrop" @click.self="modalOpen = false">
      <div class="browser-modal panel">
        <div class="panel__header">{{ modalType === "template" ? "保存模板" : "保存证券池" }}</div>
        <div class="panel__body">
          <input v-model="modalName" class="input" placeholder="名称" @keyup.enter="confirmSaveModal" />
          <div class="browser-modal__actions">
            <button type="button" class="btn btn--ghost" @click="modalOpen = false">取消</button>
            <button type="button" class="btn btn--primary" @click="confirmSaveModal">保存</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showAudit" class="browser-modal-backdrop" @click.self="showAudit = false">
      <div class="browser-modal panel browser-modal--wide">
        <div class="panel__header">
          最近查询审计
          <button type="button" class="btn btn--ghost btn--sm" @click="showAudit = false">关闭</button>
        </div>
        <div class="panel__body table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>日期</th>
                <th>指标数</th>
                <th>行数</th>
                <th>耗时 ms</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in auditItems" :key="a.id">
                <td>{{ a.created_at?.slice(0, 19) }}</td>
                <td>{{ a.as_of_date }}</td>
                <td class="numeric">{{ a.indicator_ids.length }}</td>
                <td class="numeric">{{ a.row_count }}</td>
                <td class="numeric">{{ a.duration_ms }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.browser-page {
  color: var(--color-text);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.browser-page--wizard {
  flex: 1;
  min-height: 0;
  height: calc(100vh - 88px);
  max-height: calc(100vh - 88px);
  overflow: hidden;
}

.browser-step-host {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.browser-step-host :deep(.browser-layout) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.browser-page--wizard :deep(.page-header) {
  margin-bottom: var(--space-sm);
  padding-bottom: var(--space-xs);
}

.browser-wizard {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-xs);
  margin-bottom: var(--space-sm);
  flex-shrink: 0;
}

.browser-wizard__steps {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.browser-wizard__bar {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  min-height: 44px;
  padding: var(--space-xs) var(--space-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
}

.browser-wizard__bar-start,
.browser-wizard__bar-end {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-shrink: 0;
}

.browser-wizard__bar-ctx {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

.browser-wizard__meta {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  white-space: nowrap;
}

.browser-wizard__sep {
  color: var(--color-text-muted);
  user-select: none;
}

.browser-wizard__nav-btn,
.browser-wizard__cta {
  white-space: nowrap;
}

.browser-wizard__scope {
  max-width: min(240px, 28vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.browser-wizard__count {
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

.browser-wizard__date-tag {
  max-width: min(200px, 24vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.browser-wizard__hint {
  font-size: var(--font-size-sm);
  font-weight: 400;
  margin-left: 4px;
}

.browser-step-enter-active,
.browser-step-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.browser-step-enter-from,
.browser-step-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@media (prefers-reduced-motion: reduce) {
  .browser-step-enter-active,
  .browser-step-leave-active {
    transition: none;
  }

  .browser-step-enter-from,
  .browser-step-leave-to {
    transform: none;
  }
}

.browser-wizard__step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  font-size: var(--font-size-md);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.browser-wizard__step:hover:not(.active) {
  color: var(--color-text);
  border-color: var(--color-border-strong);
  background: var(--color-surface-elevated);
}

.browser-wizard__step.active {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-weight: 600;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-primary) 25%, transparent);
}

.browser-wizard__step.done:not(.active) {
  border-color: color-mix(in srgb, var(--color-primary) 35%, var(--color-border));
  color: var(--color-text);
  font-weight: 500;
}

.browser-wizard__step.pending {
  opacity: 0.92;
}

.browser-wizard__num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: var(--font-size-sm);
  font-weight: 600;
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  border: 1px solid var(--color-border);
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

.browser-wizard__step.active .browser-wizard__num {
  background: var(--color-primary);
  color: var(--color-on-primary);
  border-color: var(--color-primary);
}

.browser-wizard__step.done:not(.active) .browser-wizard__num {
  background: var(--color-primary);
  color: var(--color-on-primary);
  border-color: var(--color-primary);
}

.browser-wizard__step.pending .browser-wizard__num {
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  border-color: var(--color-border);
}

.browser-side__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.browser-scope-mode {
  display: flex;
  gap: var(--space-md);
  margin-bottom: var(--space-sm);
  font-size: var(--font-size-md);
}

.browser-radio,
.browser-check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-md);
  color: var(--color-text);
  cursor: pointer;
}

.browser-dim-group {
  margin-bottom: var(--space-sm);
}

.browser-tree__hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin-left: 4px;
}

.browser-codes-input {
  width: 100%;
  min-height: 120px;
  font-family: var(--font-mono);
  font-size: var(--font-size-md);
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-input);
}

.browser-universe-preview {
  font-size: 12px;
  margin: var(--space-sm) 0;
}

.btn--block {
  width: 100%;
  margin-top: var(--space-sm);
}

.browser-indicator-toolbar {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin-bottom: var(--space-sm);
}

.browser-time-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.browser-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--font-size-md);
  color: var(--color-text);
  font-weight: 500;
}

.browser-field-hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.45;
  margin: 0;
}

.browser-layout {
  flex: 1;
  min-height: 0;
}

.browser-layout.browser-layout--split {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: var(--space-md);
}

.browser-layout.browser-layout--triple {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.browser-layout--split .browser-side {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.browser-main.browser-main--split {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: var(--space-sm);
}

.browser-preview {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}

.browser-preview {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}

.browser-preview .browser-data-region {
  flex: 1;
  min-height: 0;
}

.browser-preview .browser-chart {
  flex: 1;
  min-height: 200px;
  height: auto;
}

.browser-ind-summary--inline {
  margin: var(--space-xs) var(--space-sm) 0;
  flex-shrink: 0;
}

.browser-main.browser-main--triple {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 0;
}

.browser-triple-body {
  display: grid;
  grid-template-columns: minmax(240px, 28%) minmax(200px, 22%) minmax(320px, 50%);
  flex: 1;
  min-height: 360px;
  height: 100%;
  overflow: hidden;
  padding: 0;
}

@media (max-width: 1280px) {
  .browser-triple-body {
    grid-template-columns: minmax(200px, 30%) minmax(180px, 24%) minmax(280px, 46%);
  }
}

.browser-triple-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
}

.browser-triple-pane:last-child {
  border-right: none;
}

.browser-triple-pane__head {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-shrink: 0;
  padding: var(--space-sm) var(--space-md);
  font-weight: 600;
  font-size: var(--font-size-md);
  color: var(--color-text);
  background: var(--color-surface-elevated);
  border-bottom: 1px solid var(--color-border);
}

.browser-triple-pane--data .browser-triple-pane__head {
  color: var(--color-primary);
}

.browser-triple-pane__badge {
  margin-left: auto;
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text-muted);
}

.browser-triple-pane__content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.browser-triple-data {
  gap: var(--space-xs);
}

.browser-toolbar--triple-data {
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 6px;
  padding: var(--space-xs) var(--space-sm);
  margin: 0;
  border-bottom: 1px solid var(--color-border);
}

.browser-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: var(--space-sm);
}

.browser-data-region {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 280px;
  min-width: 0;
}

.browser-col-data {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
  gap: var(--space-sm);
}

.browser-toolbar--compact {
  flex-wrap: wrap;
  gap: 6px;
  padding: var(--space-xs) 0;
}

.browser-toolbar--compact .browser-toolbar__label {
  display: none;
}

.browser-triple-data .browser-data-region {
  min-height: 0;
}

.browser-triple-data .browser-chart {
  flex: 1;
  min-height: 200px;
  height: auto;
}

.browser-main--triple :deep(.ind-picker--embedded),
.browser-main--triple :deep(.ind-basket--embedded) {
  border: none;
  box-shadow: none;
  border-radius: 0;
  height: 100%;
}

.browser-main-empty {
  flex: 1;
  padding: var(--space-lg);
  text-align: center;
}

.browser-ind-summary {
  display: block;
  width: 100%;
  text-align: left;
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-sm);
  font-size: var(--font-size-md);
  color: var(--color-primary);
  background: var(--color-primary-muted);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.browser-side__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.browser-tree {
  list-style: none;
  margin: 0;
  padding: 0;
}

.browser-tree__item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  font-size: var(--font-size-md);
  color: var(--color-text);
  cursor: pointer;
  border-radius: var(--radius-sm);
}

.browser-tree__item:hover,
.browser-tree__item.active {
  background: var(--color-surface-elevated);
}

.browser-tree__actions {
  display: flex;
  gap: 2px;
}

.browser-tpl-section {
  font-size: var(--font-size-sm);
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--color-text-secondary);
  margin-top: var(--space-sm);
  text-transform: uppercase;
}

.browser-toolbar__label {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text);
}

.browser-toolbar {
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.browser-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: var(--space-sm);
  min-height: 28px;
}

.browser-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  font-size: var(--font-size-sm);
  color: var(--color-text);
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: grab;
}

.browser-tag__x {
  border: none;
  background: none;
  cursor: pointer;
  padding: 0 2px;
}

.browser-stats {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-sm);
  font-size: var(--font-size-sm);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
}

.browser-stats__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}

.browser-stats__title {
  font-weight: 600;
  color: var(--color-text);
}

.browser-stats__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: var(--space-sm);
}

.browser-stats__card {
  padding: var(--space-sm) var(--space-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  min-width: 0;
}

.browser-stats__card-label {
  margin: 0 0 var(--space-xs);
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.browser-stats__card-values {
  display: flex;
  gap: var(--space-md);
}

.browser-stats__metric {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.browser-stats__metric-key {
  font-size: 10px;
  color: var(--color-text-muted);
  letter-spacing: 0.02em;
}

.browser-stats__metric-val {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.browser-chart-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  flex: 1;
  min-height: 280px;
}

.browser-chart-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  font-size: 12px;
}

.browser-chart-label {
  color: var(--color-text-muted);
  font-size: 11px;
}

.browser-tag__adj {
  font-size: 10px;
  padding: 0 2px;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.browser-chart {
  height: 400px;
  width: 100%;
}

.browser-drill {
  font-size: 12px;
  margin-bottom: var(--space-sm);
}

.browser-th-sort {
  cursor: pointer;
  user-select: none;
}

.browser-table-panel {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
}

.browser-table-panel .panel__body {
  flex: 1;
  min-height: 0;
}

.browser-wizard__hint {
  font-size: 11px;
  font-weight: 400;
  margin-left: 6px;
}

.browser-tag-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.browser-chip {
  padding: 2px 8px;
  font-size: 11px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  cursor: pointer;
}

.browser-chip.active {
  background: var(--color-primary-muted);
  border-color: var(--color-primary);
}

.browser-badge {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 4px;
}

.browser-badge--warn {
  background: var(--color-warn-bg);
  color: var(--color-warn-text);
}

.browser-tree__item--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.browser-warn {
  color: var(--color-warn-text);
  font-size: 11px;
}

.browser-modal-backdrop {
  position: fixed;
  inset: 0;
  background: var(--color-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.browser-modal {
  width: min(420px, 92vw);
}

.browser-modal--wide {
  width: min(720px, 96vw);
  max-height: 80vh;
  overflow: auto;
}

.browser-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
}
</style>
