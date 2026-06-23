<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { apiRequest } from "@/api/client";
import { useUiStore } from "@/stores/ui";

const router = useRouter();

type CoverageSummary = {
  local_count: number;
  official_count: number;
  unchanged_count: number;
  new_on_official_count: number;
  local_only_count: number;
  coverage_pct: number;
  official_index_source: string;
  official_index_scope: string;
  official_index_total: number;
};

type CoverageItem = { api: string; reason: string };

type CoverageResponse = {
  summary: CoverageSummary;
  new_on_official_sample: CoverageItem[];
  local_only_sample: CoverageItem[];
  unchanged_sample: CoverageItem[];
};

const ui = useUiStore();
const loading = ref(false);
const coverage = ref<CoverageResponse | null>(null);
const indexScope = ref<"mixed" | "stock_a">("stock_a");

async function loadCoverage() {
  loading.value = true;
  try {
    const params = new URLSearchParams({
      index_scope: indexScope.value,
      index_source: "document2",
    });
    coverage.value = await apiRequest<CoverageResponse>(`/api/v1/catalog/coverage?${params}`);
  } catch (e) {
    coverage.value = null;
    ui.showMessage(e instanceof Error ? e.message : "加载覆盖对照失败", "error");
  } finally {
    loading.value = false;
  }
}

onMounted(() => void loadCoverage());

function openStandard(api: string) {
  void router.push({ name: "standards", query: { api } });
}
</script>

<template>
  <div class="panel">
    <div class="panel__header">
      <span>官网索引覆盖</span>
      <span v-if="loading" class="panel__header-count">加载中…</span>
    </div>
    <div class="panel__body">
      <p class="panel__hint">
        对照本地 catalog（quota + L1 override）与 Tushare 官方索引，无需触发扫描 Job。
      </p>
      <div class="filter-controls">
        <label>
          类目范围
          <select v-model="indexScope" class="input input--sm" @change="loadCoverage">
            <option value="stock_a">股票数据</option>
            <option value="mixed">全菜单</option>
          </select>
        </label>
        <button type="button" class="btn btn--ghost btn--sm" :disabled="loading" @click="loadCoverage">
          刷新
        </button>
      </div>

      <div v-if="coverage" class="stat-strip stat-strip--inline">
        <div class="stat-card stat-card--compact">
          <p class="stat-card__label">本地</p>
          <p class="stat-card__value numeric">{{ coverage.summary.local_count }}</p>
        </div>
        <div class="stat-card stat-card--compact">
          <p class="stat-card__label">官网</p>
          <p class="stat-card__value numeric">{{ coverage.summary.official_count }}</p>
        </div>
        <div class="stat-card stat-card--compact">
          <p class="stat-card__label">一致</p>
          <p class="stat-card__value numeric">{{ coverage.summary.unchanged_count }}</p>
        </div>
        <div class="stat-card stat-card--compact">
          <p class="stat-card__label">覆盖率</p>
          <p class="stat-card__value numeric">{{ coverage.summary.coverage_pct }}%</p>
        </div>
        <div class="stat-card stat-card--compact">
          <p class="stat-card__label">官网新增</p>
          <p class="stat-card__value numeric">{{ coverage.summary.new_on_official_count }}</p>
        </div>
        <div class="stat-card stat-card--compact">
          <p class="stat-card__label">本地独有</p>
          <p class="stat-card__value numeric">{{ coverage.summary.local_only_count }}</p>
        </div>
      </div>

      <p v-if="coverage" class="meta-line">
        索引来源 {{ coverage.summary.official_index_source }} · 范围 {{ coverage.summary.official_index_scope }}
      </p>

      <div v-if="coverage" class="coverage-grid">
        <div class="coverage-block">
          <h3 class="coverage-block__title">官网新增（样本）</h3>
          <ul v-if="coverage.new_on_official_sample.length" class="coverage-list">
            <li v-for="item in coverage.new_on_official_sample" :key="item.api">
              <code>{{ item.api }}</code>
              <button type="button" class="btn btn--ghost btn--sm" @click="openStandard(item.api)">
                标准
              </button>
            </li>
          </ul>
          <p v-else class="empty-state empty-state--compact">无样本</p>
        </div>
        <div class="coverage-block">
          <h3 class="coverage-block__title">本地独有（样本）</h3>
          <ul v-if="coverage.local_only_sample.length" class="coverage-list">
            <li v-for="item in coverage.local_only_sample" :key="item.api">
              <code>{{ item.api }}</code>
              <button type="button" class="btn btn--ghost btn--sm" @click="openStandard(item.api)">
                标准
              </button>
            </li>
          </ul>
          <p v-else class="empty-state empty-state--compact">无样本</p>
        </div>
        <div class="coverage-block">
          <h3 class="coverage-block__title">已对齐（样本）</h3>
          <ul v-if="coverage.unchanged_sample.length" class="coverage-list">
            <li v-for="item in coverage.unchanged_sample" :key="item.api">
              <code>{{ item.api }}</code>
            </li>
          </ul>
          <p v-else class="empty-state empty-state--compact">无样本</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: var(--space-md);
}

.filter-controls label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
}

.coverage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-md);
  margin-top: var(--space-md);
}

.coverage-block__title {
  font-size: 0.85rem;
  margin: 0 0 0.5rem;
  color: var(--color-text-muted);
}

.coverage-list li {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.25rem;
}

.stat-strip--inline {
  margin-bottom: var(--space-sm);
}
</style>
