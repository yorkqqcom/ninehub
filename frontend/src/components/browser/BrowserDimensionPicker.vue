<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { pinyin } from "pinyin-pro";
import type { BrowserDimensionRef } from "@/api/types";

defineOptions({ name: "BrowserDimensionPicker" });

const HEAVY_CATEGORIES = ["industry", "sw", "index"] as const;
type HeavyCategory = (typeof HEAVY_CATEGORIES)[number];

const props = defineProps<{
  dimensions: BrowserDimensionRef[];
  categories: Record<string, string>;
  modelValue: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [id: string];
}>();

const activeHeavy = ref<HeavyCategory | null>(null);
const searchByCat = ref<Record<HeavyCategory, string>>({ industry: "", sw: "", index: "" });
const availableOnly = ref<Record<HeavyCategory, boolean>>({
  industry: false,
  sw: true,
  index: true,
});
const letterFilter = ref<string | null>(null);
const showLimit = ref<Record<HeavyCategory, number>>({ industry: 50, sw: 50, index: 24 });

const SMALL_CATEGORIES = ["market", "special"] as const;

const itemsByCategory = computed(() => {
  const map: Record<string, BrowserDimensionRef[]> = {};
  for (const d of props.dimensions) {
    if (d.id === "sw:placeholder") continue;
    if (!map[d.category]) map[d.category] = [];
    map[d.category].push(d);
  }
  for (const cat of HEAVY_CATEGORIES) {
    if (map[cat]) {
      map[cat].sort((a, b) => (b.stock_count ?? 0) - (a.stock_count ?? 0));
    }
  }
  return map;
});

const heavySummaries = computed(() =>
  HEAVY_CATEGORIES.map((key) => ({
    key,
    label: props.categories[key] ?? key,
    total: itemsByCategory.value[key]?.length ?? 0,
    available: itemsByCategory.value[key]?.filter((d) => d.available).length ?? 0,
  })).filter((s) => s.total > 0),
);

function firstLetter(label: string): string {
  const py = pinyin(label.replace(/^申万一级·/, ""), {
    pattern: "first",
    toneType: "none",
  }).replace(/\s/g, "");
  const ch = py.charAt(0).toUpperCase();
  return ch >= "A" && ch <= "Z" ? ch : "#";
}

function baseFilterHeavy(cat: HeavyCategory): BrowserDimensionRef[] {
  let items = [...(itemsByCategory.value[cat] ?? [])];
  const q = searchByCat.value[cat].trim().toLowerCase();
  if (availableOnly.value[cat]) {
    items = items.filter((d) => d.available);
  }
  if (q) {
    items = items.filter((d) => {
      const py = pinyin(d.label, { pattern: "first", toneType: "none" }).replace(/\s/g, "");
      return (
        d.label.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q) ||
        py.toLowerCase().includes(q) ||
        (d.description?.toLowerCase().includes(q) ?? false)
      );
    });
  }
  return items;
}

function filterHeavyItems(cat: HeavyCategory): BrowserDimensionRef[] {
  let items = baseFilterHeavy(cat);
  if (letterFilter.value && cat !== "index") {
    items = items.filter((d) => firstLetter(d.label) === letterFilter.value);
  }
  return items;
}

const visibleHeavyItems = computed(() => {
  if (!activeHeavy.value) return [];
  const cat = activeHeavy.value;
  return filterHeavyItems(cat).slice(0, showLimit.value[cat]);
});

const filteredHeavyTotal = computed(() => {
  if (!activeHeavy.value) return 0;
  return filterHeavyItems(activeHeavy.value).length;
});

const letterIndex = computed(() => {
  if (!activeHeavy.value || activeHeavy.value === "index") return [];
  const letters = new Set<string>();
  for (const d of baseFilterHeavy(activeHeavy.value)) {
    letters.add(firstLetter(d.label));
  }
  return [...letters].sort();
});

const indexHotChips = computed(() => {
  const items = itemsByCategory.value.index ?? [];
  return items.filter((d) => d.available).slice(0, 6);
});

function select(id: string, available: boolean) {
  if (!available) return;
  emit("update:modelValue", id);
}

function openHeavy(cat: HeavyCategory) {
  activeHeavy.value = activeHeavy.value === cat ? null : cat;
  letterFilter.value = null;
}

function loadMore() {
  if (!activeHeavy.value) return;
  showLimit.value[activeHeavy.value] += 50;
}

function stockCount(d: BrowserDimensionRef): number | null {
  if (d.stock_count != null) return d.stock_count;
  const m = d.description?.match(/(\d+)\s*只/);
  return m ? Number(m[1]) : null;
}

watch(
  () => props.modelValue,
  (id) => {
    const d = props.dimensions.find((x) => x.id === id);
    if (d && HEAVY_CATEGORIES.includes(d.category as HeavyCategory)) {
      activeHeavy.value = d.category as HeavyCategory;
    }
  },
  { immediate: true },
);

watch(activeHeavy, () => {
  letterFilter.value = null;
  showLimit.value = { industry: 50, sw: 50, index: 24 };
});
</script>

<template>
  <div class="dim-picker">
    <!-- 市场 / 特色：短列表直接展示 -->
    <div v-for="cat in SMALL_CATEGORIES" :key="cat" class="dim-picker__group">
      <div v-if="itemsByCategory[cat]?.length" class="dim-picker__heading">
        {{ categories[cat] ?? cat }}
      </div>
      <ul class="dim-picker__list">
        <li
          v-for="d in itemsByCategory[cat]"
          :key="d.id"
          class="dim-picker__item"
          :class="{ active: modelValue === d.id, disabled: !d.available }"
          @click="select(d.id, d.available)"
        >
          <span class="dim-picker__label">{{ d.label }}</span>
        </li>
      </ul>
    </div>

    <!-- 迭代2：三大类 Tab 入口 -->
    <div v-if="heavySummaries.length" class="dim-picker__heavy-tabs">
      <button
        v-for="s in heavySummaries"
        :key="s.key"
        type="button"
        class="dim-picker__tab"
        :class="{ active: activeHeavy === s.key }"
        @click="openHeavy(s.key)"
      >
        <span class="dim-picker__tab-label">{{ s.label }}</span>
        <span class="dim-picker__tab-count">{{ s.available }}/{{ s.total }}</span>
      </button>
    </div>

    <!-- 迭代1+3：展开面板 — 搜索 / 筛选 / 字母索引 / 网格 -->
    <div v-if="activeHeavy" class="dim-picker__panel">
      <div class="dim-picker__toolbar">
        <input
          v-model="searchByCat[activeHeavy]"
          class="input dim-picker__search"
          :placeholder="`搜索${categories[activeHeavy] ?? ''}…`"
        />
        <label class="dim-picker__check">
          <input v-model="availableOnly[activeHeavy]" type="checkbox" />
          仅可用
        </label>
      </div>

      <!-- 指数：热门快捷 chip -->
      <div v-if="activeHeavy === 'index' && indexHotChips.length" class="dim-picker__chips">
        <button
          v-for="d in indexHotChips"
          :key="d.id"
          type="button"
          class="dim-picker__chip"
          :class="{ active: modelValue === d.id }"
          @click="select(d.id, d.available)"
        >
          {{ d.label }}
        </button>
      </div>

      <div class="dim-picker__body">
        <!-- 迭代3：行业/申万 字母索引 -->
        <div v-if="activeHeavy !== 'index' && letterIndex.length > 1" class="dim-picker__letters">
          <button
            type="button"
            class="dim-picker__letter"
            :class="{ active: letterFilter === null }"
            @click="letterFilter = null"
          >
            全
          </button>
          <button
            v-for="L in letterIndex"
            :key="L"
            type="button"
            class="dim-picker__letter"
            :class="{ active: letterFilter === L }"
            @click="letterFilter = L"
          >
            {{ L }}
          </button>
        </div>

        <!-- 指数：卡片网格；行业/申万：滚动列表 -->
        <div
          class="dim-picker__scroll"
          :class="{ 'dim-picker__scroll--grid': activeHeavy === 'index' }"
        >
          <template v-if="activeHeavy === 'index'">
            <button
              v-for="d in visibleHeavyItems"
              :key="d.id"
              type="button"
              class="dim-picker__card"
              :class="{ active: modelValue === d.id, disabled: !d.available }"
              @click="select(d.id, d.available)"
            >
              <span class="dim-picker__card-title">{{ d.label }}</span>
              <span v-if="stockCount(d) != null" class="dim-picker__card-count">
                {{ stockCount(d)?.toLocaleString() }} 只
              </span>
              <span v-if="d.degraded" class="badge badge--warn">未就绪</span>
            </button>
          </template>
          <ul v-else class="dim-picker__list dim-picker__list--dense">
            <li
              v-for="d in visibleHeavyItems"
              :key="d.id"
              class="dim-picker__item"
              :class="{ active: modelValue === d.id, disabled: !d.available }"
              @click="select(d.id, d.available)"
            >
              <span class="dim-picker__label">{{ d.label }}</span>
              <span v-if="stockCount(d) != null" class="dim-picker__count">
                {{ stockCount(d)?.toLocaleString() }}
              </span>
              <span v-if="d.degraded" class="badge badge--warn">未就绪</span>
            </li>
          </ul>
          <p v-if="!visibleHeavyItems.length" class="dim-picker__empty muted">无匹配项</p>
        </div>
      </div>

      <div v-if="filteredHeavyTotal > visibleHeavyItems.length" class="dim-picker__more">
        <button type="button" class="btn btn--ghost btn--sm btn--block" @click="loadMore">
          加载更多（{{ visibleHeavyItems.length }}/{{ filteredHeavyTotal }}）
        </button>
      </div>
    </div>

    <slot name="watchlists" />
  </div>
</template>

<style scoped>
.dim-picker__group {
  margin-bottom: var(--space-sm);
}

.dim-picker__heading {
  font-size: var(--font-size-sm);
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--color-text-secondary);
  margin: var(--space-sm) 0 4px;
  text-transform: uppercase;
}

.dim-picker__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.dim-picker__list--dense .dim-picker__item {
  padding: 4px 6px;
  font-size: var(--font-size-sm);
}

.dim-picker__item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--font-size-md);
  color: var(--color-text);
}

.dim-picker__item:hover,
.dim-picker__item.active {
  background: var(--color-surface-elevated);
}

.dim-picker__item.disabled {
  opacity: 0.6;
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.dim-picker__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dim-picker__count {
  font-size: 11px;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.dim-picker__heavy-tabs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: var(--space-sm) 0;
}

.dim-picker__tab {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  cursor: pointer;
  text-align: left;
  font-size: var(--font-size-sm);
  color: var(--color-text);
}

.dim-picker__tab:hover {
  border-color: var(--color-border-strong);
}

.dim-picker__tab.active {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-weight: 600;
}

.dim-picker__tab-label {
  font-weight: 500;
}

.dim-picker__tab-count {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.dim-picker__panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-sm);
  margin-bottom: var(--space-sm);
  background: var(--color-surface-muted);
}

.dim-picker__toolbar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: var(--space-xs);
}

.dim-picker__search {
  font-size: var(--font-size-sm);
}

.dim-picker__check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--color-text-secondary);
}

.dim-picker__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: var(--space-xs);
}

.dim-picker__chip {
  padding: 3px 8px;
  font-size: 11px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
}

.dim-picker__chip.active {
  background: var(--color-primary-muted);
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 600;
}

.dim-picker__body {
  display: flex;
  gap: 4px;
  min-height: 0;
}

.dim-picker__letters {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex-shrink: 0;
  max-height: 220px;
  overflow-y: auto;
}

.dim-picker__letter {
  width: 22px;
  height: 20px;
  padding: 0;
  font-size: 10px;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.dim-picker__letter:hover,
.dim-picker__letter.active {
  background: var(--color-primary-muted);
  color: var(--color-text);
  font-weight: 600;
}

.dim-picker__scroll {
  flex: 1;
  max-height: 220px;
  overflow-y: auto;
  min-width: 0;
}

.dim-picker__scroll--grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  align-content: start;
}

.dim-picker__card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  cursor: pointer;
  text-align: left;
  font-size: 11px;
  color: var(--color-text);
}

.dim-picker__card:hover,
.dim-picker__card.active {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.dim-picker__card.disabled {
  opacity: 0.6;
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.dim-picker__card-title {
  font-weight: 500;
  line-height: 1.3;
}

.dim-picker__card-count {
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.dim-picker__empty {
  font-size: 12px;
  padding: var(--space-sm);
  text-align: center;
}

.dim-picker__more {
  margin-top: var(--space-xs);
}

.btn--block {
  width: 100%;
}
</style>
