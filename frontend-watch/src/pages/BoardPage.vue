<template>
  <div class="board-page">
    <div class="page-header board-page__header">
      <div>
        <h2 class="page-header__title">实时看板</h2>
        <p class="page-header__desc">股池 · 概念/自选榜 · K 线 · 告警</p>
        <p v-if="engineHint" class="page-header__desc">{{ engineHint }}</p>
      </div>
      <span class="muted">{{ statusText }}</span>
    </div>
    <p v-if="stale" class="warn-text">数据延迟（通达信约 3–5 秒；缓存可能陈旧）</p>

    <div class="cockpit-grid">
      <section class="panel cockpit-pool">
        <div class="cockpit-pool__stack">
          <div class="cockpit-pool__block">
            <h2>自选股池</h2>
            <table class="data-table data-table--selectable">
              <thead>
                <tr>
                  <th>代码</th>
                  <th>名称</th>
                  <th class="col-num">最新价</th>
                  <th class="col-num">涨跌幅%</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in rows"
                  :key="row.symbol"
                  :class="{
                    'is-stale': row.stale || row.degraded,
                    'is-selected': row.symbol === activeSymbol,
                  }"
                  @click="onSelectPool(row)"
                >
                  <td>{{ row.symbol }}</td>
                  <td>{{ (row.name || "").trim() || row.symbol }}</td>
                  <td class="col-num" :class="{ 'price-flash': !!flashing[row.symbol] }">
                    {{ fmt(row.last_price) }}
                  </td>
                  <td class="col-num" :class="pctClass(row.change_pct)">{{ fmt(row.change_pct) }}</td>
                </tr>
                <tr v-if="!rows.length">
                  <td colspan="4" class="muted">暂无标的。请在「盯盘管理」添加并启用。</td>
                </tr>
              </tbody>
            </table>
          </div>
          <ConstituentsPanel
            class="cockpit-pool__block"
            :active-concept="selectedConcept"
            :ranks-active-concept="ranks.active_concept"
            :constituents="ranks.constituents"
            :constituents-meta="ranks.constituents_meta"
            :active-symbol="activeSymbol"
            @select-symbol="onSelectSymbol"
          />
        </div>
      </section>

      <section class="panel cockpit-ranks">
        <RankLanes
          :concepts-change="ranks.concepts_change"
          :concepts-speed="ranks.concepts_speed"
          :stocks-change="ranks.stocks_change"
          :stocks-speed="ranks.stocks_speed"
          :active-concept="selectedConcept"
          :meta="ranks.meta"
          :degraded="ranks.degraded"
          :message="ranks.message"
          :loading="ranksLoading"
          :active-symbol="activeSymbol"
          :symbol-quotes="poolSymbolQuotes"
          @select-concept="onSelectConcept"
          @select-symbol="onSelectSymbol"
          @clear-concept="clearConcept"
        />
      </section>

      <section class="panel cockpit-chart">
        <ChartPanel :symbol="activeSymbol" :title="chartTitle" />
      </section>

      <section class="panel cockpit-alerts">
        <div class="row" style="justify-content: space-between">
          <div>
            <h2 style="margin: 0">最近告警</h2>
            <p class="muted" style="margin: 4px 0 0">全部配置 · 仅 quote_alert</p>
          </div>
          <RouterLink class="btn btn--secondary btn--sm" to="/alerts">全部告警</RouterLink>
        </div>
        <table class="data-table" style="margin-top: 12px">
          <thead>
            <tr>
              <th>时间</th>
              <th>代码</th>
              <th>规则</th>
              <th>摘要</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in recentAlerts" :key="a.id">
              <td>{{ fmtTime(a.created_at) }}</td>
              <td>{{ a.symbol || "—" }}</td>
              <td>{{ a.rule_id || "—" }}</td>
              <td class="muted">{{ a.payload_json?.message || "—" }}</td>
            </tr>
            <tr v-if="!recentAlerts.length">
              <td colspan="4" class="muted">暂无告警</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { RouterLink } from "vue-router";
import { apiRequest, ApiError, obtainWatchToken } from "@/api/client";
import ChartPanel from "@/components/ChartPanel.vue";
import ConstituentsPanel, { type ConstituentsMeta } from "@/components/ConstituentsPanel.vue";
import RankLanes, {
  type RankConceptRow,
  type RankStockRow,
  type RanksMeta,
} from "@/components/RankLanes.vue";

type QuoteRow = {
  symbol: string;
  name?: string;
  last_price?: number | null;
  change_pct?: number | null;
  open?: number | null;
  pre_close?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number | null;
  amount?: number | null;
  stale?: boolean;
  degraded?: boolean;
};

type Alert = {
  id: number;
  event_type: string;
  symbol: string;
  rule_id: string;
  payload_json: { message?: string };
  created_at?: string;
};

type RanksPayload = {
  concepts_change: RankConceptRow[];
  concepts_speed: RankConceptRow[];
  stocks_change: RankStockRow[];
  stocks_speed: RankStockRow[];
  constituents: RankStockRow[];
  constituents_meta: ConstituentsMeta;
  active_concept: string | null;
  degraded: boolean;
  message: string;
  meta: RanksMeta;
};

const emptyRanks = (): RanksPayload => ({
  concepts_change: [],
  concepts_speed: [],
  stocks_change: [],
  stocks_speed: [],
  constituents: [],
  constituents_meta: {},
  active_concept: null,
  degraded: false,
  message: "",
  meta: {
    catalog_ok: true,
    speed_warm: false,
    speed_warm_progress: 0,
    pool_count: 0,
    stale_speed: false,
  },
});

const rows = ref<QuoteRow[]>([]);
const stale = ref(false);
const statusText = ref("连接中…");
const engineHint = ref("");
const activeSymbol = ref("");
const chartTitle = ref("");
const selectedConcept = ref<string | null>(null);
const recentAlerts = ref<Alert[]>([]);
const flashing = ref<Record<string, boolean>>({});
const ranks = reactive<RanksPayload>(emptyRanks());
const ranksLoading = ref(false);

const poolSymbolQuotes = computed(() => {
  const m: Record<
    string,
    { name?: string; last?: number | null; change_pct?: number | null }
  > = {};
  for (const row of rows.value) {
    if (!row.symbol) continue;
    const name = (row.name || "").trim();
    m[row.symbol] = {
      name: name || undefined,
      last: row.last_price ?? null,
      change_pct: row.change_pct ?? null,
    };
  }
  return m;
});

const prevLast = new Map<string, number | null | undefined>();
const flashTimers = new Map<string, number>();
let primed = false;
let ranksReqId = 0;

let ws: WebSocket | null = null;
let pollTimer: number | null = null;
let reconnectTimer: number | null = null;
let retryMs = 3000;
let engineTimer: number | null = null;
let alertTimer: number | null = null;
let ranksTimer: number | null = null;
let disposed = false;

function fmt(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toFixed(2);
}

function pctClass(v: number | null | undefined) {
  if (v == null) return "pnl-flat";
  if (v > 0) return "pnl-rise";
  if (v < 0) return "pnl-fall";
  return "pnl-flat";
}

function fmtTime(raw?: string) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function clearFlashTimers() {
  for (const t of flashTimers.values()) window.clearTimeout(t);
  flashTimers.clear();
  flashing.value = {};
}

function triggerFlash(symbol: string) {
  if (disposed) return;
  flashing.value = { ...flashing.value, [symbol]: true };
  const prev = flashTimers.get(symbol);
  if (prev != null) window.clearTimeout(prev);
  flashTimers.set(
    symbol,
    window.setTimeout(() => {
      if (disposed) return;
      const next = { ...flashing.value };
      delete next[symbol];
      flashing.value = next;
      flashTimers.delete(symbol);
    }, 400),
  );
}

function applyQuotes(items: QuoteRow[], batchStale?: boolean) {
  if (disposed) return;
  const sorted = [...(items || [])].sort((a, b) => a.symbol.localeCompare(b.symbol));
  if (primed) {
    for (const row of sorted) {
      const prev = prevLast.get(row.symbol);
      const cur = row.last_price;
      if (prev != null && cur != null && Number(prev) !== Number(cur)) {
        triggerFlash(row.symbol);
      }
    }
  } else {
    primed = true;
  }
  prevLast.clear();
  for (const row of sorted) {
    prevLast.set(row.symbol, row.last_price);
  }
  rows.value = sorted;
  stale.value = Boolean(batchStale) || sorted.some((r) => r.stale || r.degraded);
  if (!activeSymbol.value && sorted.length) {
    activeSymbol.value = sorted[0].symbol;
    chartTitle.value = (sorted[0].name || "").trim() || sorted[0].symbol;
  }
}

function onSelectConcept(payload: { code: string; name?: string }) {
  selectedConcept.value = payload.code;
  activeSymbol.value = payload.code;
  chartTitle.value = (payload.name || "").trim() || payload.code;
  void loadRanks();
}

function onSelectSymbol(payload: { symbol: string; name?: string }) {
  activeSymbol.value = payload.symbol;
  chartTitle.value = (payload.name || "").trim() || payload.symbol;
}

function onSelectPool(row: { symbol: string; name?: string | null }) {
  activeSymbol.value = row.symbol;
  chartTitle.value = (row.name || "").trim() || row.symbol;
}

function clearConcept() {
  selectedConcept.value = null;
  // 成分以成功响应为准；勿乐观清空，避免 502 时其它车道保留、成分已空
  void loadRanks();
}

async function loadRanks() {
  if (disposed) return;
  const id = ++ranksReqId;
  const conceptQ =
    selectedConcept.value != null && selectedConcept.value !== ""
      ? `&concept=${encodeURIComponent(selectedConcept.value)}`
      : "";
  if (!ranks.concepts_change.length && !ranks.stocks_change.length) {
    ranksLoading.value = true;
  }
  try {
    const data = await apiRequest<RanksPayload>(`/api/v1/watch/ranks?top_n=30${conceptQ}`);
    if (disposed || id !== ranksReqId) return;
    ranks.concepts_change = data.concepts_change || [];
    ranks.concepts_speed = data.concepts_speed || [];
    ranks.stocks_change = data.stocks_change || [];
    ranks.stocks_speed = data.stocks_speed || [];
    ranks.constituents = data.constituents || [];
    ranks.constituents_meta = data.constituents_meta || {};
    ranks.active_concept = data.active_concept ?? null;
    ranks.degraded = Boolean(data.degraded);
    ranks.message = data.message || "";
    ranks.meta = {
      catalog_ok: data.meta?.catalog_ok !== false,
      speed_warm: Boolean(data.meta?.speed_warm),
      speed_warm_progress: Number(data.meta?.speed_warm_progress ?? 0),
      pool_count: Number(data.meta?.pool_count ?? 0),
      stale_speed: Boolean(data.meta?.stale_speed),
    };
    // Server null / unknown concept → clear local selection; keep K (activeSymbol)
    if (data.active_concept == null && selectedConcept.value) {
      selectedConcept.value = null;
    } else if (data.active_concept) {
      selectedConcept.value = data.active_concept;
    }
  } catch (err) {
    if (disposed || id !== ranksReqId) return;
    if (err instanceof ApiError && (err.status === 502 || err.status >= 500)) {
      ranks.degraded = true;
      ranks.message = "榜单拉取失败，保留上一帧";
      // 回滚选中概念，避免与 constituents 永久串台导致「加载中…」死锁
      selectedConcept.value = ranks.active_concept;
      return;
    }
    ranks.degraded = true;
    ranks.message = err instanceof Error ? err.message : "榜单失败";
    selectedConcept.value = ranks.active_concept;
  } finally {
    if (id === ranksReqId) ranksLoading.value = false;
  }
}

async function loadEngine() {
  if (disposed) return;
  try {
    const st = await apiRequest<{
      ticker_running?: boolean;
      off_hours?: boolean;
      leader_held?: boolean;
      cache_stale?: boolean;
      enabled_profile_count?: number;
    }>("/api/v1/watch/engine-status");
    if (disposed) return;
    const bits = [
      st.ticker_running ? "引擎运行" : "引擎停止",
      st.off_hours ? "非交易时段" : "交易时段",
      st.leader_held ? "leader" : "非leader",
      `启用配置 ${st.enabled_profile_count ?? 0}`,
    ];
    if (st.cache_stale) bits.push("cache stale");
    engineHint.value = bits.join(" · ");
  } catch {
    if (!disposed) engineHint.value = "";
  }
}

async function loadAlerts() {
  if (disposed) return;
  try {
    const data = await apiRequest<{ items: Alert[] }>("/api/v1/watch/alerts?skip=0&limit=30");
    if (disposed) return;
    recentAlerts.value = (data.items || [])
      .filter((a) => a.event_type === "quote_alert")
      .slice(0, 10);
  } catch {
    /* keep previous */
  }
}

async function pollHttp() {
  if (disposed) return;
  try {
    const data = await apiRequest<{ items: QuoteRow[]; stale?: boolean }>("/api/v1/watch/quotes");
    if (disposed) return;
    applyQuotes(data.items || [], data.stale);
    statusText.value = "HTTP 轮询";
  } catch {
    if (!disposed) statusText.value = "行情拉取失败";
  }
}

function clearPoll() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function clearReconnect() {
  if (reconnectTimer != null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function connectWs() {
  if (disposed) return;
  const token = obtainWatchToken();
  if (!token) {
    statusText.value = "未登录";
    return;
  }
  clearReconnect();
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/api/v1/watch/stream`, [`bearer.${token}`]);
  ws.onopen = () => {
    if (disposed) return;
    statusText.value = "WS 已连接";
    retryMs = 3000;
    clearPoll();
    clearReconnect();
    if (!ws?.protocol) {
      ws?.send(JSON.stringify({ type: "auth", token }));
    }
  };
  ws.onmessage = (ev) => {
    if (disposed) return;
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "quotes") {
        applyQuotes(msg.items || [], msg.stale);
        statusText.value = msg.stale ? "WS（数据延迟）" : "WS 实时";
      }
    } catch {
      /* ignore */
    }
  };
  ws.onclose = () => {
    ws = null;
    if (disposed) return;
    statusText.value = "WS 断开，回退 HTTP";
    void pollHttp();
    if (pollTimer == null) {
      pollTimer = window.setInterval(() => void pollHttp(), Math.max(3000, retryMs));
    }
    retryMs = Math.min(retryMs * 1.5, 15000);
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connectWs();
    }, retryMs);
  };
}

onMounted(() => {
  disposed = false;
  connectWs();
  void loadEngine();
  void loadAlerts();
  void loadRanks();
  engineTimer = window.setInterval(() => void loadEngine(), 15000);
  alertTimer = window.setInterval(() => void loadAlerts(), 20000);
  ranksTimer = window.setInterval(() => void loadRanks(), 4000);
});

onUnmounted(() => {
  disposed = true;
  clearReconnect();
  clearPoll();
  clearFlashTimers();
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  if (engineTimer != null) window.clearInterval(engineTimer);
  if (alertTimer != null) window.clearInterval(alertTimer);
  if (ranksTimer != null) window.clearInterval(ranksTimer);
});
</script>
