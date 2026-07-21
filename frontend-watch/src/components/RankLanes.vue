<script setup lang="ts">
import { computed } from "vue";

export type RankConceptRow = {
  code: string;
  name?: string;
  change_pct?: number | null;
  speed_pct?: number | null;
  last?: number | null;
  rank?: number;
};

export type RankStockRow = {
  symbol: string;
  name?: string;
  change_pct?: number | null;
  speed_pct?: number | null;
  last?: number | null;
  rank?: number;
};

export type RanksMeta = {
  catalog_ok?: boolean;
  speed_warm?: boolean;
  speed_warm_progress?: number;
  pool_count?: number;
  stale_speed?: boolean;
};

const props = defineProps<{
  conceptsChange: RankConceptRow[];
  conceptsSpeed: RankConceptRow[];
  stocksChange: RankStockRow[];
  stocksSpeed: RankStockRow[];
  activeConcept: string | null;
  meta: RanksMeta;
  degraded?: boolean;
  message?: string;
  loading?: boolean;
  activeSymbol: string;
  /** 自选股池行情，补全 ranks 缺 name/最新价/涨幅 */
  symbolQuotes?: Record<
    string,
    { name?: string; last?: number | null; change_pct?: number | null }
  >;
}>();

const emit = defineEmits<{
  selectConcept: [payload: { code: string; name?: string }];
  selectSymbol: [payload: { symbol: string; name?: string }];
  clearConcept: [];
}>();

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

function poolQuote(symbol: string) {
  return props.symbolQuotes?.[symbol];
}

function conceptName(row: RankConceptRow) {
  return (row.name || "").trim() || row.code;
}

function displayStockName(row: RankStockRow) {
  const fromRow = (row.name || "").trim();
  if (fromRow) return fromRow;
  const fromPool = (poolQuote(row.symbol)?.name || "").trim();
  // pytdx 行情无名称时至少显示代码，避免整列「—」
  return fromPool || row.symbol;
}

function stockLast(row: RankStockRow) {
  if (row.last != null && !Number.isNaN(Number(row.last))) return row.last;
  const p = poolQuote(row.symbol)?.last;
  return p != null && !Number.isNaN(Number(p)) ? Number(p) : null;
}

function stockChangePct(row: RankStockRow) {
  if (row.change_pct != null && !Number.isNaN(Number(row.change_pct))) return Number(row.change_pct);
  const p = poolQuote(row.symbol)?.change_pct;
  return p != null && !Number.isNaN(Number(p)) ? Number(p) : null;
}

function stockSelectPayload(row: RankStockRow) {
  const name = displayStockName(row);
  return {
    symbol: row.symbol,
    name: name && name !== row.symbol ? name : undefined,
  };
}

function conceptSelectPayload(row: RankConceptRow) {
  const name = conceptName(row);
  return {
    code: row.code,
    name: name && name !== row.code ? name : undefined,
  };
}

function nameTitle(name: string) {
  return name || undefined;
}

const catalogOk = computed(() => props.meta.catalog_ok !== false);
const speedWarm = computed(() => Boolean(props.meta.speed_warm));
const staleSpeed = computed(() => Boolean(props.meta.stale_speed));
const progressPct = computed(() => {
  const p = Number(props.meta.speed_warm_progress ?? 0);
  if (!Number.isFinite(p)) return 0;
  return Math.round(Math.min(1, Math.max(0, p)) * 100);
});
const poolCount = computed(() => Number(props.meta.pool_count ?? 0));

const conceptSpeedHint = computed(() => {
  if (!catalogOk.value && !props.conceptsSpeed.length) return "概念目录不可用";
  if (!speedWarm.value && !props.conceptsSpeed.length) {
    return `涨速数据预热中… ${progressPct.value}%`;
  }
  if (staleSpeed.value) return "刷新中";
  if (!props.conceptsSpeed.length) return "暂无概念涨速";
  return "";
});

const poolEmptyHint = computed(() => {
  if (poolCount.value <= 0) return "请添加并启用盯盘标的";
  return "";
});
</script>

<template>
  <div class="rank-lanes">
    <p v-if="degraded && message" class="warn-text rank-lanes__banner">{{ message }}</p>

    <section class="rank-lane">
      <header class="rank-lane__head">
        <h3>概念涨幅</h3>
        <button
          v-if="activeConcept"
          type="button"
          class="btn btn--ghost btn--sm"
          @click="emit('clearConcept')"
        >
          清除选中
        </button>
      </header>
      <div v-if="!catalogOk" class="rank-lane__empty muted">概念目录不可用</div>
      <div v-else-if="loading && !conceptsChange.length" class="rank-lane__empty muted">加载中…</div>
      <div v-else-if="!conceptsChange.length" class="rank-lane__empty muted">暂无数据</div>
      <table v-else class="data-table data-table--selectable rank-table">
        <thead>
          <tr>
            <th>#</th>
            <th>代码</th>
            <th>名称</th>
            <th class="col-num">指数</th>
            <th class="col-num">涨幅%</th>
            <th class="col-num">5分涨速%</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in conceptsChange"
            :key="row.code"
            :class="{ 'is-selected': row.code === activeConcept }"
            @click="emit('selectConcept', conceptSelectPayload(row))"
          >
            <td>{{ row.rank ?? "—" }}</td>
            <td>{{ row.code }}</td>
            <td :title="nameTitle(conceptName(row))">{{ conceptName(row) }}</td>
            <td class="col-num">{{ fmt(row.last) }}</td>
            <td class="col-num" :class="pctClass(row.change_pct)">{{ fmt(row.change_pct) }}</td>
            <td class="col-num" :class="pctClass(row.speed_pct)">{{ fmt(row.speed_pct) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="rank-lane">
      <header class="rank-lane__head">
        <h3>概念涨速</h3>
        <span v-if="conceptSpeedHint" class="muted rank-lane__hint">{{ conceptSpeedHint }}</span>
      </header>
      <div
        v-if="!conceptsSpeed.length && !catalogOk"
        class="rank-lane__empty muted"
      >
        概念目录不可用
      </div>
      <div
        v-else-if="!conceptsSpeed.length && !speedWarm"
        class="rank-lane__empty muted"
      >
        涨速数据预热中… {{ progressPct }}%
      </div>
      <div v-else-if="!conceptsSpeed.length" class="rank-lane__empty muted">暂无数据</div>
      <table v-else class="data-table data-table--selectable rank-table">
        <thead>
          <tr>
            <th>#</th>
            <th>代码</th>
            <th>名称</th>
            <th class="col-num">指数</th>
            <th class="col-num">涨幅%</th>
            <th class="col-num">5分涨速%</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in conceptsSpeed"
            :key="row.code"
            :class="{ 'is-selected': row.code === activeConcept }"
            @click="emit('selectConcept', conceptSelectPayload(row))"
          >
            <td>{{ row.rank ?? "—" }}</td>
            <td>{{ row.code }}</td>
            <td :title="nameTitle(conceptName(row))">{{ conceptName(row) }}</td>
            <td class="col-num">{{ fmt(row.last) }}</td>
            <td class="col-num" :class="pctClass(row.change_pct)">{{ fmt(row.change_pct) }}</td>
            <td class="col-num" :class="pctClass(row.speed_pct)">{{ fmt(row.speed_pct) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="rank-lane">
      <header class="rank-lane__head">
        <h3>自选涨幅</h3>
      </header>
      <div v-if="poolEmptyHint" class="rank-lane__empty muted">{{ poolEmptyHint }}</div>
      <div v-else-if="loading && !stocksChange.length" class="rank-lane__empty muted">加载中…</div>
      <div v-else-if="!stocksChange.length" class="rank-lane__empty muted">暂无数据</div>
      <table v-else class="data-table data-table--selectable rank-table">
        <thead>
          <tr>
            <th>#</th>
            <th>代码</th>
            <th>名称</th>
            <th class="col-num">最新价</th>
            <th class="col-num">涨幅%</th>
            <th class="col-num">5分涨速%</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in stocksChange"
            :key="row.symbol"
            :class="{ 'is-selected': row.symbol === activeSymbol }"
            @click="emit('selectSymbol', stockSelectPayload(row))"
          >
            <td>{{ row.rank ?? "—" }}</td>
            <td>{{ row.symbol }}</td>
            <td :title="nameTitle(displayStockName(row))">{{ displayStockName(row) }}</td>
            <td class="col-num">{{ fmt(stockLast(row)) }}</td>
            <td class="col-num" :class="pctClass(stockChangePct(row))">
              {{ fmt(stockChangePct(row)) }}
            </td>
            <td class="col-num" :class="pctClass(row.speed_pct)">{{ fmt(row.speed_pct) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="rank-lane">
      <header class="rank-lane__head">
        <h3>自选涨速</h3>
      </header>
      <div v-if="poolEmptyHint" class="rank-lane__empty muted">{{ poolEmptyHint }}</div>
      <div v-else-if="loading && !stocksSpeed.length" class="rank-lane__empty muted">加载中…</div>
      <div v-else-if="!stocksSpeed.length" class="rank-lane__empty muted">暂无数据</div>
      <table v-else class="data-table data-table--selectable rank-table">
        <thead>
          <tr>
            <th>#</th>
            <th>代码</th>
            <th>名称</th>
            <th class="col-num">最新价</th>
            <th class="col-num">涨幅%</th>
            <th class="col-num">5分涨速%</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in stocksSpeed"
            :key="row.symbol"
            :class="{ 'is-selected': row.symbol === activeSymbol }"
            @click="emit('selectSymbol', stockSelectPayload(row))"
          >
            <td>{{ row.rank ?? "—" }}</td>
            <td>{{ row.symbol }}</td>
            <td :title="nameTitle(displayStockName(row))">{{ displayStockName(row) }}</td>
            <td class="col-num">{{ fmt(stockLast(row)) }}</td>
            <td class="col-num" :class="pctClass(stockChangePct(row))">
              {{ fmt(stockChangePct(row)) }}
            </td>
            <td class="col-num" :class="pctClass(row.speed_pct)">{{ fmt(row.speed_pct) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
