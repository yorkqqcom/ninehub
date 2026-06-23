<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { apiRequest } from "@/api/client";
import type {
  CatalogColumnMeta,
  CatalogFilterMeta,
  DataBrowseResponse,
  DataTypeItem,
  DataTypeListResponse,
} from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";

const RECENT_KEY = "ninehub_browse_recent";
const COLUMN_KEY_PREFIX = "ninehub_browse_cols:";
const PAGE_SIZES = [25, 50, 100, 200] as const;

const DOMAIN_LABELS: Record<string, string> = {
  market: "行情",
  basic: "基础",
  financial: "财务",
  reference: "参考",
  feature: "特色",
  index: "指数",
  macro: "宏观",
};

const route = useRoute();
const router = useRouter();

const browseTypes = ref<DataTypeItem[]>([]);
const browseSummary = ref<DataTypeListResponse["summary"]>(null);
const domainFilter = ref("");
const typeSearch = ref("");
const selectedType = ref("");
const columns = ref<CatalogColumnMeta[]>([]);
const visibleColumnKeys = ref<string[]>([]);
const filtersMeta = ref<CatalogFilterMeta[]>([]);
const rows = ref<Array<Record<string, unknown>>>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const loadingTypes = ref(false);
const loadingData = ref(false);
const stockCode = ref("");
const startDate = ref("");
const endDate = ref("");
const label = ref("");
const tableName = ref("");
const recentTypes = ref<string[]>([]);
const showColumnPicker = ref(false);
const statsLoaded = ref(false);

const domainTabs = computed(() => [
  { key: "", label: "全部" },
  ...Object.entries(DOMAIN_LABELS).map(([key, lbl]) => ({ key, label: lbl })),
]);

const filteredTypes = computed(() => {
  let list = browseTypes.value;
  if (domainFilter.value) {
    list = list.filter((t) => t.domain === domainFilter.value);
  }
  const q = typeSearch.value.trim().toLowerCase();
  if (q) {
    list = list.filter(
      (t) =>
        t.data_type.toLowerCase().includes(q) ||
        t.label.toLowerCase().includes(q) ||
        (t.table_name?.toLowerCase().includes(q) ?? false),
    );
  }
  return list;
});

const visibleColumns = computed(() =>
  columns.value.filter((c) => visibleColumnKeys.value.includes(c.key)),
);

const maxPage = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)));

const hasDateFilter = computed(() =>
  filtersMeta.value.some((f) => f.filter_type === "date_range"),
);

const recentTypeItems = computed(() =>
  recentTypes.value
    .map((dt) => browseTypes.value.find((t) => t.data_type === dt))
    .filter((t): t is DataTypeItem => Boolean(t)),
);

const domainCount = computed(() => {
  if (!browseSummary.value) return filteredTypes.value.length;
  if (!domainFilter.value) return browseSummary.value.total;
  return browseSummary.value.domains.find((d) => d.domain === domainFilter.value)?.count ?? 0;
});

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    recentTypes.value = raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    recentTypes.value = [];
  }
}

function saveRecent(dataType: string) {
  const next = [dataType, ...recentTypes.value.filter((t) => t !== dataType)].slice(0, 8);
  recentTypes.value = next;
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
}

function loadColumnPrefs(dataType: string) {
  try {
    const raw = localStorage.getItem(`${COLUMN_KEY_PREFIX}${dataType}`);
    if (raw) {
      visibleColumnKeys.value = JSON.parse(raw) as string[];
      return;
    }
  } catch {
    /* ignore */
  }
  visibleColumnKeys.value = columns.value.map((c) => c.key);
}

function saveColumnPrefs() {
  if (!selectedType.value) return;
  localStorage.setItem(
    `${COLUMN_KEY_PREFIX}${selectedType.value}`,
    JSON.stringify(visibleColumnKeys.value),
  );
}

function syncQueryToRoute() {
  const query: Record<string, string> = {};
  if (selectedType.value) query.data_type = selectedType.value;
  if (domainFilter.value) query.domain = domainFilter.value;
  if (typeSearch.value.trim()) query.q = typeSearch.value.trim();
  if (stockCode.value.trim()) query.stock_code = stockCode.value.trim();
  if (startDate.value) query.start_date = startDate.value;
  if (endDate.value) query.end_date = endDate.value;
  if (page.value > 1) query.page = String(page.value);
  if (pageSize.value !== 50) query.size = String(pageSize.value);
  void router.replace({ query });
}

function readQueryFromRoute() {
  const q = route.query;
  if (typeof q.domain === "string") domainFilter.value = q.domain;
  if (typeof q.q === "string") typeSearch.value = q.q;
  if (typeof q.stock_code === "string") stockCode.value = q.stock_code;
  if (typeof q.start_date === "string") startDate.value = q.start_date;
  if (typeof q.end_date === "string") endDate.value = q.end_date;
  if (typeof q.page === "string") page.value = Math.max(1, Number(q.page) || 1);
  if (typeof q.size === "string") {
    const sz = Number(q.size);
    if (PAGE_SIZES.includes(sz as (typeof PAGE_SIZES)[number])) pageSize.value = sz;
  }
}

async function loadTypes(withStats = false) {
  loadingTypes.value = true;
  try {
    const params = new URLSearchParams({ browse_only: "true", limit: "500" });
    if (withStats) params.set("include_stats", "true");
    const data = await apiRequest<DataTypeListResponse>(
      `/api/v1/catalog/data-types?${params.toString()}`,
    );
    browseTypes.value = data.items;
    browseSummary.value = data.summary ?? null;
    if (withStats) statsLoaded.value = true;

    const qType = route.query.data_type;
    if (typeof qType === "string" && data.items.some((i) => i.data_type === qType)) {
      selectedType.value = qType;
    } else if (!selectedType.value || !data.items.some((i) => i.data_type === selectedType.value)) {
      const first = filteredTypes.value[0] ?? data.items[0];
      selectedType.value = first?.data_type ?? "";
    }
  } finally {
    loadingTypes.value = false;
  }
}

async function loadData(pageNum = page.value) {
  if (!selectedType.value) return;
  loadingData.value = true;
  try {
    const skip = (pageNum - 1) * pageSize.value;
    const params = new URLSearchParams({
      skip: String(skip),
      limit: String(pageSize.value),
    });
    if (stockCode.value.trim()) params.set("stock_code", stockCode.value.trim());
    if (startDate.value) params.set("start_date", startDate.value);
    if (endDate.value) params.set("end_date", endDate.value);

    const data = await apiRequest<DataBrowseResponse>(
      `/api/v1/catalog/data/${selectedType.value}?${params.toString()}`,
    );
    rows.value = data.items;
    total.value = data.total;
    page.value = data.page;
    columns.value = data.columns;
    filtersMeta.value = data.filters;
    label.value = data.label;
    tableName.value = data.table_name ?? "";
    loadColumnPrefs(selectedType.value);
    saveRecent(selectedType.value);
    syncQueryToRoute();
  } finally {
    loadingData.value = false;
  }
}

function selectType(dataType: string) {
  if (selectedType.value === dataType) return;
  selectedType.value = dataType;
  page.value = 1;
  stockCode.value = "";
  startDate.value = "";
  endDate.value = "";
  void loadData(1);
}

function onSearch() {
  page.value = 1;
  void loadData(1);
}

function onPageSizeChange() {
  page.value = 1;
  void loadData(1);
}

function prevPage() {
  if (page.value <= 1) return;
  void loadData(page.value - 1);
}

function nextPage() {
  if (page.value >= maxPage.value) return;
  void loadData(page.value + 1);
}

function toggleColumn(key: string) {
  const idx = visibleColumnKeys.value.indexOf(key);
  if (idx >= 0) {
    if (visibleColumnKeys.value.length <= 1) return;
    visibleColumnKeys.value = visibleColumnKeys.value.filter((k) => k !== key);
  } else {
    visibleColumnKeys.value = [...visibleColumnKeys.value, key];
  }
  saveColumnPrefs();
}

function domainLabel(domain: string) {
  return DOMAIN_LABELS[domain] ?? domain;
}

function formatCell(value: unknown, col: CatalogColumnMeta) {
  if (value == null) return "—";
  if (col.type === "number" && typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/\.?0+$/, "");
  }
  return String(value);
}

function formatRowCount(count: number | null | undefined) {
  if (count == null) return "";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 10_000) return `${(count / 1_000).toFixed(1)}K`;
  return String(count);
}

onMounted(async () => {
  loadRecent();
  readQueryFromRoute();
  await loadTypes();
  if (selectedType.value) await loadData(page.value);
  void loadTypes(true);
});

watch(
  () => route.query.data_type,
  (v) => {
    if (typeof v === "string" && v !== selectedType.value) {
      selectedType.value = v;
      void loadData(1);
    }
  },
);

watch(domainFilter, () => {
  if (selectedType.value && !filteredTypes.value.some((t) => t.data_type === selectedType.value)) {
    const first = filteredTypes.value[0];
    if (first) selectType(first.data_type);
  }
});
</script>

<template>
  <PageHeader
    title="数据查询"
    description="Catalog 驱动 · 多表域导航 · 动态列与筛选"
  />

  <div v-if="browseSummary" class="stat-strip browse-kpi">
    <div class="stat-card">
      <span class="stat-card__label">可查询表</span>
      <span class="stat-card__value numeric">{{ browseSummary.total }}</span>
    </div>
    <div class="stat-card">
      <span class="stat-card__label">当前域</span>
      <span class="stat-card__value numeric">{{ domainCount }}</span>
    </div>
    <div class="stat-card">
      <span class="stat-card__label">当前表行数</span>
      <span class="stat-card__value numeric">{{ total.toLocaleString() }}</span>
    </div>
    <div v-if="tableName" class="stat-card stat-card--wide">
      <span class="stat-card__label">物理表</span>
      <span class="stat-card__value stat-card__value--mono">{{ tableName }}</span>
    </div>
  </div>

  <div class="browse-layout">
    <aside class="browse-sidebar panel">
      <div class="panel__header">
        <span>数据表</span>
        <span class="panel__header-count numeric">{{ filteredTypes.length }}</span>
      </div>
      <div class="panel__body">
        <input
          v-model="typeSearch"
          type="search"
          class="input browse-sidebar__search"
          placeholder="搜索表名 / 标签 / data_type"
          aria-label="搜索数据表"
        />

        <div class="filter-tabs browse-sidebar__tabs">
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

        <section v-if="recentTypeItems.length" class="browse-sidebar__section">
          <h3 class="browse-sidebar__section-title">最近查询</h3>
          <ul class="browse-type-list">
            <li
              v-for="t in recentTypeItems"
              :key="`recent-${t.data_type}`"
              class="browse-type-item"
              :class="{ active: selectedType === t.data_type }"
              @click="selectType(t.data_type)"
            >
              <span class="browse-type-item__label">{{ t.label }}</span>
              <span class="browse-type-item__meta">{{ t.data_type }}</span>
            </li>
          </ul>
        </section>

        <section class="browse-sidebar__section browse-sidebar__section--grow">
          <h3 class="browse-sidebar__section-title">
            {{ domainFilter ? domainLabel(domainFilter) : "全部" }}
          </h3>
          <p v-if="loadingTypes" class="muted">加载表清单…</p>
          <p v-else-if="!filteredTypes.length" class="muted">
            暂无匹配表。请先在 TIA 完成 L3 激活并启用数据查询。
          </p>
          <ul v-else class="browse-type-list">
            <li
              v-for="t in filteredTypes"
              :key="t.data_type"
              class="browse-type-item"
              :class="{ active: selectedType === t.data_type }"
              @click="selectType(t.data_type)"
            >
              <span class="browse-type-item__label">{{ t.label }}</span>
              <span class="browse-type-item__meta">
                {{ t.data_type }}
                <span v-if="statsLoaded && t.row_count != null" class="browse-type-item__count numeric">
                  {{ formatRowCount(t.row_count) }}
                </span>
              </span>
            </li>
          </ul>
        </section>
      </div>
    </aside>

    <div class="browse-main panel">
      <div class="panel__header">
        <span>{{ label || "数据" }}</span>
        <span class="panel__header-count numeric">{{ total.toLocaleString() }} 行</span>
      </div>
      <div class="panel__body">
        <div class="page-toolbar browse-toolbar">
          <input
            v-model="stockCode"
            type="text"
            class="input input-w-sm"
            placeholder="股票代码 ts_code"
            @keyup.enter="onSearch"
          />
          <template v-if="hasDateFilter">
            <input v-model="startDate" type="date" class="input input-w-sm" aria-label="起始日期" />
            <span class="browse-toolbar__sep">—</span>
            <input v-model="endDate" type="date" class="input input-w-sm" aria-label="结束日期" />
          </template>
          <button type="button" class="btn btn--secondary" :disabled="loadingData" @click="onSearch">
            查询
          </button>
          <button
            type="button"
            class="btn btn--ghost"
            :class="{ active: showColumnPicker }"
            @click="showColumnPicker = !showColumnPicker"
          >
            列显隐
          </button>
        </div>

        <div v-if="showColumnPicker && columns.length" class="column-picker">
          <label v-for="col in columns" :key="col.key" class="column-picker__item">
            <input
              type="checkbox"
              :checked="visibleColumnKeys.includes(col.key)"
              @change="toggleColumn(col.key)"
            />
            {{ col.label }}
          </label>
        </div>

        <div v-if="loadingData" class="muted">加载中…</div>

        <template v-else>
          <div v-if="rows.length && visibleColumns.length" class="table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th v-for="col in visibleColumns" :key="col.key">{{ col.label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in rows" :key="idx">
                  <td
                    v-for="col in visibleColumns"
                    :key="col.key"
                    :class="{ numeric: col.type === 'number' }"
                  >
                    {{ formatCell(row[col.key], col) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else-if="selectedType" class="muted">无数据。可先在采集任务中执行同步。</p>

          <div v-if="total > 0" class="pager">
            <button type="button" class="btn btn--ghost btn--sm" :disabled="page <= 1" @click="prevPage">
              上一页
            </button>
            <span class="pager__info">
              第 {{ page }} / {{ maxPage }} 页 · 共 {{ total.toLocaleString() }} 行
            </span>
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="page >= maxPage"
              @click="nextPage"
            >
              下一页
            </button>
            <select v-model.number="pageSize" class="input input--inline pager__size" @change="onPageSizeChange">
              <option v-for="sz in PAGE_SIZES" :key="sz" :value="sz">{{ sz }} 条/页</option>
            </select>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.browse-kpi {
  margin-bottom: var(--space-md);
}

.stat-card--wide {
  flex: 1.5;
}

.stat-card__value--mono {
  font-family: var(--font-mono, monospace);
  font-size: var(--font-size-sm);
}

.browse-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: var(--space-md);
  min-height: 0;
}

.browse-sidebar__search {
  width: 100%;
  margin-bottom: var(--space-sm);
}

.browse-sidebar__tabs {
  margin-bottom: var(--space-md);
  flex-wrap: wrap;
}

.browse-sidebar__section {
  margin-bottom: var(--space-md);
}

.browse-sidebar__section--grow {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.browse-sidebar__section-title {
  margin: 0 0 var(--space-xs);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.browse-sidebar .panel__body {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 220px);
  overflow: hidden;
}

.browse-type-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  flex: 1;
}

.browse-type-item {
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 1px solid transparent;
}

.browse-type-item:hover {
  background: var(--color-row-hover);
}

.browse-type-item.active {
  background: var(--color-nav-active-bg, var(--color-row-active));
  border-color: var(--color-primary);
}

.browse-type-item__label {
  display: block;
  font-size: var(--font-size-md);
  color: var(--color-text);
}

.browse-type-item__meta {
  display: flex;
  justify-content: space-between;
  gap: var(--space-xs);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.browse-type-item__count {
  color: var(--color-text-secondary);
}

.browse-toolbar {
  margin-bottom: var(--space-md);
}

.browse-toolbar__sep {
  color: var(--color-text-muted);
}

.column-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs) var(--space-md);
  margin-bottom: var(--space-md);
  padding: var(--space-sm);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  max-height: 120px;
  overflow-y: auto;
}

.column-picker__item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.table-scroll {
  overflow-x: auto;
  max-width: 100%;
}

.pager {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-top: var(--space-md);
  flex-wrap: wrap;
}

.pager__info {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.pager__size {
  margin-left: auto;
}

.btn.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

@media (max-width: 900px) {
  .browse-layout {
    grid-template-columns: 1fr;
  }

  .browse-sidebar .panel__body {
    max-height: 240px;
  }
}
</style>
