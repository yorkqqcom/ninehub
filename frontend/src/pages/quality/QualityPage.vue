<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { apiRequest } from "@/api/client";
import type { PageResponse, QualityReport, QualityRule, QualitySuggestionsResponse } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const route = useRoute();
const rules = ref<QualityRule[]>([]);
const reports = ref<QualityReport[]>([]);
const running = ref(false);
const asyncMode = ref(false);
const catalogTypes = ref<Array<{ data_type: string; label: string }>>([]);
const schemaSuggestions = ref<QualitySuggestionsResponse | null>(null);
const suggestionsLoading = ref(false);
const ruleForm = ref({
  name: "最少行数",
  rule_type: "min_rows",
  threshold: 1,
  target_data_type: "",
});
const runDataType = ref("");
const runStockCode = ref("");
const reportFilterType = ref("");
const reportFilterStatus = ref("");
const reportPage = ref(1);
const reportPageSize = ref(20);
const reportTotal = ref(0);
const REPORT_PAGE_SIZES = [20, 50, 100] as const;

const maxReportPage = computed(() =>
  Math.max(1, Math.ceil(reportTotal.value / reportPageSize.value)),
);

function pickDataType(types: Array<{ data_type: string }>): string {
  const fromQuery = route.query.data_type;
  if (typeof fromQuery === "string" && types.some((t) => t.data_type === fromQuery)) {
    return fromQuery;
  }
  return types[0]?.data_type ?? "";
}

async function loadSchemaSuggestions(dataType: string) {
  suggestionsLoading.value = true;
  schemaSuggestions.value = null;
  try {
    schemaSuggestions.value = await apiRequest<QualitySuggestionsResponse>(
      `/api/v1/catalog/data-standards/by-data-type/${encodeURIComponent(dataType)}/quality-suggestions`,
    );
  } catch {
    schemaSuggestions.value = null;
  } finally {
    suggestionsLoading.value = false;
  }
}

onMounted(async () => {
  const types = await apiRequest<{ items: Array<{ data_type: string; label: string }> }>(
    "/api/v1/catalog/data-types",
  );
  catalogTypes.value = types.items;
  const selected = pickDataType(types.items);
  ruleForm.value.target_data_type = selected;
  runDataType.value = selected;
  if (selected) {
    void loadSchemaSuggestions(selected);
  }
  await Promise.all([loadRules(), loadReports()]);
});

async function loadRules() {
  const data = await apiRequest<PageResponse<QualityRule>>("/api/v1/quality/rules?limit=50");
  rules.value = data.items;
}

async function loadReports() {
  const skip = (reportPage.value - 1) * reportPageSize.value;
  const params = new URLSearchParams({
    limit: String(reportPageSize.value),
    skip: String(skip),
  });
  if (reportFilterType.value) params.set("data_type", reportFilterType.value);
  if (reportFilterStatus.value) params.set("status", reportFilterStatus.value);
  const data = await apiRequest<PageResponse<QualityReport>>(
    `/api/v1/quality/reports?${params.toString()}`,
  );
  reports.value = data.items;
  reportTotal.value = data.total;
}

function onReportFilterChange() {
  reportPage.value = 1;
  void loadReports();
}

function prevReportPage() {
  if (reportPage.value > 1) {
    reportPage.value -= 1;
    void loadReports();
  }
}

function nextReportPage() {
  if (reportPage.value < maxReportPage.value) {
    reportPage.value += 1;
    void loadReports();
  }
}

function onReportPageSizeChange() {
  reportPage.value = 1;
  void loadReports();
}

async function toggleRule(rule: QualityRule) {
  if (!auth.isAdmin) return;
  await apiRequest(`/api/v1/quality/rules/${rule.id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_enabled: !rule.is_enabled }),
  });
  ui.showMessage(rule.is_enabled ? "规则已禁用" : "规则已启用", "success");
  await loadRules();
}

async function createRule() {
  if (!auth.isAdmin) return;
  await apiRequest("/api/v1/quality/rules", {
    method: "POST",
    body: JSON.stringify(ruleForm.value),
  });
  ui.showMessage("规则已创建", "success");
  await loadRules();
}

async function createSuggestedRule(suggestion: QualitySuggestionsResponse["suggestions"][number]) {
  if (!auth.isAdmin) return;
  const name = `${suggestion.target_data_type} ${suggestion.column} 非空`;
  await apiRequest("/api/v1/quality/rules", {
    method: "POST",
    body: JSON.stringify({
      name,
      rule_type: suggestion.rule_type,
      target_data_type: suggestion.target_data_type,
      config_json: suggestion.config_json ?? { fields: [suggestion.column] },
      is_enabled: true,
    }),
  });
  ui.showMessage(`已创建规则：${name}`, "success");
  await loadRules();
}

async function onRunDataTypeChange() {
  if (runDataType.value) {
    await loadSchemaSuggestions(runDataType.value);
  }
}

async function runQuality() {
  if (!auth.isAdmin || !runDataType.value) return;
  running.value = true;
  try {
    const res = await apiRequest<{ reports_created: number; message: string; alerts_sent?: number; job_id?: number }>(
      "/api/v1/quality/run",
      {
        method: "POST",
        body: JSON.stringify({
          data_type: runDataType.value,
          stock_code: runStockCode.value.trim() || undefined,
          async_mode: asyncMode.value,
        }),
      },
    );
    const extra = res.job_id
      ? `Job #${res.job_id}`
      : res.alerts_sent
        ? `，告警 ${res.alerts_sent} 条`
        : "";
    ui.showMessage(res.message + extra, "success");
    await loadReports();
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    running.value = false;
  }
}

function statusBadge(status: string) {
  return status === "passed" ? "badge--ok" : status === "failed" ? "badge--err" : "badge--muted";
}
</script>

<template>
  <PageHeader title="数据质量" description="质检报告与规则引擎">
    <template v-if="auth.isAdmin" #actions>
      <label class="form-field form-field--inline">
        <input v-model="asyncMode" type="checkbox" />
        <span>异步</span>
      </label>
      <label class="form-field form-field--inline" v-if="catalogTypes.length">
        <span>数据类型</span>
        <select v-model="runDataType" class="input-w-md" @change="onRunDataTypeChange">
          <option v-for="t in catalogTypes" :key="t.data_type" :value="t.data_type">
            {{ t.label }}
          </option>
        </select>
      </label>
      <label class="form-field form-field--inline">
        <span>股票代码</span>
        <input v-model="runStockCode" class="input-w-md" placeholder="可选，留空查全表" />
      </label>
      <button type="button" class="btn btn--primary" :disabled="running || !runDataType" @click="runQuality">
        触发质检
      </button>
    </template>
  </PageHeader>

  <div
    v-if="schemaSuggestions?.suggestions.length && auth.isAdmin"
    class="panel"
  >
    <div class="panel__header">
      数据标准建议 · {{ schemaSuggestions.data_type }}
      <span v-if="suggestionsLoading" class="panel__header-count">加载中…</span>
    </div>
    <div class="panel__body">
      <p class="panel__hint">
        来自 catalog schema 的 no_nulls 建议（{{ schemaSuggestions.api_name }}）
      </p>
      <div class="suggestion-list">
        <button
          v-for="s in schemaSuggestions.suggestions"
          :key="s.column"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="createSuggestedRule(s)"
        >
          创建 {{ s.column }} 非空
        </button>
      </div>
    </div>
  </div>

  <div v-if="auth.isAdmin" class="panel">
    <div class="panel__header">新建规则</div>
    <div class="panel__body page-toolbar">
      <label class="form-field">
        <span>名称</span>
        <input v-model="ruleForm.name" class="input-w-md" />
      </label>
      <label class="form-field">
        <span>类型</span>
        <select v-model="ruleForm.rule_type" class="input-w-md">
          <option value="min_rows">最少行数</option>
          <option value="no_nulls">非空校验</option>
        </select>
      </label>
      <label class="form-field">
        <span>阈值</span>
        <input v-model.number="ruleForm.threshold" type="number" class="input-w-sm" />
      </label>
      <label class="form-field">
        <span>数据类型</span>
        <select v-model="ruleForm.target_data_type" class="input-w-md">
          <option v-for="t in catalogTypes" :key="t.data_type" :value="t.data_type">
            {{ t.label }}
          </option>
        </select>
      </label>
      <button type="button" class="btn btn--secondary" @click="createRule">添加规则</button>
    </div>
  </div>

  <div class="page-split">
    <div class="panel">
      <div class="panel__header">规则 ({{ rules.length }})</div>
      <div class="panel__body panel__body--flush">
        <table v-if="rules.length" class="data-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>目标</th>
              <th>启用</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rules" :key="r.id">
              <td>{{ r.name }}</td>
              <td>{{ r.rule_type }}</td>
              <td>{{ r.target_data_type }}</td>
              <td>
                <button
                  v-if="auth.isAdmin"
                  type="button"
                  class="btn btn--ghost btn--sm"
                  @click="toggleRule(r)"
                >
                  {{ r.is_enabled ? "禁用" : "启用" }}
                </button>
                <span v-else>{{ r.is_enabled ? "是" : "否" }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state empty-state--compact">暂无规则</p>
      </div>
    </div>

    <div class="panel">
      <div class="panel__header">
        报告 ({{ reportTotal }})
        <span class="panel__header-actions">
          <select v-model="reportFilterType" class="input-w-md" @change="onReportFilterChange">
            <option value="">全部类型</option>
            <option v-for="t in catalogTypes" :key="t.data_type" :value="t.data_type">
              {{ t.label }}
            </option>
          </select>
          <select v-model="reportFilterStatus" class="input-w-sm" @change="onReportFilterChange">
            <option value="">全部状态</option>
            <option value="passed">passed</option>
            <option value="failed">failed</option>
          </select>
        </span>
      </div>
      <div class="panel__body panel__body--flush">
        <table v-if="reports.length" class="data-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>代码</th>
              <th>状态</th>
              <th>详情</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reports" :key="r.id">
              <td>{{ r.data_type }}</td>
              <td>{{ r.stock_code ?? "—" }}</td>
              <td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
              <td><code>{{ JSON.stringify(r.detail_json) }}</code></td>
              <td>{{ r.created_at }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state empty-state--compact">暂无报告，admin 可触发质检</p>
      </div>
      <div v-if="reportTotal > 0" class="panel__footer report-pagination">
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          :disabled="reportPage <= 1"
          @click="prevReportPage"
        >
          上一页
        </button>
        <span class="report-pagination__info">
          第 {{ reportPage }} / {{ maxReportPage }} 页
        </span>
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          :disabled="reportPage >= maxReportPage"
          @click="nextReportPage"
        >
          下一页
        </button>
        <select
          v-model.number="reportPageSize"
          class="input input--inline report-pagination__size"
          @change="onReportPageSizeChange"
        >
          <option v-for="sz in REPORT_PAGE_SIZES" :key="sz" :value="sz">{{ sz }} 条/页</option>
        </select>
      </div>
    </div>
  </div>
</template>

<style scoped>
.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.panel__header-actions {
  display: inline-flex;
  gap: 0.5rem;
  margin-left: auto;
  font-weight: normal;
  font-size: 0.875rem;
}

.report-pagination {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 10px;
  border-top: 1px solid var(--color-border);
  font-size: 0.875rem;
}

.report-pagination__info {
  color: var(--color-text-muted);
}

.report-pagination__size {
  margin-left: auto;
  width: auto;
}
</style>
