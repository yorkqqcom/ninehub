<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import Sortable from "sortablejs";
import draggable from "vuedraggable";
import { apiRequest } from "@/api/client";
import type {
  BrowserIndicatorRef,
  BrowserIndicatorTreeNode,
  DomainItem,
} from "@/api/types";
import BrowserIndicatorTree from "@/components/browser/BrowserIndicatorTree.vue";
import {
  BROWSER_INDICATOR_SOURCE_GROUP,
  canDragIndicator,
  cloneIndicatorPick,
  indicatorDragDataset,
} from "./browserDragUtils";
import {
  countTreeLeaves,
  domainStats,
  filterTreeByDataReady,
  filterTreeByDomain,
  filterTreeByIds,
  FREQ_LABELS,
  uniqueGroups,
} from "./indicatorUtils";

defineOptions({ name: "BrowserIndicatorPicker" });

const props = defineProps<{
  indicatorsFlat: BrowserIndicatorRef[];
  indicatorTree: BrowserIndicatorTreeNode[];
  domains: DomainItem[];
  selectedIds: string[];
  loading?: boolean;
  timeMode?: "single" | "multi";
  embedded?: boolean;
}>();

const emit = defineEmits<{
  pick: [ind: BrowserIndicatorRef];
}>();

const searchQ = ref("");
const selectedTags = ref<string[]>([]);
const dataReadyOnly = ref(true);
const activeDomain = ref<string | null>(null);
const selectedGroup = ref<string | null>(null);
const serverSearchResults = ref<BrowserIndicatorRef[] | null>(null);
const searchLoading = ref(false);
const treeScrollRef = ref<HTMLElement | null>(null);
let searchTimer: ReturnType<typeof setTimeout> | null = null;
let treeSortable: Sortable | null = null;

const dragOptions = {
  delayOnTouchOnly: true,
  delay: 400,
  ghostClass: "ind-picker__ghost",
  chosenClass: "ind-picker__chosen",
};

const readyIndicatorCount = computed(
  () => props.indicatorsFlat.filter((i) => i.available && i.data_ready).length,
);

const topTags = computed(() => {
  const counts = new Map<string, number>();
  for (const ind of props.indicatorsFlat) {
    for (const t of ind.tags) {
      counts.set(t, (counts.get(t) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([tag]) => tag);
});

const displayTags = computed(() => (props.embedded ? topTags.value.slice(0, 5) : topTags.value));

const groupChips = computed(() => uniqueGroups(props.indicatorsFlat, activeDomain.value));

const displayGroups = computed(() =>
  props.embedded ? groupChips.value.slice(0, 6) : groupChips.value,
);

const domainTabs = computed(() =>
  props.domains.map((d) => ({
    ...d,
    stats: domainStats(props.indicatorsFlat, d.key),
  })),
);

const filteredTree = computed(() => {
  let base = props.indicatorTree;
  if (activeDomain.value) {
    base = filterTreeByDomain(base, activeDomain.value);
  }
  if (dataReadyOnly.value) {
    base = filterTreeByDataReady(base);
  }
  let allowedIds: Set<string> | null = null;
  if (selectedGroup.value) {
    allowedIds = new Set(
      props.indicatorsFlat.filter((i) => i.group === selectedGroup.value).map((i) => i.id),
    );
  }
  if (selectedTags.value.length) {
    const tagIds = new Set(
      props.indicatorsFlat
        .filter((i) => selectedTags.value.every((t) => i.tags.includes(t)))
        .map((i) => i.id),
    );
    allowedIds = allowedIds
      ? new Set([...allowedIds].filter((id) => tagIds.has(id)))
      : tagIds;
  }
  if (allowedIds) base = filterTreeByIds(base, allowedIds);
  return base;
});

const flatBrowseList = computed(() => {
  if (serverSearchResults.value) return serverSearchResults.value;
  let items = [...props.indicatorsFlat];
  if (activeDomain.value) items = items.filter((i) => i.domain === activeDomain.value);
  if (dataReadyOnly.value) items = items.filter((i) => i.data_ready);
  if (selectedGroup.value) items = items.filter((i) => i.group === selectedGroup.value);
  if (selectedTags.value.length) {
    items = items.filter((i) => selectedTags.value.every((t) => i.tags.includes(t)));
  }
  if (activeDomain.value) items = items.filter((i) => i.available);
  return items;
});

const listDragSource = computed(() => serverSearchResults.value ?? flatBrowseList.value);

const useListMode = computed(() => {
  if (searchQ.value.trim()) return true;
  if (activeDomain.value && countTreeLeaves(filteredTree.value) > 30) return true;
  return false;
});

const listCount = computed(() =>
  searchQ.value.trim() ? (serverSearchResults.value?.length ?? 0) : flatBrowseList.value.length,
);

const showEmpty = computed(
  () =>
    !props.loading &&
    !searchLoading.value &&
    (useListMode.value ? listCount.value === 0 : filteredTree.value.length === 0),
);

function toggleTag(tag: string) {
  const idx = selectedTags.value.indexOf(tag);
  if (idx >= 0) selectedTags.value.splice(idx, 1);
  else selectedTags.value.push(tag);
  if (searchQ.value.trim()) scheduleSearch();
}

function toggleGroup(group: string) {
  selectedGroup.value = selectedGroup.value === group ? null : group;
}

function selectDomain(key: string | null) {
  activeDomain.value = activeDomain.value === key ? null : key;
  selectedGroup.value = null;
}

async function searchIndicatorsServer() {
  const q = searchQ.value.trim();
  if (!q) {
    serverSearchResults.value = null;
    return;
  }
  searchLoading.value = true;
  try {
    const params = new URLSearchParams({
      q,
      data_ready_only: String(dataReadyOnly.value),
    });
    if (selectedTags.value.length) params.set("tags", selectedTags.value.join(","));
    if (activeDomain.value) params.set("domain", activeDomain.value);
    serverSearchResults.value = await apiRequest<BrowserIndicatorRef[]>(
      `/api/v1/query/browser/meta/indicators?${params}`,
    );
  } finally {
    searchLoading.value = false;
  }
}

function scheduleSearch() {
  if (searchTimer) clearTimeout(searchTimer);
  const q = searchQ.value.trim();
  if (!q) {
    serverSearchResults.value = null;
    return;
  }
  searchTimer = setTimeout(() => searchIndicatorsServer(), 300);
}

function onPick(ind: BrowserIndicatorRef) {
  if (!ind.available) return;
  if (props.timeMode === "multi" && ind.freq === "period") {
    // parent may toast; still allow pick
  }
  emit("pick", ind);
}

function onListMove(evt: { draggedContext: { element: BrowserIndicatorRef } }) {
  return canDragIndicator(evt.draggedContext.element, { dataReadyOnly: dataReadyOnly.value });
}

function destroyTreeSortable() {
  if (treeSortable) {
    treeSortable.destroy();
    treeSortable = null;
  }
}

function initTreeSortable() {
  destroyTreeSortable();
  if (useListMode.value || !treeScrollRef.value) return;
  treeSortable = Sortable.create(treeScrollRef.value, {
    ...dragOptions,
    group: BROWSER_INDICATOR_SOURCE_GROUP,
    sort: false,
    draggable: ".ind-tree__row--leaf:not(.ind-tree__row--disabled):not(.ind-tree__row--not-ready)",
    handle: ".ind-tree__drag-handle",
    filter: ".ind-tree__row--disabled,.ind-tree__row--not-ready",
    preventOnFilter: true,
    onClone(evt: Sortable.SortableEvent) {
      const id = evt.item.dataset.indicatorId;
      if (id) evt.clone.dataset.indicatorId = id;
    },
  });
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    searchQ.value = "";
    serverSearchResults.value = null;
  }
}

watch(searchQ, () => scheduleSearch());
watch([dataReadyOnly, selectedTags, activeDomain], () => {
  if (searchQ.value.trim()) scheduleSearch();
});

watch([useListMode, filteredTree, () => props.loading], () => {
  nextTick(() => initTreeSortable());
});

onMounted(() => {
  window.addEventListener("keydown", onKeydown);
  nextTick(() => initTreeSortable());
});

onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
  if (searchTimer) clearTimeout(searchTimer);
  destroyTreeSortable();
});
</script>

<template>
  <div
    class="ind-picker"
    :class="{ panel: !embedded, 'ind-picker--embedded': embedded }"
    aria-label="指标浏览区，可将指标拖入已选篮"
  >
    <div v-if="!embedded" class="panel__header ind-picker__header">
      <span>浏览指标</span>
      <span v-if="listCount && useListMode" class="muted ind-picker__count">共 {{ listCount }} 条</span>
    </div>

    <div :class="embedded ? 'ind-picker__body' : 'panel__body ind-picker__body'">
      <input
        v-model="searchQ"
        class="input ind-picker__search"
        placeholder="搜索指标 / 拼音 / 标签"
        aria-label="搜索指标"
      />

      <p class="ind-picker__hint muted">点击或拖入指标到已选篮</p>

      <div
        v-if="domainTabs.length"
        class="ind-picker__tabs"
        :class="{ 'ind-picker__tabs--scroll': embedded }"
        role="tablist"
        aria-label="指标域"
      >
        <button
          type="button"
          role="tab"
          class="ind-picker__tab"
          :class="{ active: activeDomain === null }"
          :aria-selected="activeDomain === null"
          @click="selectDomain(null)"
        >
          全部
        </button>
        <button
          v-for="d in domainTabs"
          :key="d.key"
          type="button"
          role="tab"
          class="ind-picker__tab"
          :class="{ active: activeDomain === d.key }"
          :aria-selected="activeDomain === d.key"
          @click="selectDomain(d.key)"
        >
          <span>{{ d.label }}</span>
          <span class="ind-picker__tab-count">{{ d.stats.ready }}/{{ d.stats.total }}</span>
        </button>
      </div>

      <div v-if="displayGroups.length" class="ind-picker__chips">
        <button
          v-for="g in displayGroups"
          :key="g"
          type="button"
          class="ind-picker__chip"
          :class="{ active: selectedGroup === g }"
          @click="toggleGroup(g)"
        >
          {{ g }}
        </button>
      </div>

      <div v-if="displayTags.length && !embedded" class="ind-picker__chips">
        <button
          v-for="tag in displayTags"
          :key="tag"
          type="button"
          class="ind-picker__chip ind-picker__chip--tag"
          :class="{ active: selectedTags.includes(tag) }"
          @click="toggleTag(tag)"
        >
          {{ tag }}
        </button>
      </div>

      <label class="ind-picker__checkbox">
        <input v-model="dataReadyOnly" type="checkbox" />
        仅有数据 ({{ readyIndicatorCount }})
      </label>

      <div v-if="loading || searchLoading" class="ind-picker__skeleton">
        <div v-for="i in 6" :key="i" class="ind-picker__skel-row" />
      </div>

      <div v-else-if="showEmpty" class="ind-picker__empty">
        <p>未找到匹配指标</p>
        <button
          v-if="dataReadyOnly"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="dataReadyOnly = false"
        >
          关闭「仅有数据」
        </button>
      </div>

      <draggable
        v-else-if="useListMode"
        :list="listDragSource"
        item-key="id"
        tag="ul"
        class="ind-picker__list"
        :group="BROWSER_INDICATOR_SOURCE_GROUP"
        :sort="false"
        :clone="cloneIndicatorPick"
        :move="onListMove"
        handle=".ind-picker__drag-handle"
        filter=".ind-picker__list-row--disabled"
        :prevent-on-filter="true"
        v-bind="dragOptions"
      >
        <template #item="{ element: ind }">
          <li
            class="ind-picker__list-row"
            :class="{
              'ind-picker__list-row--selected': selectedIds.includes(ind.id),
              'ind-picker__list-row--disabled': !ind.available || (dataReadyOnly && !ind.data_ready),
            }"
            v-bind="indicatorDragDataset(ind)"
            @click="onPick(ind)"
            @dblclick.stop="onPick(ind)"
          >
            <span
              v-if="canDragIndicator(ind, { dataReadyOnly })"
              class="ind-picker__drag-handle"
              aria-label="拖拽手柄，将指标添加到已选篮"
              title="拖入已选篮"
              @click.stop
            >
              ⋮⋮
            </span>
            <span v-if="selectedIds.includes(ind.id)" class="ind-picker__list-check">✓</span>
            <span class="ind-picker__list-label">{{ ind.label }}</span>
            <span class="muted ind-picker__list-meta">{{ ind.data_type_label }}</span>
            <span v-if="ind.unit" class="muted">{{ ind.unit }}</span>
            <span class="badge badge--muted">{{ FREQ_LABELS[ind.freq] ?? ind.freq }}</span>
            <span v-if="!ind.data_ready && !dataReadyOnly" class="badge badge--warn">暂无数据</span>
          </li>
        </template>
      </draggable>

      <div v-else ref="treeScrollRef" class="ind-picker__tree-scroll">
        <BrowserIndicatorTree
          :nodes="filteredTree"
          :show-not-ready="!dataReadyOnly"
          :selected-ids="selectedIds"
          :data-ready-only="dataReadyOnly"
          @pick="onPick"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.ind-picker--embedded {
  height: 100%;
}

.ind-picker__tabs--scroll {
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.ind-picker__tabs--scroll .ind-picker__tab {
  flex-shrink: 0;
}

.ind-picker {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.ind-picker__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.ind-picker__count {
  font-size: var(--font-size-sm);
}

.ind-picker__hint {
  margin: 0;
  font-size: 11px;
}

.ind-picker__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  overflow: hidden;
  flex: 1;
  min-height: 0;
}

.ind-picker__search {
  width: 100%;
}

.ind-picker__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ind-picker__tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: var(--font-size-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
}

.ind-picker__tab.active {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.ind-picker__tab-count {
  font-size: 10px;
  color: var(--color-text-muted);
}

.ind-picker__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ind-picker__chip {
  padding: 2px 8px;
  font-size: 11px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
}

.ind-picker__chip.active {
  background: var(--color-primary-muted);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.ind-picker__checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-sm);
  color: var(--color-text);
  cursor: pointer;
}

.ind-picker__tree-scroll,
.ind-picker__list {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.ind-picker__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ind-picker__list-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  font-size: var(--font-size-md);
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 1px solid transparent;
}

.ind-picker__list-row:hover {
  background: var(--color-row-hover);
}

.ind-picker__list-row--selected {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.ind-picker__list-row--disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ind-picker__drag-handle {
  color: var(--color-text-muted);
  font-size: 10px;
  cursor: grab;
  flex-shrink: 0;
  padding: 0 2px;
  user-select: none;
}

.ind-picker__drag-handle:active {
  cursor: grabbing;
}

.ind-picker__list-label {
  font-weight: 500;
}

.ind-picker__list-meta {
  font-size: var(--font-size-sm);
}

.ind-picker__list-check {
  color: var(--color-primary);
  font-weight: 700;
}

.ind-picker__empty {
  text-align: center;
  padding: var(--space-lg);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.ind-picker__skeleton {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ind-picker__skel-row {
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  animation: ind-picker-pulse 1.2s ease-in-out infinite;
}

:global(.ind-picker__ghost) {
  opacity: 0.55;
  background: var(--color-primary-muted);
  border: 1px dashed var(--color-primary);
}

:global(.ind-picker__chosen) {
  background: var(--color-row-hover);
}

@keyframes ind-picker-pulse {
  0%,
  100% {
    opacity: 0.5;
  }
  50% {
    opacity: 1;
  }
}
</style>
