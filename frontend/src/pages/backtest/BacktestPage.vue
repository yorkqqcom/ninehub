<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { apiRequest, ApiError, getToken } from "@/api/client";
import type { PlatformJob } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { useUiStore } from "@/stores/ui";
import { disposeAndReinitChart, ensureChartInstance } from "@/utils/echartsTheme";

type SignalParam = {
  key: string;
  label: string;
  type: string;
  default?: unknown;
  min?: number;
  max?: number;
  options?: string[];
};

type SignalDef = {
  id: string;
  name: string;
  description: string;
  params: SignalParam[];
};

type WatchlistItem = { id: number; name: string; codes?: string[] };

type BacktestKpi = {
  total_return: number;
  max_drawdown: number;
  sharpe: number | null;
  trade_count: number;
  sample_days: number;
};

type BacktestResult = {
  job_id: number;
  status: string;
  kpi: BacktestKpi;
  equity_curve: Array<{ date: string; equity: number }>;
  trades_preview: Array<Record<string, unknown>>;
  download_url: string;
  codes_loaded?: string[] | null;
  codes_requested?: string[] | null;
  codes_missing?: string[] | null;
};

const POLL_MAX = 120;

const ui = useUiStore();

const signals = ref<SignalDef[]>([]);
const watchlists = ref<WatchlistItem[]>([]);
const universeMode = ref<"watchlist" | "codes">("watchlist");
const watchlistId = ref<number | null>(null);
const codesText = ref("");
const startDate = ref("");
const endDate = ref("");
const signalId = ref("");
const paramValues = ref<Record<string, string | number>>({});
const adjust = ref("qfq");
const commissionBps = ref(5);
const slippageBps = ref(5);
const maxPositions = ref(5);

const busy = ref(false);
const job = ref<PlatformJob | null>(null);
const result = ref<BacktestResult | null>(null);
let pollTimer: number | undefined;
let pollAttempts = 0;
let pollInFlight = false;
let chartInst: import("echarts").ECharts | null = null;
const chartEl = ref<HTMLElement | null>(null);

const activeSignal = computed(() => signals.value.find((s) => s.id === signalId.value) ?? null);

const selectedWatchlistCodes = computed(() => {
  const wl = watchlists.value.find((w) => w.id === watchlistId.value);
  return wl?.codes ?? [];
});

function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.details as
      | { details?: { errors?: unknown }; errors?: unknown }
      | undefined;
    const nested = body?.details?.errors ?? body?.errors;
    if (Array.isArray(nested) && nested.length) {
      const extra = nested
        .map((x) => String(x))
        .filter(Boolean)
        .slice(0, 3)
        .join("；");
      if (extra) return `${e.message}：${extra}`;
    }
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

function formatLocalDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(end.getFullYear() - 1);
  endDate.value = formatLocalDate(end);
  startDate.value = formatLocalDate(start);
}

function applySignalDefaults(sig: SignalDef | null) {
  const next: Record<string, string | number> = {};
  if (sig) {
    for (const p of sig.params) {
      next[p.key] = (p.default as string | number) ?? "";
    }
  }
  paramValues.value = next;
}

watch(signalId, () => applySignalDefaults(activeSignal.value));

async function loadMeta() {
  const [sigs, wls] = await Promise.all([
    apiRequest<SignalDef[]>("/api/v1/research/backtests/signals"),
    apiRequest<WatchlistItem[]>("/api/v1/query/browser/watchlists"),
  ]);
  signals.value = sigs;
  watchlists.value = wls;
  if (!signalId.value && sigs.length) {
    signalId.value = sigs[0].id;
    applySignalDefaults(sigs[0]);
  }
  if (watchlistId.value == null && wls.length) {
    watchlistId.value = wls[0].id;
  }
  if (!wls.length) {
    universeMode.value = "codes";
  }
}

function buildBody() {
  const params: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(paramValues.value)) {
    const def = activeSignal.value?.params.find((p) => p.key === k);
    if (def?.type === "int") params[k] = Number(v);
    else if (def?.type === "float") params[k] = Number(v);
    else params[k] = v;
  }
  const body: Record<string, unknown> = {
    start_date: startDate.value,
    end_date: endDate.value,
    signal_id: signalId.value,
    params,
    adjust: adjust.value,
    commission_bps: Number(commissionBps.value),
    slippage_bps: Number(slippageBps.value),
    max_positions: Number(maxPositions.value),
  };
  if (universeMode.value === "watchlist") {
    body.watchlist_id = watchlistId.value;
  } else {
    body.codes = codesText.value
      .split(/[\s,;]+/)
      .map((c) => c.trim().toUpperCase())
      .filter(Boolean);
  }
  return body;
}

function clearPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = undefined;
  }
  pollInFlight = false;
}

async function pollJob(jobId: number) {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    pollAttempts += 1;
    if (pollAttempts > POLL_MAX) {
      clearPoll();
      busy.value = false;
      ui.showMessage("轮询超时，请稍后在平台任务中查看", "error");
      return;
    }
    const data = await apiRequest<PlatformJob>(`/api/v1/platform/jobs/${jobId}`);
    job.value = data;
    if (data.status === "success") {
      clearPoll();
      busy.value = false;
      const res = await apiRequest<BacktestResult>(`/api/v1/research/backtests/${jobId}`);
      result.value = res;
      ui.showMessage("回测完成", "success");
      await nextTick();
      await renderChart();
      return;
    }
    if (data.status === "failed") {
      clearPoll();
      busy.value = false;
      ui.showMessage(data.error || data.message || "回测失败", "error");
    }
  } catch (e) {
    clearPoll();
    busy.value = false;
    ui.showMessage(errMsg(e), "error");
  } finally {
    pollInFlight = false;
  }
}

async function runBacktest() {
  if (busy.value) return;
  result.value = null;
  try {
    const body = buildBody();
    if (universeMode.value === "watchlist") {
      if (!watchlistId.value) {
        ui.showMessage("请选择证券池", "error");
        return;
      }
      if (!selectedWatchlistCodes.value.length) {
        ui.showMessage("所选证券池为空", "error");
        return;
      }
      if (selectedWatchlistCodes.value.length > 200) {
        ui.showMessage("证券池超过 200", "error");
        return;
      }
    } else {
      const codes = (body.codes as string[]) || [];
      if (!codes.length) {
        ui.showMessage("请输入股票代码", "error");
        return;
      }
      if (codes.length > 200) {
        ui.showMessage("证券池超过 200", "error");
        return;
      }
    }
    if (!startDate.value || !endDate.value) {
      ui.showMessage("请填写回测区间", "error");
      return;
    }
    if (startDate.value > endDate.value) {
      ui.showMessage("结束日早于开始日", "error");
      return;
    }
    const spanMs =
      new Date(endDate.value).getTime() - new Date(startDate.value).getTime();
    if (spanMs > 5 * 366 * 24 * 3600 * 1000) {
      ui.showMessage("回测区间不得超过 5 年", "error");
      return;
    }
    if (Number(commissionBps.value) < 0 || Number(slippageBps.value) < 0) {
      ui.showMessage("费用/滑点不能为负", "error");
      return;
    }
    busy.value = true;
    pollAttempts = 0;
    const res = await apiRequest<{ job_id: number }>("/api/v1/research/backtests", {
      method: "POST",
      body: JSON.stringify(body),
    });
    ui.showMessage(`回测任务 #${res.job_id} 已入队`, "success");
    clearPoll();
    pollTimer = window.setInterval(() => void pollJob(res.job_id), 1500);
    await pollJob(res.job_id);
  } catch (e) {
    busy.value = false;
    ui.showMessage(errMsg(e), "error");
  }
}

async function renderChart() {
  if (!chartEl.value || !result.value?.equity_curve?.length) return;
  const mode = ui.theme;
  chartInst = await ensureChartInstance(chartEl.value, chartInst, mode);
  const dates = result.value.equity_curve.map((p) => p.date);
  const equity = result.value.equity_curve.map((p) => p.equity);
  chartInst.setOption({
    title: { text: "净值曲线", left: 0, textStyle: { fontSize: 14 } },
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 24, top: 40, bottom: 32 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true },
    series: [{ type: "line", data: equity, showSymbol: false, name: "equity" }],
  });
}

watch(
  () => ui.theme,
  async () => {
    if (!chartEl.value) return;
    chartInst = await disposeAndReinitChart(chartEl.value, chartInst, ui.theme);
    await renderChart();
  },
);

async function downloadResult() {
  if (!result.value) return;
  const token = getToken();
  const res = await fetch(result.value.download_url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    ui.showMessage("下载失败", "error");
    return;
  }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `backtest_${result.value.job_id}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function fmtPct(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

onMounted(async () => {
  defaultDates();
  window.addEventListener("resize", onChartResize);
  try {
    await loadMeta();
  } catch (e) {
    ui.showMessage(errMsg(e), "error");
  }
});

function onChartResize() {
  chartInst?.resize();
}

onUnmounted(() => {
  clearPoll();
  window.removeEventListener("resize", onChartResize);
  chartInst?.dispose();
  chartInst = null;
});
</script>

<template>
  <div class="backtest-page">
    <PageHeader title="策略回测" description="日线信号 · 证券池 · platform job 异步">
      <template #actions>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="runBacktest">
          {{ busy ? "运行中…" : "运行回测" }}
        </button>
        <button
          class="btn"
          type="button"
          :disabled="!result"
          @click="downloadResult"
        >
          下载明细
        </button>
      </template>
    </PageHeader>

    <section class="panel">
      <h2 class="panel__title">参数</h2>
      <div class="form-grid">
        <label class="field">
          <span>证券池来源</span>
          <select v-model="universeMode">
            <option value="watchlist">Browser 证券池</option>
            <option value="codes">手输代码</option>
          </select>
        </label>
        <label v-if="universeMode === 'watchlist'" class="field">
          <span>证券池</span>
          <select v-model.number="watchlistId" :disabled="!watchlists.length">
            <option v-if="!watchlists.length" :value="null">暂无证券池</option>
            <option v-for="w in watchlists" :key="w.id" :value="w.id">
              {{ w.name }}（{{ (w.codes || []).length }}）
            </option>
          </select>
          <span v-if="!watchlists.length" class="hint">请先在数据浏览器创建证券池，或改用手输代码</span>
        </label>
        <label v-else class="field field--wide">
          <span>代码（######.SH/SZ，逗号分隔，≤200）</span>
          <textarea v-model="codesText" rows="3" placeholder="000001.SZ,600000.SH" />
        </label>
        <label class="field">
          <span>开始日</span>
          <input v-model="startDate" type="date" />
        </label>
        <label class="field">
          <span>结束日</span>
          <input v-model="endDate" type="date" />
        </label>
        <label class="field">
          <span>复权</span>
          <select v-model="adjust">
            <option value="qfq">前复权</option>
            <option value="hfq">后复权</option>
            <option value="none">不复权</option>
          </select>
        </label>
        <label class="field">
          <span>信号</span>
          <select v-model="signalId">
            <option v-for="s in signals" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </label>
        <p v-if="activeSignal" class="hint field--wide">{{ activeSignal.description }}</p>
        <template v-if="activeSignal">
          <label v-for="p in activeSignal.params" :key="p.key" class="field">
            <span>{{ p.label }}</span>
            <select v-if="p.type === 'enum'" v-model="paramValues[p.key]">
              <option v-for="opt in p.options || []" :key="opt" :value="opt">{{ opt }}</option>
            </select>
            <input
              v-else
              v-model="paramValues[p.key]"
              :type="p.type === 'int' || p.type === 'float' ? 'number' : 'text'"
              :step="p.type === 'float' ? '0.001' : '1'"
              :min="p.min"
              :max="p.max"
            />
          </label>
        </template>
        <label class="field">
          <span>佣金 bps</span>
          <input v-model.number="commissionBps" type="number" min="0" step="0.1" />
        </label>
        <label class="field">
          <span>滑点 bps</span>
          <input v-model.number="slippageBps" type="number" min="0" step="0.1" />
        </label>
        <label class="field">
          <span>最大持仓</span>
          <input v-model.number="maxPositions" type="number" min="1" max="200" />
        </label>
      </div>
    </section>

    <section v-if="job" class="panel">
      <h2 class="panel__title">运行状态</h2>
      <div class="status-row">
        <span>Job #{{ job.id }}</span>
        <span>{{ job.status }}</span>
        <span>{{ job.progress }}%</span>
        <span class="muted">{{ job.message }}</span>
      </div>
      <p v-if="job.error" class="error">{{ job.error }}</p>
    </section>

    <section v-if="result" class="panel">
      <h2 class="panel__title">结果摘要</h2>
      <div class="kpi-row">
        <div class="kpi"><span class="kpi__label">总收益</span><strong>{{ fmtPct(result.kpi.total_return) }}</strong></div>
        <div class="kpi"><span class="kpi__label">最大回撤</span><strong>{{ fmtPct(result.kpi.max_drawdown) }}</strong></div>
        <div class="kpi">
          <span class="kpi__label">夏普</span>
          <strong>{{ result.kpi.sharpe == null ? "N/A" : result.kpi.sharpe.toFixed(2) }}</strong>
        </div>
        <div class="kpi"><span class="kpi__label">交易次数</span><strong>{{ result.kpi.trade_count }}</strong></div>
        <div class="kpi"><span class="kpi__label">样本日</span><strong>{{ result.kpi.sample_days }}</strong></div>
        <div v-if="result.codes_loaded?.length" class="kpi">
          <span class="kpi__label">已加载</span>
          <strong>{{ result.codes_loaded.length }}</strong>
        </div>
      </div>
      <p v-if="result.codes_missing?.length" class="hint">
        区间内无日线、已跳过 {{ result.codes_missing.length }} 只：
        {{ result.codes_missing.slice(0, 8).join("、")
        }}{{ result.codes_missing.length > 8 ? "…" : "" }}
      </p>
      <div ref="chartEl" class="chart" />
      <h3 class="subhead">成交预览</h3>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>代码</th>
              <th>方向</th>
              <th>价格</th>
              <th>数量</th>
              <th>费用</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in result.trades_preview" :key="i">
              <td>{{ t.date }}</td>
              <td>{{ t.code }}</td>
              <td>{{ t.side }}</td>
              <td>{{ t.price }}</td>
              <td>{{ t.shares }}</td>
              <td>{{ t.fee }}</td>
            </tr>
            <tr v-if="!result.trades_preview.length">
              <td colspan="6" class="muted">无成交</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.backtest-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}
.panel__title {
  margin: 0 0 0.75rem;
  font-size: 1rem;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem 1rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.875rem;
}
.field--wide {
  grid-column: 1 / -1;
}
.field input,
.field select,
.field textarea {
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-elevated, var(--color-surface));
  color: var(--color-text);
}
.hint {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
.status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.9rem;
}
.muted {
  color: var(--color-text-muted);
}
.error {
  color: var(--color-fall, #c0392b);
}
.kpi-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1rem;
}
.kpi {
  min-width: 6.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.kpi__label {
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.chart {
  width: 100%;
  height: 320px;
}
.subhead {
  margin: 1rem 0 0.5rem;
  font-size: 0.95rem;
}
.table-wrap {
  overflow: auto;
  max-height: 320px;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.data-table th,
.data-table td {
  border-bottom: 1px solid var(--color-border);
  padding: 0.35rem 0.5rem;
  text-align: left;
}
.btn {
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-elevated, var(--color-surface));
  color: var(--color-text);
  cursor: pointer;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn-primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}
</style>
