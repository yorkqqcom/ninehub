<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { apiRequest, getApiBase, getToken } from "@/api/client";
import type {
  DataStandardDetail,
  DataStandardListResponse,
  DataStandardSummaryItem,
  DriftDetail,
  QualitySuggestionsResponse,
  DataStandardExportResponse,
} from "@/api/types";

const props = defineProps<{
  initialApi?: string | null;
  onOpenProposal?: (proposalId: number) => void;
  onOpenSchemaMaintenance?: (proposalId: number, apiName: string) => void;
}>();

const router = useRouter();

const standards = ref<DataStandardSummaryItem[]>([]);
const summary = ref<DataStandardListResponse["summary"] | null>(null);
const total = ref(0);
const loading = ref(false);
const detailLoading = ref(false);

const domainFilter = ref("");
const providerFilter = ref("");
const proposalStatusFilter = ref("");
const schemaStageFilter = ref("");
const probeStatusFilter = ref("");
const driftStatusFilter = ref("");
const searchQuery = ref("");
const selectedApi = ref<string | null>(null);
const detail = ref<DataStandardDetail | null>(null);
const driftDetail = ref<DriftDetail | null>(null);
const qualitySuggestions = ref<QualitySuggestionsResponse | null>(null);

const DOMAIN_LABELS: Record<string, string> = {
  market: "行情",
  basic: "基础",
  financial: "财务",
  reference: "参考",
  feature: "特色",
  index: "指数",
  macro: "宏观",
};

const SCHEMA_STAGE_LABELS: Record<string, string> = {
  await_probe: "待 probe",
  schema_preview: "预览对照",
  schema_persisted: "已写入 override",
  schema_ready: "可建表",
  activated: "已激活",
};

const FIELD_SOURCE_LABELS: Record<string, string> = {
  catalog_probe: "Catalog 探针",
  template: "模板推断",
  none: "无字段",
};

const DRIFT_STATUS_LABELS: Record<string, string> = {
  none: "无漂移",
  doc_drift: "文档漂移",
  live_drift: "实测漂移",
  ddl_drift: "表结构漂移",
};

const PROVIDER_LABELS: Record<string, string> = {
  tushare: "Tushare",
  akshare: "AkShare",
  cninfo: "巨潮",
};

const PROBE_STATUS_LABELS: Record<string, string> = {
  configured: "Catalog 探针",
  template: "模板推断",
  unconfigured: "待配置",
};

const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  pending: "待审",
  approved: "已批准",
  rejected: "已拒绝",
  applied: "已激活",
  failed: "失败",
};

const STATUS_LABELS: Record<string, string> = {
  matched: "已匹配",
  missing_in_standard: "列缺失",
  extra_in_standard: "列多余",
  type_mismatch: "类型不一致",
};

const domainTabs = computed(() => [
  { key: "", label: "全部" },
  ...Object.entries(DOMAIN_LABELS).map(([key, label]) => ({ key, label })),
]);

const coverageFilter = ref("");

const providerTabs = computed(() => [
  { key: "", label: "全部源" },
  { key: "tushare", label: "Tushare" },
]);

async function loadStandards() {
  loading.value = true;
  try {
    const params = new URLSearchParams({ limit: "500" });
    if (domainFilter.value) params.set("domain", domainFilter.value);
    if (providerFilter.value) params.set("provider_id", providerFilter.value);
    if (driftStatusFilter.value) params.set("drift_status", driftStatusFilter.value);
    if (searchQuery.value.trim()) params.set("q", searchQuery.value.trim());
    if (coverageFilter.value === "gap") params.set("min_coverage", "0");
    if (coverageFilter.value === "partial") params.set("min_coverage", "1");
    if (probeStatusFilter.value) params.set("probe_status", probeStatusFilter.value);
    if (proposalStatusFilter.value) params.set("proposal_status", proposalStatusFilter.value);

    const data = await apiRequest<DataStandardListResponse>(
      `/api/v1/catalog/data-standards?${params.toString()}`,
    );
    standards.value = data.items;
    total.value = data.total;
    summary.value = data.summary;

    if (schemaStageFilter.value) {
      standards.value = standards.value.filter((i) => i.schema_stage === schemaStageFilter.value);
    }

    if (coverageFilter.value === "full") {
      standards.value = standards.value.filter(
        (i) =>
          i.missing_count === 0 &&
          i.extra_count === 0 &&
          i.type_mismatch_count === 0 &&
          i.api_field_count > 0,
      );
    } else if (coverageFilter.value === "partial") {
      standards.value = standards.value.filter(
        (i) =>
          i.coverage_pct > 0 &&
          i.coverage_pct < 100 &&
          (i.missing_count > 0 || i.extra_count > 0 || i.type_mismatch_count > 0),
      );
    } else if (coverageFilter.value === "gap") {
      standards.value = standards.value.filter((i) => i.missing_count > 0);
    }
  } finally {
    loading.value = false;
  }
}

async function loadDetail(apiName: string) {
  detailLoading.value = true;
  driftDetail.value = null;
  qualitySuggestions.value = null;
  try {
    const [detailData, driftData, qualityData] = await Promise.all([
      apiRequest<DataStandardDetail>(
        `/api/v1/catalog/data-standards/${encodeURIComponent(apiName)}`,
      ),
      apiRequest<DriftDetail>(
        `/api/v1/catalog/data-standards/${encodeURIComponent(apiName)}/drift`,
      ).catch(() => null),
      apiRequest<QualitySuggestionsResponse>(
        `/api/v1/catalog/data-standards/${encodeURIComponent(apiName)}/quality-suggestions`,
      ).catch(() => null),
    ]);
    detail.value = detailData;
    driftDetail.value = driftData;
    qualitySuggestions.value = qualityData;
  } finally {
    detailLoading.value = false;
  }
}

async function openInitialApi(apiName: string) {
  selectedApi.value = apiName;
  await loadDetail(apiName);
}

onMounted(() => {
  void loadStandards().then(() => {
    if (props.initialApi) void openInitialApi(props.initialApi);
  });
});

watch(
  () => props.initialApi,
  (api) => {
    if (api) void openInitialApi(api);
  },
);

watch(
  [domainFilter, providerFilter, proposalStatusFilter, probeStatusFilter, schemaStageFilter, driftStatusFilter],
  () => void loadStandards(),
);

function onSearch() {
  void loadStandards();
}

function selectApi(apiName: string) {
  if (selectedApi.value === apiName) {
    selectedApi.value = null;
    detail.value = null;
    return;
  }
  selectedApi.value = apiName;
  void loadDetail(apiName);
}

function domainLabel(domain: string) {
  return DOMAIN_LABELS[domain] ?? domain;
}

function schemaStageLabel(stage: string) {
  return SCHEMA_STAGE_LABELS[stage] ?? stage;
}

function fieldSourceLabel(source: string) {
  return FIELD_SOURCE_LABELS[source] ?? source;
}

function probeStatusLabel(status: string) {
  return PROBE_STATUS_LABELS[status] ?? status;
}

function proposalStatusLabel(status: string) {
  return PROPOSAL_STATUS_LABELS[status] ?? status;
}

function openProposal(proposalId: number) {
  if (props.onOpenProposal) {
    props.onOpenProposal(proposalId);
    return;
  }
  void router.push({ name: "tia", query: { proposal: String(proposalId) } });
}

function openSchemaMaintenance(item: DataStandardSummaryItem | DataStandardDetail) {
  if (props.onOpenSchemaMaintenance && item.proposal_id) {
    props.onOpenSchemaMaintenance(item.proposal_id, item.api_name);
  }
}

function browseActivated(item: DataStandardSummaryItem | DataStandardDetail) {
  void router.push({ name: "browse", query: { data_type: item.data_type } });
}

function driftStatusLabel(status: string) {
  return DRIFT_STATUS_LABELS[status] ?? status;
}

function driftStatusClass(status: string) {
  if (status === "none") return "badge--ok";
  if (status === "ddl_drift") return "badge--danger";
  return "badge--warn";
}

function providerLabel(provider: string) {
  return PROVIDER_LABELS[provider] ?? provider;
}

async function exportJsonSchema(item: DataStandardSummaryItem | DataStandardDetail) {
  try {
    const data = await apiRequest<DataStandardExportResponse>(
      `/api/v1/catalog/data-standards/${encodeURIComponent(item.api_name)}/export?format=json_schema`,
    );
    if (!data.json_schema) return;
    downloadBlob(
      new Blob([JSON.stringify(data.json_schema, null, 2)], { type: "application/json" }),
      `${item.api_name}.schema.json`,
    );
  } catch (e) {
    console.error(e);
  }
}

async function exportOpenApi(item: DataStandardSummaryItem | DataStandardDetail) {
  try {
    const data = await apiRequest<DataStandardExportResponse>(
      `/api/v1/catalog/data-standards/${encodeURIComponent(item.api_name)}/export?format=openapi`,
    );
    if (!data.openapi) return;
    downloadBlob(
      new Blob([JSON.stringify(data.openapi, null, 2)], { type: "application/json" }),
      `${item.api_name}.openapi.json`,
    );
  } catch (e) {
    console.error(e);
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function downloadBundle(format: "zip_json_schema" | "zip_openapi" | "openapi") {
  const params = new URLSearchParams({ format });
  if (domainFilter.value) params.set("domain", domainFilter.value);
  if (providerFilter.value) params.set("provider_id", providerFilter.value);
  const base = getApiBase() || window.location.origin;
  const token = getToken();
  const res = await fetch(`${base}/api/v1/catalog/data-standards/export?${params}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || "导出失败");
  }
  const blob = await res.blob();
  const filename =
    format === "openapi" ? "ninehub_catalog_openapi.json" : `ninehub_catalog_${format}.zip`;
  downloadBlob(blob, filename);
}

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status;
}

function statusClass(status: string) {
  if (status === "matched") return "badge--ok";
  if (status === "type_mismatch") return "badge--warn";
  if (status === "missing_in_standard") return "badge--danger";
  return "badge--muted";
}

function coverageClass(pct: number) {
  if (pct >= 100) return "coverage--full";
  if (pct >= 60) return "coverage--partial";
  return "coverage--gap";
}

function schemaStageClass(stage: string) {
  if (stage === "activated") return "badge--ok";
  if (stage === "schema_ready") return "badge--ok";
  if (stage === "await_probe") return "badge--danger";
  return "badge--muted";
}
</script>

<template>
  <div class="stat-strip">
    <div class="stat-card">
      <p class="stat-card__label">TIA 提案</p>
      <p class="stat-card__value numeric">{{ summary?.proposal_total ?? total }}</p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">可建表</p>
      <p class="stat-card__value numeric">{{ summary?.schema_ready_count ?? summary?.ddl_ready_count ?? "—" }}</p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">已激活</p>
      <p class="stat-card__value numeric">{{ summary?.activated_count ?? "—" }}</p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">待审提案</p>
      <p class="stat-card__value numeric">{{ summary?.pending_count ?? "—" }}</p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">有探针</p>
      <p class="stat-card__value numeric">{{ summary?.configured_count ?? "—" }}</p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">待 probe</p>
      <p class="stat-card__value numeric">{{ summary?.unconfigured_count ?? "—" }}</p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">漂移</p>
      <p class="stat-card__value numeric">{{ summary?.drift_count ?? "—" }}</p>
    </div>
  </div>

  <div class="panel">
    <div class="panel__header">
      <span>接口字段 ↔ 平台 Schema 对照</span>
      <span v-if="loading" class="panel__header-count">加载中…</span>
    </div>
    <div class="panel__body">
      <p class="panel__hint">
        只读检视：数据来自 TIA 提案列表。批准、L3 激活与 Schema 持久化请在「提案治理」Tab 完成。
      </p>
      <div class="bulk-export-bar">
        <span class="muted">批量导出（当前筛选）：</span>
        <button type="button" class="btn btn--ghost btn--sm" @click="downloadBundle('zip_json_schema')">
          ZIP · JSON Schema
        </button>
        <button type="button" class="btn btn--ghost btn--sm" @click="downloadBundle('zip_openapi')">
          ZIP · OpenAPI
        </button>
        <button type="button" class="btn btn--ghost btn--sm" @click="downloadBundle('openapi')">
          OpenAPI 聚合
        </button>
      </div>
      <div class="filter-bar">
        <div class="filter-tabs">
          <button
            v-for="tab in domainTabs"
            :key="tab.key"
            type="button"
            class="filter-tab"
            :class="{ active: domainFilter === tab.key }"
            @click="domainFilter = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>
        <div class="filter-tabs">
          <button
            v-for="tab in providerTabs"
            :key="'p-' + tab.key"
            type="button"
            class="filter-tab"
            :class="{ active: providerFilter === tab.key }"
            @click="providerFilter = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>
        <div class="filter-controls">
          <select v-model="proposalStatusFilter" class="input input--sm">
            <option value="">提案：全部</option>
            <option value="pending">待审</option>
            <option value="approved">已批准</option>
            <option value="applied">已激活</option>
            <option value="rejected">已拒绝</option>
            <option value="failed">失败</option>
          </select>
          <select v-model="schemaStageFilter" class="input input--sm">
            <option value="">Schema：全部</option>
            <option value="await_probe">待 probe</option>
            <option value="schema_preview">预览对照</option>
            <option value="schema_persisted">已写入 override</option>
            <option value="schema_ready">可建表</option>
            <option value="activated">已激活</option>
          </select>
          <select v-model="probeStatusFilter" class="input input--sm">
            <option value="">字段来源：全部</option>
            <option value="configured">Catalog 探针</option>
            <option value="template">模板推断</option>
            <option value="unconfigured">待 probe</option>
          </select>
          <select v-model="driftStatusFilter" class="input input--sm">
            <option value="">漂移：全部</option>
            <option value="none">无漂移</option>
            <option value="doc_drift">文档漂移</option>
            <option value="live_drift">实测漂移</option>
            <option value="ddl_drift">表结构漂移</option>
          </select>
          <select v-model="coverageFilter" class="input input--sm" @change="loadStandards">
            <option value="">对照：全部</option>
            <option value="full">完全匹配</option>
            <option value="partial">部分匹配</option>
            <option value="gap">存在缺口</option>
          </select>
          <input
            v-model="searchQuery"
            type="search"
            class="input input--sm"
            placeholder="搜索接口 / 名称"
            @keyup.enter="onSearch"
          />
          <button type="button" class="btn btn--ghost btn--sm" @click="onSearch">搜索</button>
        </div>
      </div>
    </div>
    <div class="panel__body panel__body--flush">
      <table v-if="standards.length" class="data-table">
        <thead>
          <tr>
            <th>接口</th>
            <th>域</th>
            <th>源</th>
            <th>提案</th>
            <th>Schema 阶段</th>
            <th>漂移</th>
            <th>字段来源</th>
            <th>API 字段</th>
            <th>平台列</th>
            <th>缺口</th>
            <th>唯一键</th>
            <th>对照率</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="s in standards" :key="s.api_name">
            <tr :class="{ 'row-selected': selectedApi === s.api_name }">
              <td>
                <code>{{ s.api_name }}</code>
                <span class="muted"> · {{ s.label }}</span>
              </td>
              <td>{{ domainLabel(s.domain) }}</td>
              <td>{{ providerLabel(s.provider_id ?? "tushare") }}</td>
              <td>
                <button
                  type="button"
                  class="btn btn--ghost btn--sm proposal-link"
                  @click="openProposal(s.proposal_id)"
                >
                  {{ proposalStatusLabel(s.proposal_status) }}
                </button>
              </td>
              <td>
                <span class="badge" :class="schemaStageClass(s.schema_stage)">
                  {{ schemaStageLabel(s.schema_stage) }}
                </span>
              </td>
              <td>
                <span class="badge" :class="driftStatusClass(s.drift_status ?? 'none')">
                  {{ driftStatusLabel(s.drift_status ?? "none") }}
                </span>
              </td>
              <td>
                <span class="badge badge--muted">{{ fieldSourceLabel(s.field_source) }}</span>
              </td>
              <td class="numeric">{{ s.api_field_count }}</td>
              <td class="numeric">{{ s.standard_field_count }}</td>
              <td class="numeric">
                <span v-if="s.missing_count" class="gap-count">{{ s.missing_count }}</span>
                <span v-else class="muted">0</span>
              </td>
              <td class="numeric">
                <code v-if="s.unique_keys.length" class="uk-cell">{{ s.unique_keys.join(", ") }}</code>
                <span v-else class="muted">—</span>
              </td>
              <td class="numeric">
                <span class="coverage" :class="coverageClass(s.coverage_pct)">
                  {{ s.coverage_pct }}%
                </span>
              </td>
              <td class="actions-cell">
                <button
                  type="button"
                  class="btn btn--ghost btn--sm"
                  :disabled="s.probe_status === 'unconfigured'"
                  @click="selectApi(s.api_name)"
                >
                  {{ selectedApi === s.api_name ? "收起" : "对照" }}
                </button>
                <button
                  v-if="s.probe_status !== 'unconfigured'"
                  type="button"
                  class="btn btn--ghost btn--sm"
                  @click="exportJsonSchema(s)"
                >
                  导出
                </button>
                <a
                  v-if="s.doc_url"
                  :href="s.doc_url"
                  target="_blank"
                  rel="noopener"
                  class="btn btn--ghost btn--sm"
                >
                  文档
                </a>
                <button
                  v-if="s.is_activated"
                  type="button"
                  class="btn btn--ghost btn--sm"
                  @click="browseActivated(s)"
                >
                  查询
                </button>
              </td>
            </tr>
            <tr v-if="selectedApi === s.api_name">
              <td colspan="13">
                <div v-if="detailLoading" class="muted">加载字段对照…</div>
                <div v-else-if="detail" class="detail-block">
                  <div class="detail-meta">
                    <span v-if="detail.table_name">
                      表名：<code>{{ detail.table_name }}</code>
                    </span>
                    <span v-if="detail.naming_compliance">
                      命名合规：{{ detail.naming_compliance.score }} 分
                      <span v-if="detail.naming_compliance.issues.length" class="warn-text">
                        （{{ detail.naming_compliance.issues.join("; ") }}）
                      </span>
                    </span>
                    <span v-if="driftDetail && driftDetail.drift_status !== 'none'">
                      漂移：{{ driftStatusLabel(driftDetail.drift_status) }}
                      <span v-if="driftDetail.live_drift.has_drift" class="muted">
                        实测 ±{{ driftDetail.live_drift.missing.length }}/{{ driftDetail.live_drift.extra.length }}
                      </span>
                    </span>
                    <span>
                      唯一键：
                      <code v-if="detail.unique_keys.length">{{ detail.unique_keys.join(", ") }}</code>
                      <span v-else class="muted">—</span>
                    </span>
                    <span v-if="detail.unique_constraint">
                      约束：
                      <code>{{ detail.unique_constraint.name }}</code>
                    </span>
                    <span v-if="detail.indexes?.length">
                      索引 {{ detail.indexes.length }} 个
                      <span class="muted">
                        （{{ detail.indexes.map((i) => i.name).join(", ") }}）
                      </span>
                    </span>
                    <span>
                      探针：{{ probeStatusLabel(detail.probe_status) }}
                    </span>
                    <span v-if="detail.extra_count" class="muted">
                      多余列 {{ detail.extra_count }}
                    </span>
                    <span v-if="detail.field_mappings && Object.keys(detail.field_mappings).length">
                      映射：
                      <code>{{ JSON.stringify(detail.field_mappings) }}</code>
                    </span>
                    <span v-if="detail.ddl_errors.length" class="warn-text">
                      L3 建表阻塞：{{ detail.ddl_errors.join("; ") }}
                    </span>
                    <button
                      v-if="detail.is_activated"
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="browseActivated(detail)"
                    >
                      数据查询
                    </button>
                    <RouterLink
                      v-if="qualitySuggestions?.suggestions.length"
                      :to="{ path: '/quality', query: { data_type: detail.data_type } }"
                      class="btn btn--ghost btn--sm"
                    >
                      质检建议 ({{ qualitySuggestions.suggestions.length }})
                    </RouterLink>
                    <button
                      v-if="detail.is_activated && detail.proposal_id"
                      type="button"
                      class="btn btn--ghost btn--sm"
                      @click="openSchemaMaintenance(detail)"
                    >
                      Schema 运维
                    </button>
                    <button type="button" class="btn btn--ghost btn--sm" @click="exportJsonSchema(detail)">
                      导出 JSON Schema
                    </button>
                    <button type="button" class="btn btn--ghost btn--sm" @click="exportOpenApi(detail)">
                      导出 OpenAPI
                    </button>
                  </div>
                  <p
                    v-if="qualitySuggestions?.suggestions.length"
                    class="panel__hint quality-hint"
                  >
                    建议 no_nulls 列：
                    {{ qualitySuggestions.suggestions.map((q) => q.column).join(", ") }}
                    （须在质量监控页确认创建）
                  </p>
                  <table class="mini-table">
                    <thead>
                      <tr>
                        <th>API 字段</th>
                        <th>推断类型</th>
                        <th>平台列 key</th>
                        <th>列 label</th>
                        <th>列 type</th>
                        <th>唯一键</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="f in detail.fields" :key="f.api_field">
                        <td><code>{{ f.api_field }}</code></td>
                        <td>{{ f.inferred_type }}</td>
                        <td>{{ f.standard_key ?? "—" }}</td>
                        <td>{{ f.standard_label ?? "—" }}</td>
                        <td>{{ f.standard_type ?? "—" }}</td>
                        <td>{{ f.is_unique_key ? "是" : "—" }}</td>
                        <td>
                          <span class="badge" :class="statusClass(f.status)">
                            {{ statusLabel(f.status) }}
                          </span>
                        </td>
                      </tr>
                      <tr v-for="f in detail.extra_fields" :key="'extra-' + f.api_field">
                        <td class="muted">—</td>
                        <td>{{ f.inferred_type }}</td>
                        <td><code>{{ f.standard_key }}</code></td>
                        <td>{{ f.standard_label }}</td>
                        <td>{{ f.standard_type }}</td>
                        <td>{{ f.is_unique_key ? "是" : "—" }}</td>
                        <td>
                          <span class="badge" :class="statusClass(f.status)">
                            {{ statusLabel(f.status) }}
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-else-if="!loading" class="empty-state empty-state--compact">
        无匹配接口；可调整筛选或先在提案治理 Tab 运行 TIA 扫描
      </p>
    </div>
  </div>
</template>

<style scoped>
.bulk-export-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.75rem;
  font-size: 0.85rem;
}

.filter-bar {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.filter-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.input--sm {
  max-width: 10rem;
  font-size: 0.85rem;
}

.actions-cell {
  white-space: nowrap;
}

.row-selected {
  background: var(--color-surface-muted);
}

.coverage {
  font-weight: 600;
}

.coverage--full {
  color: var(--color-ok-text);
}

.coverage--partial {
  color: var(--color-warn-text);
}

.coverage--gap {
  color: var(--color-err-text);
}

.gap-count {
  color: var(--color-err-text);
  font-weight: 600;
}

.detail-block {
  padding: 0.5rem 0;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 0.75rem;
  font-size: 0.85rem;
}

.mini-table {
  width: 100%;
  font-size: 0.8rem;
  border-collapse: collapse;
}

.mini-table th,
.mini-table td {
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}

.badge--warn {
  background: var(--color-warn-bg);
  color: var(--color-warn-text);
}

.warn-text {
  color: var(--color-warn-text);
}

.muted {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
</style>
