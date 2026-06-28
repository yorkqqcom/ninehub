<script setup lang="ts">
import { onMounted, onUnmounted, ref, nextTick, computed, watch } from "vue";
import { useRouter, useRoute } from "vue-router";
import { apiRequest, getToken, getApiBase, ApiError } from "@/api/client";
import type { PlatformJob } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SchemaMaintenanceDrawer from "@/components/tia/SchemaMaintenanceDrawer.vue";
import {
  BATCH_GOVERNANCE_MAX,
  batchKindLabel,
  useTiaBatchGovernance,
} from "@/composables/useTiaBatchGovernance";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const job = ref<PlatformJob | null>(null);
const scanResult = ref<Record<string, unknown> | null>(null);
const auditResult = ref<Record<string, unknown> | null>(null);
const proposals = ref<Array<Record<string, unknown>>>([]);
const proposalTotal = ref(0);
const proposalPage = ref(1);
const proposalPageSize = ref(50);
const proposalStatusFilter = ref("");
const proposalSearch = ref("");
const proposalPointsMin = ref("");
const proposalPointsMax = ref("");
const proposalActivePointsMin = ref<number | null>(null);
const proposalActivePointsMax = ref<number | null>(null);
const proposalSummary = ref<Record<string, number> | null>(null);
const proposalLoading = ref(false);
const expandedProposalId = ref<number | null>(null);
const selectedProposalIds = ref<number[]>([]);
const selectionScope = ref<"none" | "page" | "all_filtered">("none");
const selectAllFilteredLoading = ref(false);
const headerSelectRef = ref<HTMLInputElement | null>(null);
const proposalsPanelRef = ref<HTMLElement | null>(null);
const scanInProgress = ref(false);
const jobPollStuck = ref(false);
let jobPollCount = 0;
const activateJobId = ref<number | null>(null);
let pollTimer: number | undefined;

const SCAN_PROVIDER_STORAGE_KEY = "ninehub.tiaScanProvider";
const scanProvider = ref<"tushare" | "tdx">("tushare");
const scanProviders = ref<string[]>(["tushare", "tdx"]);
const tdxSidecarProbe = ref(false);
const tdxReadiness = ref<Record<string, unknown> | null>(null);
const tdxReadinessLoading = ref(false);

const isTdxProvider = computed(() => scanProvider.value === "tdx");
const isTushareProvider = computed(() => scanProvider.value === "tushare");

const {
  batchOp,
  batchBusy,
  batchProgressPct,
  batchSummary,
  restoreBatch,
  dismissBatchPanel,
  retryBatchFailed,
  runBatchApprove,
  runBatchActivateL3,
  runBatchEnableBrowse,
  runSingleL3Job,
} = useTiaBatchGovernance(() => loadProposals());

function openStandards(apiName: string) {
  void router.push({ name: "standards", query: { api: apiName } });
}

onMounted(() => {
  loadPointsPrefs();
  const stored = localStorage.getItem(SCAN_PROVIDER_STORAGE_KEY);
  if (stored === "tdx" || stored === "tushare") {
    scanProvider.value = stored;
  } else if (route.query.provider === "tdx") {
    scanProvider.value = "tdx";
  }
  void loadScanProviders();
  void loadProposals();
  if (scanProvider.value === "tdx") {
    void loadTdxReadiness();
  }
  restoreBatch();
  const proposalQ = route.query.proposal;
  if (proposalQ) {
    const pid = Number(proposalQ);
    if (!Number.isNaN(pid)) {
      expandedProposalId.value = pid;
      nextTick(() => {
        proposalsPanelRef.value?.scrollIntoView({ behavior: "smooth" });
        void loadProposalDetail(pid);
      });
    }
  }
});

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});

async function loadProposals(page = proposalPage.value) {
  proposalLoading.value = true;
  try {
    const params = buildProposalQueryParams({
      skip: (page - 1) * proposalPageSize.value,
      limit: proposalPageSize.value,
      includeSummary: true,
    });
    const data = await apiRequest<{
      items: Array<Record<string, unknown>>;
      total: number;
      page: number;
      summary?: Record<string, number>;
    }>(`/api/v1/tia/proposals?${params.toString()}`);
    proposals.value = data.items;
    proposalTotal.value = data.total;
    proposalPage.value = data.page;
    proposalSummary.value = data.summary ?? null;
  } finally {
    proposalLoading.value = false;
  }
}

function buildProposalQueryParams(opts: {
  skip?: number;
  limit?: number;
  includeSummary?: boolean;
}) {
  const params = new URLSearchParams();
  params.set("skip", String(opts.skip ?? 0));
  params.set("limit", String(opts.limit ?? proposalPageSize.value));
  params.set("include_summary", String(opts.includeSummary ?? false));
  if (proposalStatusFilter.value) params.set("status", proposalStatusFilter.value);
  if (proposalSearch.value.trim()) params.set("q", proposalSearch.value.trim());
  if (proposalActivePointsMin.value != null) {
    params.set("min_points_gte", String(proposalActivePointsMin.value));
  }
  if (proposalActivePointsMax.value != null) {
    params.set("min_points_lte", String(proposalActivePointsMax.value));
  }
  if (scanProvider.value) params.set("provider", scanProvider.value);
  return params;
}

async function loadScanProviders() {
  try {
    const data = await apiRequest<{ providers: string[] }>("/api/v1/tia/scan/providers");
    const allowed = (data.providers || []).filter((p) => p === "tushare" || p === "tdx");
    if (allowed.length) scanProviders.value = allowed;
  } catch {
    scanProviders.value = ["tushare", "tdx"];
  }
}

async function loadTdxReadiness() {
  tdxReadinessLoading.value = true;
  try {
    tdxReadiness.value = await apiRequest<Record<string, unknown>>("/api/v1/tia/tdx-readiness");
  } catch {
    tdxReadiness.value = null;
  } finally {
    tdxReadinessLoading.value = false;
  }
}

function providerTabLabel(id: string) {
  if (id === "tdx") return "通达信 (TDX)";
  if (id === "tushare") return "Tushare";
  return id;
}

function switchScanProvider(provider: "tushare" | "tdx") {
  if (scanProvider.value === provider) return;
  scanProvider.value = provider;
  localStorage.setItem(SCAN_PROVIDER_STORAGE_KEY, provider);
  scanResult.value = null;
  auditResult.value = null;
  clearProposalSelection();
  proposalPage.value = 1;
  if (provider === "tdx") {
    void loadTdxReadiness();
  }
  void loadProposals(1);
}

function goSourcesPage() {
  void router.push({ name: "sources" });
}

async function fetchAllFilteredProposals() {
  const pageSize = 500;
  let skip = 0;
  const all: Array<Record<string, unknown>> = [];
  while (true) {
    const params = buildProposalQueryParams({ skip, limit: pageSize, includeSummary: false });
    const data = await apiRequest<{ items: Array<Record<string, unknown>>; total: number }>(
      `/api/v1/tia/proposals?${params.toString()}`,
    );
    all.push(...data.items);
    if (all.length >= data.total || data.items.length === 0) break;
    skip += pageSize;
  }
  return all;
}

function clearProposalSelection() {
  selectedProposalIds.value = [];
  selectionScope.value = "none";
}

function onProposalFilterChange() {
  clearProposalSelection();
  proposalPage.value = 1;
  void loadProposals(1);
}

function onProposalSearch() {
  clearProposalSelection();
  proposalPage.value = 1;
  void loadProposals(1);
}

function proposalPrevPage() {
  if (proposalPage.value <= 1) return;
  void loadProposals(proposalPage.value - 1);
}

function proposalNextPage() {
  const maxPage = Math.max(1, Math.ceil(proposalTotal.value / proposalPageSize.value));
  if (proposalPage.value >= maxPage) return;
  void loadProposals(proposalPage.value + 1);
}

function toggleProposalDetail(id: number) {
  if (expandedProposalId.value === id) {
    expandedProposalId.value = null;
    return;
  }
  expandedProposalId.value = id;
  const row = proposals.value.find((p) => proposalRowId(p) === id);
  if (row && !row.description && !row.input_params) {
    void loadProposalDetail(id);
  }
}

async function loadProposalDetail(proposalId: number) {
  try {
    const detail = await apiRequest<Record<string, unknown>>(`/api/v1/tia/proposals/${proposalId}`);
    applyProposalRowUpdate(proposalId, detail);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : "加载详情失败", "error");
  }
}

function formatProposalTime(value: unknown) {
  if (!value) return "—";
  const d = new Date(String(value));
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

const PROPOSAL_STATUS_TABS = [
  { key: "", label: "全部" },
  { key: "pending", label: "待审" },
  { key: "approved", label: "已批准" },
  { key: "applied", label: "已激活" },
  { key: "rejected", label: "已拒绝" },
  { key: "failed", label: "激活失败" },
] as const;

const POINTS_PREFS_KEY = "ninehub.tiaProposalPointsFilter";

function loadPointsPrefs() {
  try {
    const raw = localStorage.getItem(POINTS_PREFS_KEY);
    if (!raw) return;
    const p = JSON.parse(raw) as { min?: string | number; max?: string | number };
    if (p.min !== undefined && p.min !== null) proposalPointsMin.value = String(p.min);
    if (p.max !== undefined && p.max !== null) proposalPointsMax.value = String(p.max);
    const gte = parsePointsInput(proposalPointsMin.value);
    const lte = parsePointsInput(proposalPointsMax.value);
    if (pointsInputFilled(proposalPointsMin.value) && gte === null) return;
    if (pointsInputFilled(proposalPointsMax.value) && lte === null) return;
    if (gte != null && lte != null && gte > lte) return;
    proposalActivePointsMin.value = gte;
    proposalActivePointsMax.value = lte;
  } catch {
    /* ignore */
  }
}

function savePointsPrefs() {
  localStorage.setItem(
    POINTS_PREFS_KEY,
    JSON.stringify({ min: proposalPointsMin.value, max: proposalPointsMax.value }),
  );
}

function pointsInputFilled(raw: unknown): boolean {
  if (raw === null || raw === undefined || raw === "") return false;
  if (typeof raw === "number") return !Number.isNaN(raw);
  return String(raw).trim() !== "";
}

function parsePointsInput(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  if (typeof raw === "number") {
    if (!Number.isFinite(raw) || raw < 0 || !Number.isInteger(raw)) return null;
    return raw;
  }
  const trimmed = String(raw).trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) return null;
  return n;
}

function applyCustomPointsFilter(showToast = true) {
  const gte = parsePointsInput(proposalPointsMin.value);
  const lte = parsePointsInput(proposalPointsMax.value);
  if (pointsInputFilled(proposalPointsMin.value) && gte === null) {
    if (showToast) ui.showMessage("最低积分须为非负整数", "error");
    return;
  }
  if (pointsInputFilled(proposalPointsMax.value) && lte === null) {
    if (showToast) ui.showMessage("最高积分须为非负整数", "error");
    return;
  }
  if (gte != null && lte != null && gte > lte) {
    if (showToast) ui.showMessage("最低积分不能大于最高积分", "error");
    return;
  }
  proposalActivePointsMin.value = gte;
  proposalActivePointsMax.value = lte;
  savePointsPrefs();
  onProposalFilterChange();
}

function clearPointsFilter() {
  proposalPointsMin.value = "";
  proposalPointsMax.value = "";
  proposalActivePointsMin.value = null;
  proposalActivePointsMax.value = null;
  localStorage.removeItem(POINTS_PREFS_KEY);
  onProposalFilterChange();
}

const pointsFilterActive = computed(
  () => proposalActivePointsMin.value != null || proposalActivePointsMax.value != null,
);

const pointsFilterLabel = computed(() => {
  const min = proposalActivePointsMin.value;
  const max = proposalActivePointsMax.value;
  if (min != null && max != null) return `${min} – ${max}`;
  if (min != null) return `≥ ${min}`;
  if (max != null) return `≤ ${max}`;
  return "";
});

const selectedPendingIds = computed(() =>
  selectedProposalIds.value.filter((id) => {
    const p = proposals.value.find((row) => row.id === id);
    return p?.status === "pending";
  }),
);

const selectedBrowseIds = computed(() =>
  selectedProposalIds.value.filter((id) => {
    const p = proposals.value.find((row) => row.id === id);
    return p?.status === "applied" && !p?.browse_enabled;
  }),
);

const selectedL3Ids = computed(() =>
  selectedProposalIds.value.filter((id) => {
    const p = proposals.value.find((row) => row.id === id);
    return p?.status === "approved" || p?.status === "failed";
  }),
);

function isProposalSelectable(p: Record<string, unknown>) {
  return (
    p.status === "pending" ||
    p.status === "approved" ||
    p.status === "failed" ||
    (p.status === "applied" && !p.browse_enabled)
  );
}

const selectableOnPage = computed(() => proposals.value.filter(isProposalSelectable));

const pageSelectableIds = computed(() =>
  selectableOnPage.value.map((p) => p.id as number),
);

const pageAllSelected = computed(
  () =>
    pageSelectableIds.value.length > 0 &&
    pageSelectableIds.value.every((id) => selectedProposalIds.value.includes(id)),
);

const pageSomeSelected = computed(() =>
  pageSelectableIds.value.some((id) => selectedProposalIds.value.includes(id)),
);

const selectedCount = computed(() => selectedProposalIds.value.length);

const batchSelectionOverLimit = computed(() => selectedCount.value > BATCH_GOVERNANCE_MAX);

function buildProposalMeta(ids: number[]) {
  const map = new Map<number, string>();
  for (const id of ids) {
    const p = proposals.value.find((row) => row.id === id);
    map.set(id, String(p?.api_name ?? `#${id}`));
  }
  return map;
}

function clearSelectionForIds(ids: number[]) {
  selectedProposalIds.value = selectedProposalIds.value.filter((id) => !ids.includes(id));
  if (selectedProposalIds.value.length === 0) selectionScope.value = "none";
}

const showSelectAllFilteredHint = computed(
  () =>
    selectedCount.value > 0 &&
    selectionScope.value !== "all_filtered" &&
    proposalTotal.value > pageSelectableIds.value.length,
);

watch([pageAllSelected, pageSomeSelected], () => {
  const el = headerSelectRef.value;
  if (el) el.indeterminate = pageSomeSelected.value && !pageAllSelected.value;
});

watch(
  () => batchOp.value?.phase,
  (phase, prev) => {
    if (phase !== "done" || prev === "done") return;
    const op = batchOp.value;
    if (!op || op.kind !== "activate_l3") return;
    const succeeded = op.jobRows.filter((row) => row.status === "success");
    if (!succeeded.length) return;
    for (const row of succeeded) {
      const proposal = proposals.value.find((p) => p.id === row.proposalId);
      const dataType = String(proposal?.data_type ?? "");
      if (dataType.startsWith("tdx_")) {
        ui.showMessage(`${dataType} 已激活`, "success");
      }
    }
    if (scanProvider.value === "tdx") {
      void loadTdxReadiness();
    }
  },
);

function toggleSelectPage() {
  if (pageAllSelected.value) {
    const pageSet = new Set(pageSelectableIds.value);
    selectedProposalIds.value = selectedProposalIds.value.filter((id) => !pageSet.has(id));
    selectionScope.value = "none";
    return;
  }
  const merged = new Set([...selectedProposalIds.value, ...pageSelectableIds.value]);
  selectedProposalIds.value = [...merged];
  selectionScope.value =
    selectedProposalIds.value.length >= proposalTotal.value ? "all_filtered" : "page";
}

function toggleSelectProposal(id: number) {
  const idx = selectedProposalIds.value.indexOf(id);
  if (idx >= 0) {
    selectedProposalIds.value.splice(idx, 1);
    selectionScope.value = "none";
    return;
  }
  selectedProposalIds.value.push(id);
  if (pageAllSelected.value && selectionScope.value !== "all_filtered") {
    selectionScope.value = "page";
  }
}

async function selectAllFiltered() {
  if (selectAllFilteredLoading.value) return;
  selectAllFilteredLoading.value = true;
  try {
    const all = await fetchAllFilteredProposals();
    const ids = all.filter(isProposalSelectable).map((p) => p.id as number);
    if (!ids.length) {
      ui.showMessage("当前筛选下无可批量操作项", "error");
      return;
    }
    selectedProposalIds.value = ids;
    selectionScope.value = "all_filtered";
    ui.showMessage(`已全选筛选结果 ${ids.length} 条`, "success");
  } finally {
    selectAllFilteredLoading.value = false;
  }
}

const ACTIVATION_STEP_LABELS: Record<string, string> = {
  preflight_test: "Preflight 测试",
  infer_schema: "推断 Schema",
  run_migration: "自动建表",
  register_catalog: "注册 Catalog",
  register_handler: "注册采集 Handler",
  create_sync_task: "创建采集任务",
  setup_quality: "配置质检规则",
  trigger_initial_collect: "首跑采集",
  register_browse: "启用数据查询",
};

function activationStepLabel(step: string) {
  return ACTIVATION_STEP_LABELS[step] ?? step;
}

function isSelected(id: number) {
  return selectedProposalIds.value.includes(id);
}

const preflightLoading = ref<number | null>(null);
const editingPointsId = ref<number | null>(null);
const editingPointsValue = ref<string | number>("");
const savingPointsId = ref<number | null>(null);
const pointsEditError = ref<string | null>(null);

const EDITABLE_POINTS_STATUSES = new Set(["pending", "approved", "applied", "failed"]);

function proposalRowId(p: Record<string, unknown>): number {
  return Number(p.id);
}

function isEditingPoints(p: Record<string, unknown>) {
  return editingPointsId.value != null && editingPointsId.value === proposalRowId(p);
}

function canEditProposalPoints(p: Record<string, unknown>) {
  return auth.isAdmin && EDITABLE_POINTS_STATUSES.has(String(p.status));
}

function formatPointsEditError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

function parseProposalPointsValue(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  if (typeof raw === "number") {
    if (!Number.isFinite(raw) || raw < 0 || !Number.isInteger(raw)) return null;
    return raw;
  }
  const trimmed = String(raw).trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) return null;
  return n;
}

function applyProposalRowUpdate(proposalId: number, updated: Record<string, unknown>) {
  const idx = proposals.value.findIndex((row) => proposalRowId(row) === proposalId);
  if (idx >= 0) {
    proposals.value.splice(idx, 1, { ...proposals.value[idx], ...updated });
  }
}

async function refreshProposalRow(proposalId: number) {
  const updated = await apiRequest<Record<string, unknown>>(`/api/v1/tia/proposals/${proposalId}`);
  applyProposalRowUpdate(proposalId, updated);
  return updated;
}

function startPointsEdit(p: Record<string, unknown>) {
  editingPointsId.value = proposalRowId(p);
  pointsEditError.value = null;
  editingPointsValue.value =
    p.min_points != null && p.min_points !== "" ? String(p.min_points) : "";
}

function cancelPointsEdit() {
  editingPointsId.value = null;
  editingPointsValue.value = "";
  pointsEditError.value = null;
}

async function savePointsEdit(proposalId: number) {
  pointsEditError.value = null;
  const pts = parseProposalPointsValue(editingPointsValue.value);
  if (pts === null) {
    const msg = pointsInputFilled(editingPointsValue.value)
      ? "积分须为非负整数"
      : "请输入非负整数积分";
    pointsEditError.value = msg;
    ui.showMessage(msg, "error");
    return;
  }
  savingPointsId.value = proposalId;
  try {
    const updated = await apiRequest<Record<string, unknown>>(
      `/api/v1/tia/proposals/${proposalId}/min-points`,
      {
        method: "PATCH",
        body: JSON.stringify({ min_points: pts }),
      },
    );
    applyProposalRowUpdate(proposalId, updated);
    ui.showMessage("积分已更新", "success");
    cancelPointsEdit();
  } catch (e) {
    const msg = formatPointsEditError(e);
    pointsEditError.value = msg;
    ui.showMessage(msg, "error");
  } finally {
    savingPointsId.value = null;
  }
}

async function clearPointsOverride(proposalId: number) {
  savingPointsId.value = proposalId;
  pointsEditError.value = null;
  try {
    const updated = await apiRequest<Record<string, unknown>>(
      `/api/v1/tia/proposals/${proposalId}/min-points`,
      {
        method: "PATCH",
        body: JSON.stringify({ min_points: null }),
      },
    );
    applyProposalRowUpdate(proposalId, updated);
    ui.showMessage("已恢复为文档积分", "success");
    if (editingPointsId.value === proposalId) cancelPointsEdit();
  } catch (e) {
    const msg = formatPointsEditError(e);
    pointsEditError.value = msg;
    ui.showMessage(msg, "error");
  } finally {
    savingPointsId.value = null;
  }
}

function pointsSourceLabel(source: unknown) {
  const map: Record<string, string> = {
    manual: "人工修正",
    l1_override: "L1 override",
    doc_page: "官网文档",
  };
  return map[String(source)] ?? String(source ?? "—");
}

async function runPreflightTest(id: number) {
  preflightLoading.value = id;
  try {
    const data = await apiRequest<{
      passed: boolean;
      checks: Array<{ key: string; label: string; status: string; message: string }>;
      blocking_errors: string[];
    }>(`/api/v1/tia/proposals/${id}/preflight-test?live_probe=true`, { method: "POST" });
    if (data.passed) {
      ui.showMessage(`Preflight 通过（${data.checks.filter((c) => c.status === "pass").length}/10）`, "success");
    } else {
      ui.showMessage(data.blocking_errors.join("；") || "Preflight 未通过", "error");
    }
    await loadProposals();
    expandedProposalId.value = id;
  } finally {
    preflightLoading.value = null;
  }
}

function preflightCheckLabel(status: string) {
  if (status === "pass") return "badge--ok";
  if (status === "warn") return "badge--warn";
  if (status === "fail") return "badge--err";
  return "badge--muted";
}

async function batchApprove(autoActivate = false) {
  const ids = selectedPendingIds.value;
  if (!ids.length || batchBusy.value) return;
  const ok = await runBatchApprove(ids, buildProposalMeta(ids), autoActivate);
  if (ok) clearSelectionForIds(ids);
}

async function batchEnableBrowse() {
  const ids = selectedBrowseIds.value;
  if (!ids.length || batchBusy.value) return;
  const ok = await runBatchEnableBrowse(ids, buildProposalMeta(ids));
  if (ok) clearSelectionForIds(ids);
}

async function batchActivateL3() {
  const ids = selectedL3Ids.value;
  if (!ids.length || batchBusy.value) return;
  const ok = await runBatchActivateL3(ids, buildProposalMeta(ids));
  if (ok) clearSelectionForIds(ids);
}

async function retryFilteredFailed() {
  await selectAllFiltered();
  if (!selectedL3Ids.value.length) {
    ui.showMessage("当前筛选下无可重试的失败提案", "error");
    return;
  }
  await batchActivateL3();
}

function proposalApiName(id: number): string {
  const p = proposals.value.find((row) => row.id === id);
  return String(p?.api_name ?? `#${id}`);
}

async function approveAndActivate(id: number) {
  if (batchBusy.value) return;
  const ok = await runBatchApprove([id], new Map([[id, proposalApiName(id)]]), true);
  if (ok) clearSelectionForIds([id]);
}

async function activateProposal(id: number, reapply = false, forceSchema = false) {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = undefined;
  }
  activateJobId.value = null;
  job.value = null;
  const params = new URLSearchParams();
  if (reapply) params.set("reapply", "true");
  if (forceSchema) params.set("force_schema", "true");
  const q = params.toString() ? `?${params.toString()}` : "";
  const msg = forceSchema ? "L3 重建 Schema 已提交" : "L3 激活已提交";
  await runSingleL3Job(id, proposalApiName(id), `/api/v1/tia/proposals/${id}/activate${q}`, msg);
}

function browseData(dataType: string) {
  void router.push({ name: "browse", query: { data_type: dataType } });
}

async function enableBrowse(id: number) {
  if (batchBusy.value) return;
  await apiRequest(`/api/v1/tia/proposals/${id}/enable-browse`, { method: "POST" });
  ui.showMessage("已启用数据查询", "success");
  await loadProposals();
}

function scrollToProposals() {
  proposalsPanelRef.value?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function viewPendingProposals() {
  proposalStatusFilter.value = "pending";
  proposalSearch.value = "";
  proposalPage.value = 1;
  void loadProposals(1).then(() => scrollToProposals());
}

async function startScan() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = undefined;
  }
  scanInProgress.value = true;
  job.value = null;
  scanResult.value = null;
  activateJobId.value = null;
  try {
    const body =
      scanProvider.value === "tdx"
        ? {
            provider: "tdx" as const,
            mode: "full" as const,
            index_scope: "stock_a" as const,
            probe: tdxSidecarProbe.value,
            probe_scope: "all" as const,
            probe_limit: 500,
            probe_unlimited: false,
            index_source: "bundled" as const,
            sync_doc_pages: false,
            sync_doc_specs: false,
            sync_sdk_scan: false,
          }
        : {
            provider: "tushare" as const,
            mode: "full" as const,
            index_scope: "stock_a" as const,
            probe: true,
            probe_scope: "all" as const,
            probe_limit: 500,
            probe_unlimited: false,
            index_source: "document2" as const,
            sync_doc_pages: false,
            sync_doc_specs: true,
          };
    const data = await apiRequest<{ job_id: number; message: string }>("/api/v1/tia/scan", {
      method: "POST",
      body: JSON.stringify(body),
    });
    ui.showMessage(data.message || "扫描已提交", "success");
    pollTimer = window.setInterval(() => void pollJob(data.job_id), 1500);
    await pollJob(data.job_id);
    if (scanProvider.value === "tdx") {
      void loadTdxReadiness();
    }
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
    scanInProgress.value = false;
  }
}

async function runAudit() {
  auditResult.value = null;
  try {
    const data = await apiRequest<{ job_id: number }>("/api/v1/tia/audit", { method: "POST" });
    const result = await apiRequest<PlatformJob & { result?: Record<string, unknown> }>(
      `/api/v1/tia/scan/${data.job_id}`,
    );
    auditResult.value = result.result ?? null;
    ui.showMessage(String(result.message), "success");
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  }
}

async function pollJob(jobId: number) {
  jobPollCount += 1;
  const data = await apiRequest<PlatformJob & { result?: Record<string, unknown> }>(
    `/api/v1/tia/scan/${jobId}`,
  );
  job.value = data;
  jobPollStuck.value =
    jobPollCount > 10 && data.status === "pending" && (data.progress ?? 0) === 0;
  if (data.status === "success" || data.status === "failed") {
    jobPollStuck.value = false;
    jobPollCount = 0;
    scanInProgress.value = false;
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = undefined;
    }
    if (data.status === "success" && activateJobId.value !== jobId) {
      scanResult.value = data.result ?? null;
      const created = Number((data.result as Record<string, unknown> | undefined)?.proposals_created ?? 0);
      const pending = Number((data.result as Record<string, unknown> | undefined)?.proposals_pending ?? 0);
      if (created > 0 || pending > 0) {
        proposalStatusFilter.value = "pending";
        proposalPage.value = 1;
        proposalSearch.value = "";
      }
    }
    await loadProposals(proposalPage.value);
    if (
      data.status === "success" &&
      activateJobId.value !== jobId &&
      (Number((data.result as Record<string, unknown> | undefined)?.proposals_created ?? 0) > 0 ||
        Number((data.result as Record<string, unknown> | undefined)?.proposals_pending ?? 0) > 0)
    ) {
      scrollToProposals();
    }
  }
}

async function approveProposal(id: number) {
  await apiRequest(`/api/v1/tia/proposals/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "approved", note: "approved via UI" }),
  });
  ui.showMessage("已批准", "success");
  await loadProposals();
}

async function rejectProposal(id: number) {
  await apiRequest(`/api/v1/tia/proposals/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "rejected", note: "rejected via UI" }),
  });
  ui.showMessage("已拒绝", "success");
  await loadProposals();
}

async function downloadScaffold(id: number, apiName: string) {
  const base = getApiBase() || window.location.origin;
  const token = getToken();
  const res = await fetch(`${base}/api/v1/tia/proposals/${id}/scaffold`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("下载失败");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `tia_scaffold_${apiName}.zip`;
  a.click();
  URL.revokeObjectURL(a.href);
}

const schemaMaintenanceProposalId = ref<number | null>(null);
const schemaMaintenanceApiName = ref<string>("");

function openSchemaMaintenance(id: number, apiName?: string) {
  schemaMaintenanceProposalId.value = id;
  schemaMaintenanceApiName.value = apiName ?? "";
  expandedProposalId.value = id;
}

function closeSchemaMaintenance() {
  schemaMaintenanceProposalId.value = null;
  schemaMaintenanceApiName.value = "";
}

async function onSchemaMaintenanceApplied() {
  await loadProposals();
}

function preflightUniqueKeys(steps: Record<string, unknown> | undefined): string {
  const pre = steps?.preflight_test as { checks?: Array<{ key: string; detail?: { unique_keys?: string[] } }> } | undefined;
  const chk = pre?.checks?.find((c) => c.key === "schema_ddl");
  const keys = chk?.detail?.unique_keys;
  return keys?.length ? keys.join(", ") : "";
}

function inferSchemaUniqueKeys(steps: Record<string, unknown> | undefined): string {
  const infer = steps?.infer_schema as { unique_keys?: string[] } | undefined;
  return infer?.unique_keys?.length ? infer.unique_keys.join(", ") : "";
}

function proposalBadge(status: string) {
  if (status === "approved" || status === "applied") return "badge--ok";
  if (status === "rejected" || status === "failed") return "badge--err";
  if (status === "pending" || status === "review") return "badge--warn";
  return "badge--muted";
}

type ApiProbeRow = {
  api: string;
  status: string;
  rows?: number;
  message?: string;
  missing_fields?: string[];
  extra_fields?: string[];
  actual_fields?: string[];
  probe_params?: Record<string, string>;
  probe_source?: string;
  latency_ms?: number;
  doc_url?: string;
  catalog_min_points?: number;
  api_live_min_points?: number;
  interface_level?: number;
  official_doc_min_points?: number;
  points_doc_mismatch?: boolean;
};

function probeBadge(status: string) {
  if (status === "ok") return "badge--ok";
  if (status === "doc_field_mismatch" || status.startsWith("failed")) return "badge--err";
  if (status.startsWith("skipped")) return "badge--muted";
  return "badge--warn";
}

function probeStatusLabel(status: string) {
  const map: Record<string, string> = {
    ok: "一致",
    doc_field_mismatch: "字段不一致",
    skipped_no_token: "无 token",
    skipped_insufficient_points: "积分不足",
    skipped_no_probe: "无探测配置",
    failed_empty: "空响应",
    failed_points: "积分/权限",
    failed: "调用失败",
  };
  return map[status] ?? status;
}
</script>

<template>
  <PageHeader title="提案治理" description="扫描 · 审批 · L3 激活流水线">
    <template #actions>
      <button
        v-if="isTushareProvider"
        type="button"
        class="btn btn--secondary"
        @click="runAudit"
      >
        积分审计
      </button>
      <button type="button" class="btn btn--primary" :disabled="scanInProgress" @click="startScan">
        {{ scanInProgress ? "扫描中…" : "开始扫描" }}
      </button>
    </template>
  </PageHeader>

  <div class="provider-tabs">
    <button
      v-for="provider in scanProviders"
      :key="provider"
      type="button"
      class="btn btn--sm"
      :class="{ 'btn--primary': scanProvider === provider }"
      @click="switchScanProvider(provider as 'tushare' | 'tdx')"
    >
      {{ providerTabLabel(provider) }}
    </button>
  </div>

  <div v-if="isTdxProvider" class="panel panel--compact">
    <div class="panel__body">
      <div v-if="tdxReadinessLoading" class="panel__hint">检查 Sidecar 就绪状态…</div>
      <template v-else-if="tdxReadiness">
        <div class="kv-list kv-list--compact">
          <div class="kv-row">
            <span class="kv-row__label">索引</span>
            <span class="kv-row__value">bundled 官方目录 · {{ tdxReadiness.bundled_api_count }} 个 T+1 接口</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">数据源</span>
            <span class="kv-row__value">
              <template v-if="tdxReadiness.has_data_source">
                {{ tdxReadiness.source_name }}
                <code class="table-sub">{{ tdxReadiness.base_url }}</code>
              </template>
              <span v-else class="badge badge--warn">未配置</span>
            </span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">Sidecar</span>
            <span class="kv-row__value tdx-sidecar-status">
              <span
                class="badge"
                :class="tdxReadiness.sidecar_ok ? 'badge--ok' : 'badge--warn'"
              >
                {{ tdxReadiness.sidecar_ok ? "就绪" : "不可用" }}
              </span>
              <span class="tdx-sidecar-status__msg">{{ tdxReadiness.sidecar_message }}</span>
            </span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">L3 进度</span>
            <span class="kv-row__value numeric">
              已激活 {{ tdxReadiness.applied_count }} / {{ tdxReadiness.bundled_api_count }}
              · 待审 {{ tdxReadiness.pending_count }}
            </span>
          </div>
        </div>
        <p v-if="!tdxReadiness.ready" class="panel__hint panel__hint--warn">
          请先在
          <button type="button" class="inline-link" @click="goSourcesPage">数据源</button>
          配置 TDX Sidecar 并确保服务可达后再扫描与激活。
        </p>
        <label v-else class="tdx-scan-option">
          <input v-model="tdxSidecarProbe" type="checkbox" />
          扫描时执行 Sidecar 抽样探针（可选）
        </label>
      </template>
    </div>
  </div>

  <div v-if="auditResult && isTushareProvider" class="panel">
    <div class="panel__header">
      <span>积分审计结果 (F-08)</span>
    </div>
    <div class="panel__body">
      <div class="kv-list">
        <div class="kv-row">
          <span class="kv-row__label">本地 override</span>
          <span class="kv-row__value numeric">{{ auditResult.override_count }}</span>
        </div>
        <div class="kv-row">
          <span class="kv-row__label">document/2 覆盖</span>
          <span class="kv-row__value numeric">{{ auditResult.doc14_count }}</span>
        </div>
      </div>
      <details v-if="(auditResult.doc14_gaps as string[] | undefined)?.length" class="audit-details">
        <summary>document/2 菜单缺口 ({{ (auditResult.doc14_gaps as string[]).length }})</summary>
        <code>{{ (auditResult.doc14_gaps as string[]).join(", ") }}</code>
      </details>
      <details
        v-if="(auditResult.points_mismatches as unknown[] | undefined)?.length"
        class="audit-details"
      >
        <summary>积分不一致 ({{ (auditResult.points_mismatches as unknown[]).length }})</summary>
        <pre class="code-block">{{ JSON.stringify(auditResult.points_mismatches, null, 2) }}</pre>
      </details>
    </div>
  </div>

  <div v-if="scanResult && !activateJobId" class="panel">
    <div class="panel__header">
      <span>扫描结果</span>
      <span class="panel__header-count">
        <template v-if="Number(scanResult.proposals_created ?? 0) > 0">
          {{ scanResult.proposals_created }} 条新提案
        </template>
        <template v-else-if="Number(scanResult.proposals_pending ?? 0) > 0">
          0 条新提案 · {{ scanResult.proposals_pending }} 条待审
        </template>
        <template v-else>0 条新提案</template>
      </span>
      <button
        v-if="
          Number(scanResult.proposals_created ?? 0) > 0 ||
          Number(scanResult.proposals_pending ?? 0) > 0 ||
          (scanResult.new_on_official as string[] | undefined)?.length
        "
        type="button"
        class="btn btn--secondary btn--sm"
        @click="viewPendingProposals"
      >
        查看待审提案
      </button>
    </div>
    <div class="panel__body">
      <div class="kv-list">
        <div class="kv-row">
          <span class="kv-row__label">{{ isTdxProvider ? "本地已激活" : "本地 override" }}</span>
          <span class="kv-row__value numeric">{{ scanResult.local_count }}</span>
        </div>
        <div class="kv-row">
          <span class="kv-row__label">{{ isTdxProvider ? "bundled 索引" : "官网索引" }}</span>
          <span class="kv-row__value numeric">{{ scanResult.official_count }}</span>
        </div>
        <div
          v-if="isTdxProvider && (scanResult.scan_credentials as Record<string, unknown> | undefined)"
          class="kv-row"
        >
          <span class="kv-row__label">Sidecar</span>
          <span class="kv-row__value">
            {{
              (scanResult.scan_credentials as Record<string, unknown>).source_name || "—"
            }}
            <code
              v-if="(scanResult.scan_credentials as Record<string, unknown>).base_url"
              class="table-sub"
            >
              {{ (scanResult.scan_credentials as Record<string, unknown>).base_url }}
            </code>
          </span>
        </div>
        <div v-if="!isTdxProvider && scanResult.official_index_total" class="kv-row">
          <span class="kv-row__label">官方索引</span>
          <span class="kv-row__value">
            {{ scanResult.official_index_total }} 条
            <span class="badge badge--muted">{{ scanResult.official_index_source }}</span>
          </span>
        </div>
        <div v-if="!isTdxProvider && scanResult.doc_ids_traversed" class="kv-row">
          <span class="kv-row__label">遍历 doc_id</span>
          <span class="kv-row__value numeric">{{ scanResult.doc_ids_traversed }}</span>
        </div>
        <div v-if="!isTdxProvider && scanResult.sidebar_link_total" class="kv-row">
          <span class="kv-row__label">菜单链接</span>
          <span class="kv-row__value numeric">{{ scanResult.sidebar_link_total }}</span>
        </div>
        <div v-if="!isTdxProvider && scanResult.unresolved_doc_count" class="kv-row">
          <span class="kv-row__label">未解析 api</span>
          <span class="kv-row__value numeric">{{ scanResult.unresolved_doc_count }}</span>
        </div>
        <div
          v-if="
            !isTdxProvider &&
            (scanResult.sidebar_index as Record<string, unknown> | undefined)?.snapshot_path
          "
          class="kv-row"
        >
          <span class="kv-row__label">menu 快照</span>
          <span class="kv-row__value table-sub">{{
            String((scanResult.sidebar_index as Record<string, unknown>).snapshot_path)
          }}</span>
        </div>
        <div v-if="(scanResult.new_on_official as string[] | undefined)?.length" class="kv-row">
          <span class="kv-row__label">{{ isTdxProvider ? "待激活" : "官网新增" }}</span>
          <span class="kv-row__value numeric">{{ (scanResult.new_on_official as string[]).length }}</span>
        </div>
      </div>
      <details v-if="(scanResult.new_on_official as string[] | undefined)?.length" class="audit-details">
        <summary>官网新增明细 ({{ (scanResult.new_on_official as string[]).length }})</summary>
        <code>{{ (scanResult.new_on_official as string[]).join(", ") }}</code>
      </details>
      <details
        v-if="(scanResult.new_on_official_sample as string[] | undefined)?.length &&
          (scanResult.new_on_official as string[]).length > 30"
        class="audit-details"
      >
        <summary>官网新增（仅展示前 30，完整列表见 proposals）</summary>
        <code>{{ (scanResult.new_on_official_sample as string[]).join(", ") }}</code>
      </details>
      <details
        v-if="(scanResult.missing_from_official as string[] | undefined)?.length"
        class="audit-details"
      >
        <summary>仅本地登记 ({{ (scanResult.missing_from_official as string[]).length }})</summary>
        <code>{{ (scanResult.missing_from_official as string[]).join(", ") }}</code>
        <p class="panel__hint">可能为 override 登记但官网索引未覆盖的接口</p>
      </details>
      <details v-if="(scanResult.unchanged as string[] | undefined)?.length" class="audit-details">
        <summary>两边一致 ({{ (scanResult.unchanged as string[]).length }})</summary>
        <code>{{ (scanResult.unchanged as string[]).join(", ") }}</code>
      </details>

      <div
        v-if="!isTdxProvider && (scanResult.scan_options as Record<string, unknown> | undefined)"
        class="panel__hint scan-options-applied"
      >
        本次扫描：document/2 股票数据 · 全索引探测 · 最多 500 个接口
        <template v-if="scanResult.probe_planner as Record<string, number> | undefined">
          · 实际探测 {{ (scanResult.probe_planner as Record<string, number>).planned }} 个
          <span v-if="(scanResult.probe_planner as Record<string, number>).deferred">
            （延后 {{ (scanResult.probe_planner as Record<string, number>).deferred }}）
          </span>
        </template>
      </div>

      <div
        v-if="!isTdxProvider && (scanResult.doc_specs_sync as Record<string, unknown> | undefined)"
        class="probe-section"
      >
        <h3 class="probe-section__title">接口规格同步（wctapi + SDK）</h3>
        <div class="kv-list kv-list--compact">
          <div class="kv-row">
            <span class="kv-row__label">doc_id 总数</span>
            <span class="kv-row__value numeric">{{
              (scanResult.doc_specs_sync as Record<string, number>).doc_ids_total
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">已同步</span>
            <span class="kv-row__value numeric">{{
              (scanResult.doc_specs_sync as Record<string, number>).synced_count
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">解析失败</span>
            <span class="kv-row__value numeric">{{
              (scanResult.doc_specs_sync as Record<string, number>).error_count
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">SDK 无效接口</span>
            <span class="kv-row__value numeric">{{
              (scanResult.doc_specs_sync as Record<string, number>).invalid_sdk_count
            }}</span>
          </div>
        </div>
        <p
          v-if="(scanResult.doc_specs_sync as Record<string, string[]>).invalid_sdk_apis?.length"
          class="panel__hint"
        >
          无效 API 示例：
          {{ (scanResult.doc_specs_sync as Record<string, string[]>).invalid_sdk_apis?.join(", ") }}
        </p>
      </div>

      <div
        v-if="!isTdxProvider && (scanResult.points_coverage as Record<string, unknown> | undefined)"
        class="probe-section"
      >
        <h3 class="probe-section__title">积分识别覆盖</h3>
        <div class="kv-list kv-list--compact">
          <div class="kv-row">
            <span class="kv-row__label">识别模式</span>
            <span class="kv-row__value">{{
              (scanResult.points_coverage as Record<string, unknown>).points_mode === "api_live"
                ? "API 实测"
                : "文档缓存"
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">P0 文档同步</span>
            <span class="kv-row__value">{{
              (scanResult.points_coverage as Record<string, unknown>).sync_doc_pages
                ? "已开启"
                : "未开启"
            }}</span>
          </div>
          <div
            v-if="(scanResult.points_coverage as Record<string, number>).api_probe_total"
            class="kv-row"
          >
            <span class="kv-row__label">API 识别积分</span>
            <span class="kv-row__value numeric">{{
              (scanResult.points_coverage as Record<string, number>).api_live_with_min_points
            }}
            /
            {{
              (scanResult.points_coverage as Record<string, number>).api_probe_total
            }}</span>
          </div>
          <div
            v-if="(scanResult.points_coverage as Record<string, number>).api_live_points_mismatch"
            class="kv-row"
          >
            <span class="kv-row__label">API vs 文档不一致</span>
            <span class="kv-row__value numeric">{{
              (scanResult.points_coverage as Record<string, number>).api_live_points_mismatch
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">索引已识别积分</span>
            <span class="kv-row__value numeric">{{
              (scanResult.points_coverage as Record<string, number>).index_apis_with_min_points
            }}
            /
            {{
              (scanResult.points_coverage as Record<string, number>).index_apis_total
            }}</span>
          </div>
          <div
            v-if="(scanResult.points_coverage as Record<string, number>).index_apis_missing_min_points"
            class="kv-row"
          >
            <span class="kv-row__label">无数字门槛</span>
            <span class="kv-row__value numeric">{{
              (scanResult.points_coverage as Record<string, number>).index_apis_missing_min_points
            }}</span>
          </div>
        </div>
        <p
          v-if="
            (scanResult.points_coverage as Record<string, unknown>).points_mode !== 'api_live' &&
            !(scanResult.points_coverage as Record<string, number>).page_cache_with_raw_text
          "
          class="panel__hint"
        >
          页面缓存无正文。可开启 P0 文档同步，或依赖 live API 探测识别积分门槛。
        </p>
      </div>

      <div
        v-if="(scanResult.api_probe_summary as Record<string, number> | undefined)"
        class="probe-section"
      >
        <h3 class="probe-section__title">API 探测（实际响应 vs 文档字段）</h3>
        <div
          v-if="scanResult.scan_credentials as Record<string, unknown> | undefined"
          class="panel__hint"
        >
          凭证：
          {{
            (scanResult.scan_credentials as Record<string, unknown>).source_name
              || "环境变量"
          }}
          · 积分 {{ (scanResult.scan_credentials as Record<string, unknown>).account_points }}
          · token {{ (scanResult.scan_credentials as Record<string, unknown>).has_token ? "已配置" : "未配置" }}
        </div>
        <div class="kv-list kv-list--compact">
          <div class="kv-row">
            <span class="kv-row__label">一致</span>
            <span class="kv-row__value numeric">{{
              (scanResult.api_probe_summary as Record<string, number>).ok
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">字段不一致</span>
            <span class="kv-row__value numeric">{{
              (scanResult.api_probe_summary as Record<string, number>).doc_field_mismatch
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">失败</span>
            <span class="kv-row__value numeric">{{
              (scanResult.api_probe_summary as Record<string, number>).failed
            }}</span>
          </div>
          <div class="kv-row">
            <span class="kv-row__label">跳过</span>
            <span class="kv-row__value numeric">{{
              (scanResult.api_probe_summary as Record<string, number>).skipped
            }}</span>
          </div>
          <div
            v-if="(scanResult.api_probe_summary as Record<string, number>).api_live_min_points"
            class="kv-row"
          >
            <span class="kv-row__label">API 识别积分</span>
            <span class="kv-row__value numeric">{{
              (scanResult.api_probe_summary as Record<string, number>).api_live_min_points
            }}</span>
          </div>
          <div
            v-if="(scanResult.api_probe_summary as Record<string, number>).points_doc_mismatch"
            class="kv-row"
          >
            <span class="kv-row__label">积分文档不一致</span>
            <span class="kv-row__value numeric">{{
              (scanResult.api_probe_summary as Record<string, number>).points_doc_mismatch
            }}</span>
          </div>
        </div>
        <table
          v-if="(scanResult.api_probes as ApiProbeRow[] | undefined)?.length"
          class="data-table probe-table"
        >
          <thead>
            <tr>
              <th>API</th>
              <th>来源</th>
              <th>状态</th>
              <th>API积分</th>
              <th>等级</th>
              <th>行数</th>
              <th>耗时</th>
              <th>说明</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in scanResult.api_probes as ApiProbeRow[]" :key="p.api">
              <td>
                <code>{{ p.api }}</code>
                <a
                  v-if="p.doc_url"
                  :href="p.doc_url"
                  target="_blank"
                  rel="noopener"
                  class="probe-doc-link"
                >文档</a>
              </td>
              <td>{{ p.probe_source === "official_only" ? "官网新增" : p.probe_source === "template" ? "模板" : "文档库" }}</td>
              <td>
                <span class="badge" :class="probeBadge(p.status)">{{
                  probeStatusLabel(p.status)
                }}</span>
                <span v-if="p.points_doc_mismatch" class="badge badge--warn">积分不一致</span>
              </td>
              <td class="numeric">{{ p.api_live_min_points ?? "—" }}</td>
              <td class="numeric">{{ p.interface_level ?? "—" }}</td>
              <td class="numeric">{{ p.rows ?? "—" }}</td>
              <td class="numeric">{{ p.latency_ms != null ? `${p.latency_ms}ms` : "—" }}</td>
              <td>{{ p.message }}</td>
              <td>
                <details v-if="p.missing_fields?.length || p.extra_fields?.length || p.probe_params" class="audit-details audit-details--inline">
                  <summary>字段/参数</summary>
                  <p v-if="p.missing_fields?.length">
                    缺失: <code>{{ p.missing_fields.join(", ") }}</code>
                  </p>
                  <p v-if="p.extra_fields?.length">
                    额外: <code>{{ p.extra_fields.join(", ") }}</code>
                  </p>
                  <p v-if="p.probe_params">
                    参数: <code>{{ JSON.stringify(p.probe_params) }}</code>
                  </p>
                </details>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div v-if="batchOp" class="panel batch-governance-panel">
    <div class="panel__header">
      <span>{{ batchKindLabel(batchOp.kind) }}进度</span>
      <span class="panel__header-count">
        {{ batchOp.phase === "submitting" ? "受理中…" : batchOp.phase === "done" ? "已完成" : "执行中" }}
      </span>
      <button
        v-if="batchOp.phase === 'done' && batchSummary?.failed"
        type="button"
        class="btn btn--secondary btn--sm"
        :disabled="batchBusy"
        @click="retryBatchFailed()"
      >
        重试失败项 ({{ batchSummary?.failed }})
      </button>
      <button
        v-if="batchOp.phase === 'done'"
        type="button"
        class="btn btn--ghost btn--sm"
        @click="dismissBatchPanel()"
      >
        关闭
      </button>
    </div>
    <div class="panel__body">
      <div v-if="batchOp.phase === 'submitting'" class="progress-meta">
        <span>正在提交 {{ batchOp.total }} 条…</span>
      </div>
      <template v-else>
        <div v-if="batchSummary" class="batch-governance-summary">
          <span class="badge badge--ok">完成 {{ batchSummary.succeeded }}</span>
          <span v-if="batchSummary.running" class="badge badge--warn">进行中 {{ batchSummary.running }}</span>
          <span v-if="batchSummary.failed" class="badge badge--err">L3 失败 {{ batchSummary.failed }}</span>
          <span v-if="batchSummary.submitFailed" class="badge badge--err">
            提交失败 {{ batchSummary.submitFailed }}
          </span>
          <span v-if="batchSummary.queued" class="badge badge--muted">等待 {{ batchSummary.queued }}</span>
        </div>
        <div v-if="batchOp.jobRows.length" class="progress-meta">
          <span>L3 后台执行（含 Preflight）</span>
          <span class="numeric">{{ batchProgressPct }}%</span>
        </div>
        <div v-if="batchOp.jobRows.length" class="progress-bar">
          <div class="progress-bar__fill" :style="{ width: `${batchProgressPct}%` }" />
        </div>
        <table v-if="batchOp.jobRows.length" class="data-table batch-governance-table">
          <thead>
            <tr>
              <th>API</th>
              <th>状态</th>
              <th>进度</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in batchOp.jobRows" :key="row.jobId">
              <td><code>{{ row.apiName }}</code></td>
              <td>
                <span
                  class="badge"
                  :class="
                    row.status === 'success'
                      ? 'badge--ok'
                      : row.status === 'failed'
                        ? 'badge--err'
                        : 'badge--warn'
                  "
                >{{ row.status }}</span>
              </td>
              <td class="numeric">{{ row.progress }}%</td>
              <td>{{ row.error || row.message || "—" }}</td>
            </tr>
          </tbody>
        </table>
        <ul v-if="batchOp.submitErrors.length" class="batch-governance-errors">
          <li v-for="err in batchOp.submitErrors" :key="err.proposalId">
            <code>{{ err.apiName }}</code>：{{ err.error }}
          </li>
        </ul>
        <p v-if="batchOp.phase === 'running'" class="panel__hint">
          L3 按序后台执行（含 Preflight），可刷新页面或离开本页，进度 24 小时内自动恢复。
        </p>
      </template>
    </div>
  </div>

  <div v-if="job && !batchOp?.jobRows.length" class="panel">
    <div class="panel__header">
      <span>{{ activateJobId === job.id ? "L3 激活进度" : "扫描进度" }}</span>
      <span class="panel__header-count">{{ job.status }}</span>
    </div>
    <div class="panel__body">
      <div class="progress-meta">
        <span>{{ job.message }}</span>
        <span class="numeric">{{ job.progress }}%</span>
      </div>
      <div class="progress-bar">
        <div class="progress-bar__fill" :style="{ width: `${job.progress}%` }" />
      </div>
      <p v-if="jobPollStuck" class="panel__hint panel__hint--warn">
        任务长时间停在 Queued：请确认 Celery Worker 已启动，或设置
        <code>CELERY_INLINE_FALLBACK=true</code> 后重试。若刚提交批量 L3，请刷新页面再试一次。
      </p>
    </div>
  </div>

  <div ref="proposalsPanelRef" class="panel">
    <div class="panel__header">
      <span>提案列表</span>
      <span class="panel__header-count">
        {{ proposalTotal }} 条
        <template v-if="proposalSummary?.pending"> · 待审 {{ proposalSummary.pending }}</template>
      </span>
      <button type="button" class="btn btn--ghost btn--sm" :disabled="proposalLoading" @click="loadProposals()">
        刷新
      </button>
    </div>
    <div class="panel__body">
      <div v-if="proposalSummary" class="proposal-summary">
        <button
          v-for="tab in PROPOSAL_STATUS_TABS"
          :key="tab.key"
          type="button"
          class="btn btn--ghost btn--sm"
          :class="{ 'btn--primary': proposalStatusFilter === tab.key }"
          @click="proposalStatusFilter = tab.key; onProposalFilterChange()"
        >
          {{ tab.label }}
          <span v-if="tab.key && proposalSummary[tab.key as keyof typeof proposalSummary]" class="numeric">
            ({{ proposalSummary[tab.key as keyof typeof proposalSummary] }})
          </span>
          <span v-else-if="!tab.key" class="numeric">({{ proposalSummary.total }})</span>
        </button>
        <button
          v-if="proposalStatusFilter === 'failed'"
          type="button"
          class="btn btn--secondary btn--sm"
          :disabled="selectAllFilteredLoading || batchBusy"
          @click="retryFilteredFailed()"
        >
          全选筛选结果并重试 L3
        </button>
      </div>
      <div v-if="!isTdxProvider" class="kv-row proposal-points-filter">
        <span class="table-sub proposal-points-filter__label">积分区间</span>
        <input
          v-model="proposalPointsMin"
          type="number"
          min="0"
          step="1"
          class="input input--narrow"
          placeholder="最低"
          @keyup.enter="applyCustomPointsFilter()"
        />
        <span class="table-sub">至</span>
        <input
          v-model="proposalPointsMax"
          type="number"
          min="0"
          step="1"
          class="input input--narrow"
          placeholder="最高"
          @keyup.enter="applyCustomPointsFilter()"
        />
        <button type="button" class="btn btn--secondary btn--sm" @click="applyCustomPointsFilter()">
          筛选
        </button>
        <button
          v-if="pointsFilterActive"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="clearPointsFilter"
        >
          清除
        </button>
        <span v-if="pointsFilterActive" class="badge badge--muted">
          已筛选 {{ pointsFilterLabel }}
        </span>
      </div>
      <div class="kv-row proposal-toolbar">
        <input
          v-model="proposalSearch"
          type="search"
          class="input"
          placeholder="搜索 API / data_type / 原因"
          @keyup.enter="onProposalSearch"
        />
        <button type="button" class="btn btn--secondary btn--sm" @click="onProposalSearch">搜索</button>
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          :disabled="!selectableOnPage.length || selectAllFilteredLoading"
          @click="toggleSelectPage()"
        >
          {{ pageAllSelected ? "取消本页" : "全选本页" }}
        </button>
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          :disabled="selectAllFilteredLoading || proposalTotal === 0"
          @click="selectAllFiltered()"
        >
          {{ selectAllFilteredLoading ? "全选中…" : "全选筛选结果" }}
        </button>
        <button
          v-if="selectedCount"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="clearProposalSelection()"
        >
          清除选择 ({{ selectedCount }})
        </button>
        <button
          v-if="selectedPendingIds.length"
          type="button"
          class="btn btn--secondary btn--sm"
          :disabled="batchBusy || batchSelectionOverLimit"
          @click="batchApprove(false)"
        >
          {{ batchBusy ? "处理中…" : `批量批准 (${selectedPendingIds.length})` }}
        </button>
        <button
          v-if="selectedPendingIds.length"
          type="button"
          class="btn btn--primary btn--sm"
          :disabled="batchBusy || batchSelectionOverLimit"
          @click="batchApprove(true)"
        >
          {{ batchBusy ? "处理中…" : `批量批准并激活 (${selectedPendingIds.length})` }}
        </button>
        <button
          v-if="selectedL3Ids.length"
          type="button"
          class="btn btn--primary btn--sm"
          :disabled="batchBusy || batchSelectionOverLimit"
          @click="batchActivateL3()"
        >
          {{ batchBusy ? "处理中…" : `批量 L3 激活 (${selectedL3Ids.length})` }}
        </button>
        <button
          v-if="selectedBrowseIds.length"
          type="button"
          class="btn btn--secondary btn--sm"
          :disabled="batchBusy || batchSelectionOverLimit"
          @click="batchEnableBrowse()"
        >
          {{ batchBusy ? "处理中…" : `批量开通查询 (${selectedBrowseIds.length})` }}
        </button>
      </div>
      <p v-if="batchSelectionOverLimit" class="panel__hint panel__hint--warn">
        已选 {{ selectedCount }} 条，超过单次上限 {{ BATCH_GOVERNANCE_MAX }}，请缩小选择范围。
      </p>
      <div v-if="selectedCount" class="proposal-selection-bar">
        <span>
          已选 <strong class="numeric">{{ selectedCount }}</strong> 条
          <template v-if="selectionScope === 'all_filtered'">（筛选结果全部）</template>
          <template v-else-if="pageAllSelected && proposalTotal > pageSelectableIds.length">
            （本页全部）
          </template>
        </span>
        <span v-if="selectedPendingIds.length" class="badge badge--muted">
          待审 {{ selectedPendingIds.length }}
        </span>
        <span v-if="selectedL3Ids.length" class="badge badge--muted">
          可 L3 {{ selectedL3Ids.length }}
        </span>
        <span v-if="selectedBrowseIds.length" class="badge badge--muted">
          可开通查询 {{ selectedBrowseIds.length }}
        </span>
        <span v-if="showSelectAllFilteredHint" class="proposal-selection-hint">
          筛选共 {{ proposalTotal }} 条，可
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            :disabled="selectAllFilteredLoading"
            @click="selectAllFiltered()"
          >
            全选筛选结果
          </button>
        </span>
      </div>
    </div>
    <div class="panel__body panel__body--flush">
      <table v-if="proposals.length" class="data-table">
        <thead>
          <tr>
            <th class="proposal-select-th">
              <input
                ref="headerSelectRef"
                type="checkbox"
                :checked="pageAllSelected"
                :disabled="!selectableOnPage.length || selectAllFilteredLoading"
                title="全选本页可操作项"
                @change="toggleSelectPage()"
              />
            </th>
            <th>API</th>
            <th>{{ isTdxProvider ? "说明" : "文档" }}</th>
            <th v-if="!isTdxProvider">积分</th>
            <th>data_type</th>
            <th>状态</th>
            <th>扫描任务</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="p in proposals" :key="p.id as number">
            <tr>
              <td>
                <input
                  v-if="isProposalSelectable(p)"
                  type="checkbox"
                  :checked="isSelected(p.id as number)"
                  @change="toggleSelectProposal(p.id as number)"
                />
              </td>
              <td>
                <code>{{ p.api_name }}</code>
                <div v-if="p.label" class="table-sub">{{ p.label }}</div>
              </td>
              <td>
                <a
                  v-if="!isTdxProvider && p.doc_url"
                  :href="String(p.doc_url)"
                  target="_blank"
                  rel="noopener"
                  class="link-muted"
                >
                  doc {{ p.doc_id }}
                </a>
                <span v-else-if="isTdxProvider && p.label" class="table-sub">{{ p.label }}</span>
                <span v-else>—</span>
              </td>
              <td v-if="!isTdxProvider" class="numeric proposal-points-cell">
                <div v-if="isEditingPoints(p)" class="proposal-points-edit" @click.stop>
                  <input
                    v-model.number="editingPointsValue"
                    type="number"
                    min="0"
                    step="1"
                    class="input input--narrow"
                    :disabled="savingPointsId === proposalRowId(p)"
                    @keyup.enter="savePointsEdit(proposalRowId(p))"
                    @keyup.escape="cancelPointsEdit()"
                  />
                  <button
                    type="button"
                    class="btn btn--primary btn--sm"
                    :disabled="savingPointsId === proposalRowId(p)"
                    @click.stop="savePointsEdit(proposalRowId(p))"
                  >
                    {{ savingPointsId === proposalRowId(p) ? "保存中…" : "保存" }}
                  </button>
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm"
                    :disabled="savingPointsId === proposalRowId(p)"
                    @click.stop="cancelPointsEdit()"
                  >
                    取消
                  </button>
                  <span v-if="pointsEditError && editingPointsId === proposalRowId(p)" class="proposal-points-error">
                    {{ pointsEditError }}
                  </span>
                </div>
                <div v-else class="proposal-points-display">
                  <span>{{ p.min_points ?? "—" }}</span>
                  <span
                    v-if="p.min_points_source === 'manual'"
                    class="badge badge--warn proposal-points-badge"
                    title="已人工修正"
                  >
                    手动
                  </span>
                  <button
                    v-if="canEditProposalPoints(p)"
                    type="button"
                    class="btn btn--ghost btn--sm proposal-points-edit-btn"
                    :disabled="savingPointsId === proposalRowId(p)"
                    title="修正积分"
                    @click.stop="startPointsEdit(p)"
                  >
                    编辑
                  </button>
                </div>
              </td>
              <td><code class="table-sub">{{ p.data_type ?? "—" }}</code></td>
              <td>
                <span class="badge" :class="proposalBadge(String(p.status))">{{ p.status }}</span>
              </td>
              <td class="numeric">{{ p.job_id ?? "—" }}</td>
              <td class="table-sub">{{ formatProposalTime(p.created_at) }}</td>
              <td>
                <div class="btn-group">
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm"
                    @click="toggleProposalDetail(p.id as number)"
                  >
                    详情
                  </button>
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm"
                    @click="openStandards(String(p.api_name))"
                  >
                    标准
                  </button>
                  <template v-if="p.status === 'pending'">
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      :disabled="preflightLoading === (p.id as number)"
                      @click="runPreflightTest(p.id as number)"
                    >
                      {{ preflightLoading === (p.id as number) ? "测试中…" : "Preflight" }}
                    </button>
                    <button type="button" class="btn btn--ghost btn--sm" @click="approveProposal(p.id as number)">
                      批准
                    </button>
                    <button
                      type="button"
                      class="btn btn--primary btn--sm"
                      :disabled="batchBusy"
                      @click="approveAndActivate(p.id as number)"
                    >
                      批准并激活
                    </button>
                    <button type="button" class="btn btn--ghost btn--sm" @click="rejectProposal(p.id as number)">
                      拒绝
                    </button>
                  </template>
                  <template v-else-if="p.status === 'approved'">
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      :disabled="preflightLoading === (p.id as number)"
                      @click="runPreflightTest(p.id as number)"
                    >
                      Preflight
                    </button>
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="downloadScaffold(p.id as number, String(p.api_name))"
                    >
                      L2
                    </button>
                    <button
                      type="button"
                      class="btn btn--primary btn--sm"
                      :disabled="batchBusy"
                      @click="activateProposal(p.id as number)"
                    >
                      L3
                    </button>
                  </template>
                  <template v-else-if="p.status === 'applied'">
                    <button
                      v-if="!p.browse_enabled"
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="enableBrowse(p.id as number)"
                    >
                      启用查询
                    </button>
                    <button
                      v-if="p.browse_enabled && p.data_type"
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="browseData(String(p.data_type))"
                    >
                      查询
                    </button>
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="openSchemaMaintenance(p.id as number, String(p.api_name))"
                    >
                      Schema 运维
                    </button>
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      :disabled="batchBusy"
                      @click="activateProposal(p.id as number, true)"
                    >
                      重试
                    </button>
                  </template>
                  <template v-else-if="p.status === 'failed'">
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="openSchemaMaintenance(p.id as number, String(p.api_name))"
                    >
                      Schema 运维
                    </button>
                    <button
                      type="button"
                      class="btn btn--primary btn--sm"
                      :disabled="batchBusy"
                      @click="activateProposal(p.id as number, true)"
                    >
                      重试 L3
                    </button>
                  </template>
                </div>
              </td>
            </tr>
            <tr v-if="expandedProposalId === p.id" class="proposal-detail-row">
              <td colspan="9">
                <div class="kv-list kv-list--compact">
                  <div class="kv-row">
                    <span class="kv-row__label">原因</span>
                    <span>{{ p.reason ?? "—" }}</span>
                  </div>
                  <div v-if="p.category" class="kv-row">
                    <span class="kv-row__label">类目</span>
                    <span>{{ p.category }}</span>
                  </div>
                  <div v-if="p.description" class="kv-row kv-row--stack">
                    <span class="kv-row__label">接口描述</span>
                    <span>{{ p.description }}</span>
                  </div>
                  <div v-if="Array.isArray(p.sample_codes) && p.sample_codes.length" class="kv-row kv-row--stack">
                    <span class="kv-row__label">调用示例</span>
                    <pre class="code-block">{{ p.sample_codes[0] }}</pre>
                  </div>
                  <div
                    v-if="Array.isArray(p.input_params) && p.input_params.length"
                    class="kv-row kv-row--stack"
                  >
                    <span class="kv-row__label">入参 ({{ p.input_params.length }})</span>
                    <table class="mini-table">
                      <thead>
                        <tr>
                          <th>名称</th>
                          <th>类型</th>
                          <th>必选</th>
                          <th>描述</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="row in p.input_params" :key="String(row.name)">
                          <td><code>{{ row.name }}</code></td>
                          <td>{{ row.type ?? "—" }}</td>
                          <td>{{ row.required ?? "—" }}</td>
                          <td>{{ row.description ?? "—" }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div
                    v-if="Array.isArray(p.output_fields) && p.output_fields.length"
                    class="kv-row kv-row--stack"
                  >
                    <span class="kv-row__label">出参字段 ({{ p.output_fields.length }})</span>
                    <div class="tag-list">
                      <code v-for="f in p.output_fields.slice(0, 24)" :key="String(f)" class="tag">{{ f }}</code>
                      <span v-if="p.output_fields.length > 24" class="table-sub">
                        +{{ p.output_fields.length - 24 }} 更多
                      </span>
                    </div>
                  </div>
                  <div v-if="p.sdk_valid != null" class="kv-row">
                    <span class="kv-row__label">SDK 校验</span>
                    <span class="badge" :class="p.sdk_valid ? 'badge--ok' : 'badge--err'">
                      {{ p.sdk_valid ? "有效" : "无效" }}
                    </span>
                    <span v-if="p.spec_source" class="table-sub">来源 {{ p.spec_source }}</span>
                  </div>
                  <div class="kv-row">
                    <span class="kv-row__label">官网积分</span>
                    <span class="numeric">{{ p.min_points_doc ?? "—" }}</span>
                  </div>
                  <div class="kv-row">
                    <span class="kv-row__label">生效积分</span>
                    <span class="numeric">
                      {{ p.min_points ?? "—" }}
                      <span v-if="p.min_points_source" class="badge badge--muted">
                        {{ pointsSourceLabel(p.min_points_source) }}
                      </span>
                    </span>
                  </div>
                  <div
                    v-if="canEditProposalPoints(p) && p.min_points_source === 'manual'"
                    class="kv-row"
                  >
                    <span class="kv-row__label">积分修正</span>
                    <button
                      type="button"
                      class="btn btn--ghost btn--sm"
                      :disabled="savingPointsId === proposalRowId(p)"
                      @click.stop="clearPointsOverride(proposalRowId(p))"
                    >
                      {{ savingPointsId === proposalRowId(p) ? "恢复中…" : "恢复文档值" }}
                    </button>
                  </div>
                  <div v-if="p.reviewer_note" class="kv-row">
                    <span class="kv-row__label">审批备注</span>
                    <span>{{ p.reviewer_note }}</span>
                  </div>
                  <div class="kv-row">
                    <span class="kv-row__label">更新时间</span>
                    <span>{{ formatProposalTime(p.updated_at) }}</span>
                  </div>
                  <div
                    v-if="preflightUniqueKeys(p.activation_steps as Record<string, unknown> | undefined)"
                    class="kv-row"
                  >
                    <span class="kv-row__label">Preflight 唯一键</span>
                    <code>{{ preflightUniqueKeys(p.activation_steps as Record<string, unknown> | undefined) }}</code>
                  </div>
                  <div
                    v-if="inferSchemaUniqueKeys(p.activation_steps as Record<string, unknown> | undefined)"
                    class="kv-row"
                  >
                    <span class="kv-row__label">L3 唯一键</span>
                    <code>{{ inferSchemaUniqueKeys(p.activation_steps as Record<string, unknown> | undefined) }}</code>
                  </div>
                  <div
                    v-if="(p.activation_steps as Record<string, unknown> | undefined)?.preflight_test"
                    class="kv-row kv-row--stack"
                  >
                    <span class="kv-row__label">Preflight</span>
                    <div class="activation-steps">
                      <span
                        class="badge"
                        :class="
                          (p.activation_steps as Record<string, { passed?: boolean }>).preflight_test?.passed
                            ? 'badge--ok'
                            : 'badge--err'
                        "
                      >
                        {{
                          (p.activation_steps as Record<string, { passed?: boolean }>).preflight_test?.passed
                            ? "通过"
                            : "未通过"
                        }}
                      </span>
                      <span
                        v-for="chk in (
                          p.activation_steps as Record<
                            string,
                            { checks?: Array<{ key: string; label: string; status: string; message: string }> }
                          >
                        ).preflight_test?.checks ?? []"
                        :key="chk.key"
                        class="badge"
                        :class="preflightCheckLabel(chk.status)"
                        :title="chk.message"
                      >
                        {{ chk.label }}: {{ chk.status }}
                      </span>
                    </div>
                  </div>
                  <div v-if="p.activation_steps as Record<string, unknown> | undefined" class="kv-row kv-row--stack">
                    <span class="kv-row__label">L3 流水线</span>
                    <div class="activation-steps">
                      <span
                        v-for="(meta, step) in p.activation_steps as Record<string, { status?: string }>"
                        :key="step"
                        v-show="step !== 'preflight_test'"
                        class="badge"
                        :class="
                          meta.status === 'success'
                            ? 'badge--ok'
                            : meta.status === 'failed'
                              ? 'badge--err'
                              : 'badge--muted'
                        "
                      >
                        {{ activationStepLabel(String(step)) }}: {{ meta.status ?? "—" }}
                      </span>
                    </div>
                  </div>
                  <div v-if="p.status === 'applied'" class="kv-row kv-row--stack">
                    <span class="kv-row__label">采集说明</span>
                    <span class="table-sub">
                      <template v-if="p.api_name === 'stock_basic'">
                        股票列表为<strong>全量快照</strong>（非按日历史）；L3 后会自动首跑并生成工作日 08:00 调度。
                      </template>
                      <template v-else>
                        L3 完成后会创建 active 采集任务、Cron 调度并排队首跑；可在
                        <RouterLink to="/tasks">采集任务</RouterLink>
                        查看执行日志。
                      </template>
                      若已激活但无数据：到采集任务页手动「执行」，或对本提案「重试 L3」。
                    </span>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-else-if="!proposalLoading && proposalSearch.trim()" class="empty-state empty-state--compact">
        无匹配「{{ proposalSearch.trim() }}」
      </p>
      <p v-else-if="!proposalLoading" class="empty-state empty-state--compact">
        暂无提案，刷新列表或运行扫描
      </p>
      <p v-else class="empty-state empty-state--compact">加载中…</p>
      <div v-if="proposalTotal > proposalPageSize" class="panel__footer proposal-pagination">
        <button type="button" class="btn btn--ghost btn--sm" :disabled="proposalPage <= 1" @click="proposalPrevPage">
          上一页
        </button>
        <span class="numeric">
          第 {{ proposalPage }} / {{ Math.max(1, Math.ceil(proposalTotal / proposalPageSize)) }} 页
        </span>
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          :disabled="proposalPage >= Math.ceil(proposalTotal / proposalPageSize)"
          @click="proposalNextPage"
        >
          下一页
        </button>
      </div>
    </div>
  </div>

  <SchemaMaintenanceDrawer
    :proposal-id="schemaMaintenanceProposalId"
    :api-name="schemaMaintenanceApiName"
    @close="closeSchemaMaintenance"
    @applied="onSchemaMaintenanceApplied"
  />
</template>

<style scoped>
.doc-auth-panel {
  margin-top: var(--space-md);
  padding-top: var(--space-md);
  border-top: 1px solid var(--color-border);
}

.doc-auth-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
  font-weight: 600;
}

.doc-auth-form {
  display: grid;
  gap: var(--space-sm);
  margin: var(--space-sm) 0;
  max-width: 24rem;
}

.doc-auth-form__field {
  display: grid;
  gap: 0.25rem;
  font-size: 0.875rem;
}

.doc-auth-form__actions,
.doc-auth-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
}

.stat-strip--compact {
  margin-bottom: var(--space-md);
}

.stat-card--compact .stat-card__value {
  font-size: 1.1rem;
}

.proposal-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}

.batch-governance-panel {
  margin-bottom: var(--space-md);
}

.batch-governance-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.batch-governance-table {
  margin-top: var(--space-sm);
  font-size: 0.875rem;
}

.batch-governance-errors {
  margin: var(--space-sm) 0 0;
  padding-left: 1.25rem;
  font-size: 0.875rem;
  color: var(--color-text-muted);
}

.proposal-points-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}

.proposal-points-filter__label {
  flex-shrink: 0;
}

.input--narrow {
  flex: 0 0 96px;
  width: 96px;
  min-width: 72px;
}

.proposal-points-cell {
  white-space: nowrap;
}

.proposal-points-display,
.proposal-points-edit {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}

.proposal-points-badge {
  font-size: 0.7rem;
  vertical-align: middle;
}

.proposal-points-edit-btn {
  padding: 0.1rem 0.35rem;
  font-size: 0.75rem;
  opacity: 0.65;
}

.proposal-points-error {
  flex: 1 1 100%;
  font-size: 0.75rem;
  color: var(--color-err-text);
}

.proposal-points-display:hover .proposal-points-edit-btn {
  opacity: 1;
}

.proposal-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-md);
}

.proposal-toolbar .input {
  flex: 1 1 220px;
  min-width: 160px;
}

.proposal-selection-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  background: var(--color-surface-muted);
  font-size: var(--font-size-sm);
}

.proposal-selection-hint {
  color: var(--color-text-muted);
}

.proposal-select-th {
  width: 2.5rem;
  text-align: center;
}

.proposal-select-th input[type="checkbox"] {
  cursor: pointer;
}

.proposal-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  padding: var(--space-md);
}

.table-sub {
  display: block;
  margin-top: 2px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  white-space: normal;
}

.proposal-detail-row td {
  background: var(--color-surface-muted);
  white-space: normal;
}

.proposal-detail-row .kv-list--compact {
  padding: var(--space-sm) var(--space-md);
}

.activation-steps {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
}

.kv-row--stack {
  flex-direction: column;
  align-items: flex-start;
}

.code-block {
  margin: 0;
  padding: 0.5rem 0.75rem;
  max-width: 100%;
  overflow-x: auto;
  font-size: 0.75rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  white-space: pre-wrap;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}

.mini-table th,
.mini-table td {
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--color-border);
  text-align: left;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.tag-list .tag {
  font-size: 0.7rem;
  padding: 0.1rem 0.35rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 3px;
}

.provider-tabs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  margin-bottom: var(--space-md);
  padding: 3px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.provider-tabs .btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  box-shadow: none;
}

.provider-tabs .btn:hover:not(:disabled) {
  background: var(--color-row-hover);
  color: var(--color-text);
}

.provider-tabs .btn.btn--primary {
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.panel--compact .panel__body {
  padding: var(--space-sm) var(--space-md);
}

.panel__hint {
  margin: var(--space-sm) 0 0;
  font-size: 0.875rem;
  color: var(--color-text-muted);
  line-height: 1.5;
}

.panel__hint--warn {
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-sm);
  background: var(--color-warn-bg);
  color: var(--color-warn-text);
  border: 1px solid color-mix(in srgb, var(--color-warn-text) 22%, transparent);
}

.inline-link {
  padding: 0;
  border: none;
  background: none;
  color: var(--color-primary);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.inline-link:hover {
  opacity: 0.85;
}

.tdx-sidecar-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
}

.tdx-sidecar-status__msg {
  font-size: 0.8125rem;
  color: var(--color-text-muted);
  word-break: break-word;
}

.tdx-scan-option {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  font-size: 0.875rem;
  color: var(--color-text-muted);
}
</style>
