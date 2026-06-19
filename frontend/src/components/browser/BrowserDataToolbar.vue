<script setup lang="ts">
defineOptions({ name: "BrowserDataToolbar" });

withDefaults(
  defineProps<{
    loadingData: boolean;
    hasIndicators: boolean;
    hasUniverse?: boolean;
    cacheHit: boolean;
    hasResult: boolean;
    exportFormat: "csv" | "xlsx";
    viewMode: "table" | "chart";
    extended?: boolean;
    exportDownloadUrl?: string | null;
  }>(),
  { hasUniverse: false, extended: false, exportDownloadUrl: null },
);

const emit = defineEmits<{
  refresh: [];
  export: [];
  exportAsync: [];
  saveTemplate: [];
  share: [];
  saveWatchlist: [];
  loadAudits: [];
  "update:exportFormat": [value: "csv" | "xlsx"];
  "update:viewMode": [value: "table" | "chart"];
}>();
</script>

<template>
  <div class="page-toolbar browser-toolbar browser-toolbar--triple-data">
    <button type="button" class="btn btn--ghost btn--sm" :disabled="loadingData" @click="emit('refresh')">
      刷新
    </button>
    <span v-if="cacheHit" class="badge badge--muted">缓存</span>
    <span v-else-if="hasResult" class="badge badge--info">实时</span>
    <select
      :value="exportFormat"
      class="input input--inline"
      @change="emit('update:exportFormat', ($event.target as HTMLSelectElement).value as 'csv' | 'xlsx')"
    >
      <option value="csv">CSV</option>
      <option value="xlsx">XLSX</option>
    </select>
    <button
      type="button"
      class="btn btn--ghost btn--sm"
      :disabled="!hasIndicators"
      @click="emit('export')"
    >
      导出
    </button>
    <button
      v-if="extended"
      type="button"
      class="btn btn--ghost btn--sm"
      :disabled="!hasIndicators"
      @click="emit('exportAsync')"
    >
      异步导出
    </button>
    <a
      v-if="extended && exportDownloadUrl"
      :href="exportDownloadUrl"
      class="btn btn--ghost btn--sm"
      target="_blank"
      rel="noopener"
    >
      下载
    </a>
    <button type="button" class="btn btn--ghost btn--sm" @click="emit('saveTemplate')">存模板</button>
    <button type="button" class="btn btn--ghost btn--sm" @click="emit('share')">分享</button>
    <button
      v-if="extended"
      type="button"
      class="btn btn--ghost btn--sm"
      :disabled="!hasUniverse"
      @click="emit('saveWatchlist')"
    >
      存证券池
    </button>
    <button v-if="extended" type="button" class="btn btn--ghost btn--sm" @click="emit('loadAudits')">
      审计
    </button>
    <div class="browser-toolbar__view">
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :class="{ active: viewMode === 'table' }"
        @click="emit('update:viewMode', 'table')"
      >
        表
      </button>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :class="{ active: viewMode === 'chart' }"
        @click="emit('update:viewMode', 'chart')"
      >
        图
      </button>
    </div>
  </div>
</template>
