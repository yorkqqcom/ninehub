<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import Sortable from "sortablejs";
import draggable from "vuedraggable";
import type {
  BrowserIndicatorRef,
  BrowserTemplateItem,
  BrowserTemplateResponse,
} from "@/api/types";
import {
  BROWSER_INDICATOR_REMOVE_GROUP,
  BROWSER_INDICATOR_TARGET_GROUP,
  type DragRejectReason,
  parseIndicatorIdFromElement,
} from "./browserDragUtils";
import { INDICATOR_LIMIT } from "./indicatorUtils";

export type IndicatorPick = { id: string; adjust?: string };

defineOptions({ name: "BrowserIndicatorBasket" });

const props = defineProps<{
  modelValue: IndicatorPick[];
  indicatorsFlat: BrowserIndicatorRef[];
  systemTemplates: BrowserTemplateItem[];
  userTemplates: BrowserTemplateResponse[];
  timeMode?: "single" | "multi";
  embedded?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: IndicatorPick[]];
  "load-system": [tpl: BrowserTemplateItem, mode: "replace" | "append"];
  "load-user": [tpl: BrowserTemplateResponse, mode: "replace" | "append"];
  "delete-user": [id: number];
  "next-step": [];
  "drag-rejected": [reason: DragRejectReason];
}>();

const flash = ref(false);
const dragOver = ref(false);
const removeSlotRef = ref<HTMLElement | null>(null);
let flashTimer: ReturnType<typeof setTimeout> | null = null;
let removeSortable: Sortable | null = null;

const dragOptions = {
  delayOnTouchOnly: true,
  delay: 400,
  ghostClass: "ind-basket__ghost",
  chosenClass: "ind-basket__chosen",
};

const count = computed(() => props.modelValue.length);
const atLimit = computed(() => count.value >= INDICATOR_LIMIT);
const progressPct = computed(() => Math.min(100, (count.value / INDICATOR_LIMIT) * 100));
const progressClass = computed(() => {
  if (count.value >= INDICATOR_LIMIT) return "ind-basket__bar-fill--full";
  if (count.value > 30) return "ind-basket__bar-fill--warn";
  return "";
});

const hasPeriodConflict = computed(
  () =>
    props.timeMode === "multi" &&
    props.modelValue.some((s) => indicatorMeta(s.id)?.freq === "period"),
);

function indicatorMeta(id: string) {
  return props.indicatorsFlat.find((i) => i.id === id);
}

function indicatorLabel(id: string) {
  return indicatorMeta(id)?.label ?? id;
}

function removeIndicator(id: string) {
  emit(
    "update:modelValue",
    props.modelValue.filter((s) => s.id !== id),
  );
}

function clearAll() {
  emit("update:modelValue", []);
}

function removeNotReady() {
  emit(
    "update:modelValue",
    props.modelValue.filter((s) => indicatorMeta(s.id)?.data_ready),
  );
}

function onListDblClick(id: string) {
  removeIndicator(id);
}

function buildPick(id: string): IndicatorPick | null {
  const meta = indicatorMeta(id);
  if (!meta?.available) return null;
  return {
    id,
    adjust: meta.supports_adjust ? "none" : undefined,
  };
}

function onDragAdd(evt: { newIndex: number; item: HTMLElement }) {
  const id =
    parseIndicatorIdFromElement(evt.item) ?? props.modelValue[evt.newIndex]?.id ?? null;
  const next = [...props.modelValue];
  next.splice(evt.newIndex, 1);

  if (!id) {
    emit("update:modelValue", next);
    return;
  }

  if (next.some((s) => s.id === id)) {
    emit("update:modelValue", next);
    emit("drag-rejected", "duplicate");
    return;
  }

  if (next.length >= INDICATOR_LIMIT) {
    emit("update:modelValue", next);
    emit("drag-rejected", "limit");
    return;
  }

  const meta = indicatorMeta(id);
  if (!meta?.available) {
    emit("update:modelValue", next);
    emit("drag-rejected", "unavailable");
    return;
  }

  const pick = buildPick(id);
  if (!pick) {
    emit("update:modelValue", next);
    emit("drag-rejected", "unavailable");
    return;
  }

  next.splice(evt.newIndex, 0, pick);
  emit("update:modelValue", next);
}

function onBasketMove(evt: { from: HTMLElement; to: HTMLElement; dragged: HTMLElement }) {
  const external = evt.from !== evt.to;
  dragOver.value = external;
  if (external && atLimit.value) return false;
  return true;
}

function onBasketDragStart() {
  dragOver.value = false;
}

function onBasketDragEnd() {
  dragOver.value = false;
}

function initRemoveSortable() {
  if (!removeSlotRef.value) return;
  if (removeSortable) removeSortable.destroy();
  removeSortable = Sortable.create(removeSlotRef.value, {
    ...dragOptions,
    group: BROWSER_INDICATOR_REMOVE_GROUP,
    sort: false,
    onAdd(evt: Sortable.SortableEvent) {
      evt.item.remove();
    },
  });
}

watch(
  () => props.modelValue.length,
  (n, prev) => {
    if (n > prev) {
      flash.value = true;
      if (flashTimer) clearTimeout(flashTimer);
      flashTimer = setTimeout(() => {
        flash.value = false;
      }, 200);
    }
  },
);

function templateIndicatorCount(tpl: { payload: Record<string, unknown> }): number {
  const inds = tpl.payload.indicators;
  return Array.isArray(inds) ? inds.length : 0;
}

onMounted(() => nextTick(() => initRemoveSortable()));
onUnmounted(() => {
  if (flashTimer) clearTimeout(flashTimer);
  if (removeSortable) removeSortable.destroy();
});
</script>

<template>
  <div class="ind-basket" :class="{ panel: !embedded, 'ind-basket--embedded': embedded, 'ind-basket--flash': flash }">
    <div v-if="!embedded" class="panel__header ind-basket__header">
      <span>已选指标 ({{ count }}/{{ INDICATOR_LIMIT }})</span>
      <div class="ind-basket__header-actions">
        <button
          v-if="count"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="clearAll"
        >
          清空
        </button>
        <button
          v-if="count"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="removeNotReady"
        >
          移除未就绪
        </button>
      </div>
    </div>

    <div v-if="embedded && count" class="ind-basket__embedded-actions">
      <button type="button" class="btn btn--ghost btn--sm" @click="clearAll">清空</button>
      <button type="button" class="btn btn--ghost btn--sm" @click="removeNotReady">移除未就绪</button>
    </div>

    <div :class="embedded ? 'ind-basket__body' : 'panel__body ind-basket__body'">
      <div v-if="atLimit" class="ind-basket__limit-warn">
        已达上限 {{ INDICATOR_LIMIT }} 项，请移除后再添加
      </div>

      <div v-if="hasPeriodConflict" class="badge badge--warn ind-basket__conflict">
        多截面不支持期频指标
      </div>

      <div class="ind-basket__progress" aria-hidden="true">
        <div
          class="ind-basket__bar-fill"
          :class="progressClass"
          :style="{ width: `${progressPct}%` }"
        />
      </div>

      <div
        class="ind-basket__drop-zone"
        :class="{
          'ind-basket__drop-zone--active': dragOver && !atLimit,
          'ind-basket__drop-zone--reject': dragOver && atLimit,
        }"
        aria-dropeffect="copy"
        aria-label="已选指标篮，可拖入指标或拖拽排序"
      >
        <draggable
          :model-value="modelValue"
          item-key="id"
          class="ind-basket__list"
          :class="{ 'ind-basket__list--empty': !count }"
          :group="BROWSER_INDICATOR_TARGET_GROUP"
          v-bind="dragOptions"
          @update:model-value="emit('update:modelValue', $event)"
          @add="onDragAdd"
          @start="onBasketDragStart"
          @end="onBasketDragEnd"
          @move="onBasketMove"
        >
          <template #item="{ element }">
            <div
              class="ind-basket__item"
              :data-indicator-id="element.id"
              @dblclick="onListDblClick(element.id)"
            >
              <span
                class="ind-basket__drag"
                aria-label="拖拽排序或拖出移除"
                title="拖拽排序"
              >
                ⋮⋮
              </span>
              <span class="ind-basket__label">{{ indicatorLabel(element.id) }}</span>
              <select
                v-if="indicatorMeta(element.id)?.supports_adjust"
                v-model="element.adjust"
                class="ind-basket__adj input"
                @click.stop
              >
                <option value="none">不复权</option>
                <option value="qfq">前复权</option>
                <option value="hfq">后复权</option>
              </select>
              <button
                type="button"
                class="ind-basket__remove"
                :aria-label="`移除 ${indicatorLabel(element.id)}`"
                @click="removeIndicator(element.id)"
              >
                ×
              </button>
            </div>
          </template>
        </draggable>

        <p v-if="!count" class="ind-basket__empty muted">拖入指标或从左侧点击添加</p>
      </div>

      <div
        v-if="count"
        ref="removeSlotRef"
        class="ind-basket__remove-slot"
        aria-label="拖出指标到此处移除"
      >
        拖出到此处移除
      </div>

      <details class="ind-basket__templates">
        <summary>从模板加载</summary>
        <div class="ind-basket__tpl-block">
          <div class="ind-basket__tpl-title">系统模板</div>
          <div
            v-for="tpl in systemTemplates"
            :key="tpl.id"
            class="ind-basket__tpl-row"
          >
            <span>
              {{ tpl.name }}
              <span class="muted">({{ templateIndicatorCount(tpl) }} 项)</span>
            </span>
            <span class="ind-basket__tpl-actions">
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                @click="emit('load-system', tpl, 'replace')"
              >
                加载
              </button>
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                @click="emit('load-system', tpl, 'append')"
              >
                追加
              </button>
            </span>
          </div>
        </div>
        <div v-if="userTemplates.length" class="ind-basket__tpl-block">
          <div class="ind-basket__tpl-title">我的模板</div>
          <div v-for="tpl in userTemplates" :key="tpl.id" class="ind-basket__tpl-row">
            <span>
              {{ tpl.name }}
              <span class="muted">({{ templateIndicatorCount(tpl) }} 项)</span>
            </span>
            <span class="ind-basket__tpl-actions">
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                @click="emit('load-user', tpl, 'replace')"
              >
                加载
              </button>
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                @click="emit('load-user', tpl, 'append')"
              >
                追加
              </button>
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                @click="emit('delete-user', tpl.id)"
              >
                删
              </button>
            </span>
          </div>
        </div>
      </details>

      <button
        v-if="!embedded"
        type="button"
        class="btn btn--secondary btn--block"
        @click="emit('next-step')"
      >
        下一步：选时间
      </button>
    </div>
  </div>
</template>

<style scoped>
.ind-basket--embedded {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.ind-basket__embedded-actions {
  display: flex;
  gap: 4px;
  padding: 0 var(--space-sm) var(--space-xs);
  flex-shrink: 0;
}

.ind-basket {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  transition: background 0.2s ease;
}

.ind-basket--flash {
  background: var(--color-primary-muted);
}

.ind-basket__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-sm);
}

.ind-basket__header-actions {
  display: flex;
  gap: 2px;
}

.ind-basket__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  overflow: hidden;
  flex: 1;
  min-height: 0;
  padding: var(--space-sm);
}

.ind-basket__limit-warn {
  font-size: var(--font-size-sm);
  color: var(--color-err-text);
  background: var(--color-err-bg);
  padding: 4px 8px;
  border-radius: var(--radius-sm);
}

.ind-basket__conflict {
  align-self: flex-start;
}

.ind-basket__progress {
  height: 4px;
  background: var(--color-surface-muted);
  border-radius: 2px;
  overflow: hidden;
}

.ind-basket__bar-fill {
  height: 100%;
  background: var(--color-primary);
  transition: width 0.2s ease;
}

.ind-basket__bar-fill--warn {
  background: var(--color-warn-text);
}

.ind-basket__bar-fill--full {
  background: var(--color-err-text);
}

.ind-basket__drop-zone {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 80px;
  border: 1px dashed transparent;
  border-radius: var(--radius-sm);
  transition: border-color 0.15s ease, background 0.15s ease;
}

.ind-basket__drop-zone--active {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.ind-basket__drop-zone--reject {
  border-color: var(--color-err-text);
  background: var(--color-err-bg);
  cursor: not-allowed;
}

.ind-basket__list {
  flex: 1;
  overflow: auto;
  min-height: 48px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ind-basket__list--empty {
  min-height: 64px;
}

.ind-basket__item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: grab;
  font-size: var(--font-size-md);
}

.ind-basket__drag {
  color: var(--color-text-muted);
  font-size: 10px;
  cursor: grab;
}

.ind-basket__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ind-basket__adj {
  font-size: var(--font-size-sm);
  padding: 2px 4px;
  max-width: 88px;
}

.ind-basket__remove {
  border: none;
  background: none;
  cursor: pointer;
  padding: 0 4px;
  color: var(--color-text-muted);
  font-size: 16px;
  line-height: 1;
}

.ind-basket__remove:hover {
  color: var(--color-err-text);
}

.ind-basket__empty {
  text-align: center;
  padding: var(--space-md);
  font-size: var(--font-size-sm);
  margin: auto 0;
}

.ind-basket__remove-slot {
  flex-shrink: 0;
  min-height: 28px;
  padding: 6px 8px;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 11px;
  color: var(--color-text-muted);
  text-align: center;
  background: var(--color-surface-muted);
}

.ind-basket__templates {
  font-size: var(--font-size-sm);
  border-top: 1px solid var(--color-border);
  padding-top: var(--space-sm);
}

.ind-basket__templates summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.ind-basket__tpl-block {
  margin-top: var(--space-xs);
}

.ind-basket__tpl-title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 4px;
}

.ind-basket__tpl-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-sm);
  padding: 4px 0;
  font-size: var(--font-size-md);
}

.ind-basket__tpl-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.btn--block {
  width: 100%;
  margin-top: auto;
}

:global(.ind-basket__ghost) {
  opacity: 0.55;
  background: var(--color-primary-muted);
  border: 1px dashed var(--color-primary);
}

:global(.ind-basket__chosen) {
  background: var(--color-row-hover);
}
</style>
