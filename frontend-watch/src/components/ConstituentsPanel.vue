<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { RankStockRow } from "./RankLanes.vue";

export type ConstituentsMeta = {
  member_count?: number;
  quote_count?: number;
  reason?: string;
};

const props = defineProps<{
  activeConcept: string | null;
  ranksActiveConcept: string | null;
  constituents: RankStockRow[];
  constituentsMeta?: ConstituentsMeta;
  activeSymbol: string;
}>();

const emit = defineEmits<{
  selectSymbol: [payload: { symbol: string; name?: string }];
}>();

const rootRef = ref<HTMLElement | null>(null);

/** 选中概念与 ranks 返回的 active_concept 一致后才展示表，避免串台 */
const conceptAligned = computed(() => {
  if (!props.activeConcept) return true;
  return props.activeConcept === props.ranksActiveConcept;
});

const constituentsEmptyHint = computed(() => {
  const reason = props.constituentsMeta?.reason;
  if (reason === "no_quotes") return "成分已加载但行情暂不可用";
  if (reason === "no_members") return "暂无成分股数据";
  if (reason === "no_concept") return "点击概念查看成分";
  return "暂无成分或行情";
});

const constituentsTitle = computed(() => {
  if (!props.activeConcept) return "成分股";
  // 未对齐时不用旧 meta 的 q/n，避免「新码 + 旧覆盖率」
  if (!conceptAligned.value) {
    return `成分股 · ${props.activeConcept}`;
  }
  const n = props.constituentsMeta?.member_count;
  const q = props.constituentsMeta?.quote_count;
  const suffix =
    typeof n === "number" && n > 0
      ? typeof q === "number"
        ? ` · ${props.activeConcept}（${q}/${n}）`
        : ` · ${props.activeConcept}（${n}）`
      : ` · ${props.activeConcept}`;
  return `成分股${suffix}`;
});

/** 后端按 top_n 切片；meta.member_count 为全量，避免误以为列表不全是 bug */
const truncatedHint = computed(() => {
  if (!conceptAligned.value) return "";
  const n = props.constituentsMeta?.member_count;
  const shown = props.constituents.length;
  if (typeof n !== "number" || n <= 0 || shown <= 0 || n <= shown) return "";
  return `按涨幅展示前 ${shown} / ${n}`;
});

const showNoQuotesBanner = computed(
  () =>
    conceptAligned.value &&
    props.constituents.length > 0 &&
    props.constituentsMeta?.reason === "no_quotes",
);

// 切换/对齐概念时回到顶部；同概念轮询刷新不重置（依赖项不含 constituents）
watch(
  () => [props.activeConcept, props.ranksActiveConcept] as const,
  () => {
    const el = rootRef.value;
    if (el) el.scrollTop = 0;
  },
  { flush: "post" },
);

function fmt(v: number | null | undefined, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

function pctClass(v: number | null | undefined) {
  if (v == null) return "pnl-flat";
  if (v > 0) return "pnl-rise";
  if (v < 0) return "pnl-fall";
  return "pnl-flat";
}
</script>

<template>
  <!-- 根节点同时带 cockpit-pool__block（overflow/flex），勿设 height:100% -->
  <div ref="rootRef" class="constituents-panel">
    <!-- 标题+横幅同一 sticky 层，避免 thead sticky 与横幅叠层 -->
    <div class="constituents-panel__sticky">
      <h3 class="cockpit-pool__subhead">{{ constituentsTitle }}</h3>
      <p
        v-if="showNoQuotesBanner"
        class="constituents-panel__empty muted constituents-panel__banner"
      >
        成分已加载但行情暂不可用
      </p>
      <p
        v-if="truncatedHint"
        class="constituents-panel__empty muted constituents-panel__banner"
      >
        {{ truncatedHint }}
      </p>
    </div>

    <div v-if="!activeConcept" class="constituents-panel__empty muted">点击概念查看成分</div>
    <div v-else-if="!conceptAligned" class="constituents-panel__empty muted">加载中…</div>
    <div v-else-if="!constituents.length" class="constituents-panel__empty muted">
      {{ constituentsEmptyHint }}
    </div>
    <table
      v-else
      class="data-table data-table--selectable constituents-panel__table"
    >
      <thead>
        <tr>
          <th>#</th>
          <th>代码</th>
          <th>名称</th>
          <th class="col-num">涨幅%</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in constituents"
          :key="row.symbol"
          :class="{ 'is-selected': row.symbol === activeSymbol }"
          @click="
            emit('selectSymbol', {
              symbol: row.symbol,
              name: (row.name || '').trim() || row.symbol,
            })
          "
        >
          <td>{{ row.rank ?? "—" }}</td>
          <td class="constituents-panel__code" :title="row.symbol">{{ row.symbol }}</td>
          <td class="constituents-panel__name" :title="(row.name || row.symbol) || undefined">
            {{ (row.name || "").trim() || row.symbol }}
          </td>
          <td class="col-num" :class="pctClass(row.change_pct)">{{ fmt(row.change_pct) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.constituents-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.constituents-panel__sticky {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--color-surface);
  padding-bottom: 2px;
}

.cockpit-pool__subhead {
  margin: 0 0 var(--space-sm);
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text);
}

.constituents-panel__empty {
  margin: 0;
  padding: 8px 0;
  font-size: 0.85rem;
}

.constituents-panel__banner {
  margin-bottom: 6px;
  padding-top: 0;
  padding-bottom: 0;
}

.constituents-panel__table {
  width: 100%;
}

/* 涨幅排序每轮可能重排，关闭 scroll anchoring 避免视口跳动 */
.constituents-panel__table tbody {
  overflow-anchor: none;
}

.constituents-panel__code {
  white-space: nowrap;
}

.constituents-panel__name {
  max-width: 5.5em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
