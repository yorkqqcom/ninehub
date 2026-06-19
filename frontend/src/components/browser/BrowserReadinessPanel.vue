<script setup lang="ts">
import { onMounted, ref } from "vue";
import { apiRequest } from "@/api/client";
import type { BrowserReadinessResponse } from "@/api/types";

defineOptions({ name: "BrowserReadinessPanel" });

const props = withDefaults(
  defineProps<{
    compact?: boolean;
    autoLoad?: boolean;
  }>(),
  { compact: false, autoLoad: true },
);

const loading = ref(false);
const readiness = ref<BrowserReadinessResponse | null>(null);

async function load() {
  loading.value = true;
  try {
    readiness.value = await apiRequest<BrowserReadinessResponse>(
      "/api/v1/query/browser/readiness",
    );
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (props.autoLoad) void load();
});

defineExpose({ load, readiness });
</script>

<template>
  <div v-if="loading" class="browser-readiness muted">检查数据就绪…</div>
  <div v-else-if="readiness" class="browser-readiness">
    <div v-if="!compact" class="browser-readiness__header">
      <span class="badge" :class="readiness.p0_ok ? 'badge--ok' : 'badge--err'">
        P0 {{ readiness.p0_ok ? "通过" : "未通过" }}
      </span>
      <button type="button" class="btn btn--ghost btn--sm" @click="load">刷新</button>
    </div>

    <div
      v-if="compact && (!readiness.p0_ok || readiness.warnings.length)"
      class="browser-readiness__banner"
      :class="readiness.p0_ok ? 'browser-readiness__banner--warn' : 'browser-readiness__banner--err'"
    >
      <template v-if="!readiness.p0_ok">
        数据浏览器 P0 未就绪：{{ readiness.errors[0] }}
      </template>
      <template v-else>
        {{ readiness.warnings[0] }}
      </template>
    </div>

    <table v-if="!compact" class="data-table browser-readiness__table">
      <thead>
        <tr>
          <th>级别</th>
          <th>数据</th>
          <th>状态</th>
          <th>行数</th>
          <th>建议</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in readiness.items" :key="item.data_type">
          <td>{{ item.level.toUpperCase() }}</td>
          <td>{{ item.label }}</td>
          <td>
            <span class="badge" :class="item.ok ? 'badge--ok' : 'badge--warn'">
              {{ item.ok ? "就绪" : item.message ?? "待补" }}
            </span>
          </td>
          <td class="numeric">
            <template v-if="item.row_count != null">
              {{ item.row_count.toLocaleString() }}
              <span v-if="item.min_rows" class="muted"> / {{ item.min_rows }}</span>
            </template>
            <span v-else>—</span>
          </td>
          <td>
            <code v-if="item.suggested_script">python scripts/{{ item.suggested_script }}</code>
            <span v-else class="muted">—</span>
          </td>
        </tr>
      </tbody>
    </table>

    <ul v-if="!compact && readiness.warnings.length" class="browser-readiness__warnings">
      <li v-for="(w, i) in readiness.warnings" :key="i">{{ w }}</li>
    </ul>
  </div>
</template>

<style scoped>
.browser-readiness__header {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}

.browser-readiness__banner {
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-md);
  margin-bottom: var(--space-md);
}

.browser-readiness__banner--warn {
  background: var(--color-warn-bg);
  color: var(--color-warn-text);
  border: 1px solid var(--color-border);
}

.browser-readiness__banner--err {
  background: var(--color-err-bg);
  color: var(--color-err-text);
  border: 1px solid var(--color-border);
}

.browser-readiness__table {
  font-size: var(--font-size-sm);
}

.browser-readiness__warnings {
  margin: var(--space-md) 0 0;
  padding-left: 1.25rem;
  font-size: var(--font-size-sm);
  color: var(--color-warn-text);
}
</style>
