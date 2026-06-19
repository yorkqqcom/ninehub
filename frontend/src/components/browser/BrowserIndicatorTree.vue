<script setup lang="ts">
import { computed, ref } from "vue";
import type { BrowserIndicatorRef, BrowserIndicatorTreeNode } from "@/api/types";
import { canDragIndicator, indicatorDragDataset } from "./browserDragUtils";
import { FREQ_LABELS } from "./indicatorUtils";

defineOptions({ name: "BrowserIndicatorTree" });

const props = defineProps<{
  nodes: BrowserIndicatorTreeNode[];
  depth?: number;
  showNotReady?: boolean;
  selectedIds?: string[];
  dataReadyOnly?: boolean;
}>();

const emit = defineEmits<{
  pick: [ind: BrowserIndicatorRef];
}>();

const depth = props.depth ?? 0;
const collapsed = ref<Record<string, boolean>>({});

function toggle(id: string) {
  collapsed.value[id] = !collapsed.value[id];
}

function isCollapsed(id: string) {
  return collapsed.value[id] === true;
}

function isSelected(id: string) {
  return props.selectedIds?.includes(id) ?? false;
}

function onPick(node: BrowserIndicatorTreeNode) {
  if (node.indicator) emit("pick", node.indicator);
}

function rowClass(node: BrowserIndicatorTreeNode) {
  const ind = node.indicator;
  const notReadyBlocked = !!(ind && props.dataReadyOnly && !ind.data_ready);
  return {
    "ind-tree__row--branch": node.node_type !== "indicator",
    "ind-tree__row--leaf": node.node_type === "indicator",
    "ind-tree__row--disabled": ind && !ind.available,
    "ind-tree__row--not-ready": ind && ind.available && !ind.data_ready && props.showNotReady,
    "ind-tree__row--not-ready-blocked": notReadyBlocked,
    "ind-tree__row--selected": ind && isSelected(ind.id),
  };
}

function tooltip(node: BrowserIndicatorTreeNode) {
  const ind = node.indicator;
  if (ind && !ind.available) return "未激活";
  if (ind && ind.available && !ind.data_ready) return "暂无数据";
  return undefined;
}

function isDraggable(ind: BrowserIndicatorRef | undefined) {
  if (!ind) return false;
  return canDragIndicator(ind, { dataReadyOnly: props.dataReadyOnly ?? true });
}
</script>

<template>
  <ul class="ind-tree" :class="`ind-tree--d${depth}`">
    <li v-for="node in nodes" :key="node.id" class="ind-tree__node">
      <div
        class="ind-tree__row"
        :class="rowClass(node)"
        :title="tooltip(node)"
        v-bind="node.indicator ? indicatorDragDataset(node.indicator) : {}"
        @click="node.children?.length ? toggle(node.id) : onPick(node)"
        @dblclick.stop="node.indicator ? onPick(node) : undefined"
      >
        <span
          v-if="node.indicator && isDraggable(node.indicator)"
          class="ind-tree__drag-handle"
          aria-label="拖拽手柄，将指标添加到已选篮"
          title="拖入已选篮"
          @click.stop
        >
          ⋮⋮
        </span>
        <span v-if="node.children?.length" class="ind-tree__caret">
          {{ isCollapsed(node.id) ? "▸" : "▾" }}
        </span>
        <span v-if="node.indicator && isSelected(node.indicator.id)" class="ind-tree__check">✓</span>
        <span class="ind-tree__label">{{ node.label }}</span>
        <template v-if="node.indicator">
          <span v-if="node.indicator.unit" class="ind-tree__unit muted">{{ node.indicator.unit }}</span>
          <span class="badge badge--muted ind-tree__freq">{{ FREQ_LABELS[node.indicator.freq] ?? node.indicator.freq }}</span>
          <span
            v-if="!node.indicator.data_ready && showNotReady"
            class="badge badge--warn ind-tree__warn"
          >
            暂无数据
          </span>
        </template>
        <button
          v-if="node.indicator?.available"
          type="button"
          class="btn btn--ghost btn--sm"
          :aria-label="isSelected(node.indicator.id) ? `移除 ${node.label}` : `添加 ${node.label}`"
          @click.stop="onPick(node)"
        >
          {{ isSelected(node.indicator!.id) ? "−" : "+" }}
        </button>
      </div>

      <BrowserIndicatorTree
        v-if="node.children?.length && !isCollapsed(node.id)"
        :nodes="node.children"
        :depth="depth + 1"
        :show-not-ready="showNotReady"
        :selected-ids="selectedIds"
        :data-ready-only="dataReadyOnly"
        @pick="emit('pick', $event)"
      />
    </li>
  </ul>
</template>

<style scoped>
.ind-tree {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ind-tree--d1 {
  padding-left: 8px;
}

.ind-tree--d2 {
  padding-left: 16px;
}

.ind-tree--d3 {
  padding-left: 24px;
}

.ind-tree__row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  font-size: var(--font-size-md);
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 1px solid transparent;
}

.ind-tree__row--branch {
  font-weight: 600;
  color: var(--color-text);
}

.ind-tree__row--leaf {
  color: var(--color-text);
}

.ind-tree__row--leaf:hover {
  background: var(--color-row-hover);
}

.ind-tree__row--selected {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.ind-tree__row--disabled {
  opacity: 0.6;
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.ind-tree__row--not-ready,
.ind-tree__row--not-ready-blocked {
  opacity: 0.65;
  color: var(--color-text-muted);
  font-style: italic;
}

.ind-tree__drag-handle {
  color: var(--color-text-muted);
  font-size: 10px;
  cursor: grab;
  flex-shrink: 0;
  user-select: none;
}

.ind-tree__drag-handle:active {
  cursor: grabbing;
}

.ind-tree__caret {
  width: 12px;
  flex-shrink: 0;
}

.ind-tree__check {
  color: var(--color-primary);
  font-weight: 700;
  font-size: var(--font-size-sm);
}

.ind-tree__unit {
  font-size: var(--font-size-sm);
}

.ind-tree__freq {
  font-size: 10px;
  padding: 0 4px;
}

.ind-tree__warn {
  font-size: 10px;
}
</style>
