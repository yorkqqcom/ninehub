<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { apiRequest, ApiError } from "@/api/client";
import {
  type ChartBar,
  cropLastSession,
  cumulativeAvg,
  dayKey,
  formatDailyRange,
  formatSessionLabel,
  isConceptIndexSymbol,
  quoteStatsDaily,
  quoteStatsIntraday,
  sma,
  toSessionPoints,
} from "@/utils/chartMath";

export type { ChartBar };

const props = defineProps<{
  symbol: string;
  title?: string;
}>();

const period = ref<"1m" | "1d">("1m");
const bars = ref<ChartBar[]>([]);
const prevClose = ref<number | null>(null);
const status = ref("");
const degraded = ref(false);
let reqId = 0;

const isConcept = computed(() => isConceptIndexSymbol(props.symbol));
const showIntradayAvg = computed(() => period.value === "1m" && !isConcept.value);

const W = 400;
const H = 300;
const pad = { l: 44, r: 8, t: 10, b: 18 };
const mainFrac = 0.72;
const gap = 6;

const mainTop = pad.t;
const mainH = (H - pad.t - pad.b - gap) * mainFrac;
const volTop = mainTop + mainH + gap;
const volH = H - pad.t - pad.b - gap - mainH;
const innerW = W - pad.l - pad.r;

const displayBars = computed(() => {
  if (period.value === "1m") return cropLastSession(bars.value);
  const sorted = [...bars.value].sort((a, b) =>
    String(a.ts || "").localeCompare(String(b.ts || "")),
  );
  return sorted.slice(-120);
});

const quote = computed(() => {
  if (period.value === "1m") {
    return quoteStatsIntraday(displayBars.value, prevClose.value);
  }
  return quoteStatsDaily(displayBars.value);
});

const dateLabel = computed(() => {
  if (period.value === "1m") return formatSessionLabel(displayBars.value);
  return formatDailyRange(displayBars.value);
});

function yScale(min: number, max: number, top: number, height: number) {
  const span = max - min || 1;
  return (v: number) => top + (1 - (v - min) / span) * height;
}

function polyline(xs: number[], ys: number[]): string {
  if (xs.length < 2) return "";
  return xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
}

const intradayModel = computed(() => {
  if (period.value !== "1m") return null;
  const points = toSessionPoints(displayBars.value);
  if (!points.length) return null;
  // 概念指数分时不显示均价线（TDX amount 不可靠）；与图例 showIntradayAvg 一致
  const showAvg = showIntradayAvg.value;
  const avgs = showAvg ? cumulativeAvg(points) : [];
  const prices = points.map((p) => p.close);
  const ref = prevClose.value;
  let ymin = Math.min(...prices);
  let ymax = Math.max(...prices);
  if (showAvg && avgs.length) {
    ymin = Math.min(ymin, ...avgs);
    ymax = Math.max(ymax, ...avgs);
  }
  if (ref !== null && ref > 0) {
    ymin = Math.min(ymin, ref);
    ymax = Math.max(ymax, ref);
  }
  const padPct = (ymax - ymin) * 0.02 || ymax * 0.01 || 0.01;
  ymin -= padPct;
  ymax += padPct;
  const y = yScale(ymin, ymax, mainTop, mainH);
  const xOf = (slot: number) => pad.l + (slot / 239) * innerW;
  const pricePath = polyline(
    points.map((p) => xOf(p.slot)),
    points.map((p) => y(p.close)),
  );
  const avgPath = showAvg
    ? polyline(
        points.map((p) => xOf(p.slot)),
        avgs.map((a) => y(a)),
      )
    : "";
  const maxVol = Math.max(...points.map((p) => p.volume), 0);
  const volBars = points.map((p) => {
    const x = xOf(p.slot);
    const bw = Math.max(1, innerW / 240);
    const vh = maxVol > 0 ? (p.volume / maxVol) * (volH - 2) : 0;
    const up =
      ref !== null && ref > 0
        ? p.close >= ref
        : p.close >= Number(points[0]?.bar.open || p.close);
    return { x, y: volTop + volH - vh, h: Math.max(vh, p.volume > 0 ? 1 : 0), bw, up };
  });
  const gridYs = [0, 0.5, 1].map((t) => mainTop + t * mainH);
  const priceLabels = [
    { y: mainTop + 4, text: ymax.toFixed(2) },
    { y: mainTop + mainH / 2, text: ((ymin + ymax) / 2).toFixed(2) },
    { y: mainTop + mainH - 2, text: ymin.toFixed(2) },
  ];
  const axis = [
    { x: xOf(0), text: "09:30" },
    { x: xOf(120), text: "11:30/13:00" },
    { x: xOf(239), text: "15:00" },
  ];
  const prevY = ref !== null && ref > 0 ? y(ref) : null;
  return { pricePath, avgPath, volBars, gridYs, priceLabels, axis, prevY, hasVol: maxVol > 0 };
});

const dailyModel = computed(() => {
  if (period.value !== "1d") return null;
  const rows = displayBars.value.filter(
    (b) =>
      Number(b.open) > 0 &&
      Number(b.high) > 0 &&
      Number(b.low) > 0 &&
      Number(b.close) > 0,
  );
  if (!rows.length) return null;
  const closes = rows.map((b) => Number(b.close));
  const ma5 = sma(closes, 5);
  const ma10 = sma(closes, 10);
  const ma20 = sma(closes, 20);
  const highs = rows.map((b) => Number(b.high));
  const lows = rows.map((b) => Number(b.low));
  const maVals = [...ma5, ...ma10, ...ma20].filter((v): v is number => v !== null);
  let ymin = Math.min(...lows, ...(maVals.length ? maVals : lows));
  let ymax = Math.max(...highs, ...(maVals.length ? maVals : highs));
  const padPct = (ymax - ymin) * 0.02 || 0.01;
  ymin -= padPct;
  ymax += padPct;
  const y = yScale(ymin, ymax, mainTop, mainH);
  const n = rows.length;
  const bw = Math.max(2, (innerW / n) * 0.6);
  const candles = rows.map((b, i) => {
    const o = Number(b.open);
    const c = Number(b.close);
    const h = Number(b.high);
    const l = Number(b.low);
    const x = pad.l + ((i + 0.5) / n) * innerW;
    const yO = y(o);
    const yC = y(c);
    return {
      x,
      yHigh: y(h),
      yLow: y(l),
      bodyY: Math.min(yO, yC),
      bodyH: Math.max(1, Math.abs(yC - yO)),
      bw,
      up: c >= o,
    };
  });
  const maPath = (series: (number | null)[]) => {
    const xs: number[] = [];
    const ys: number[] = [];
    series.forEach((v, i) => {
      if (v === null) return;
      xs.push(pad.l + ((i + 0.5) / n) * innerW);
      ys.push(y(v));
    });
    return polyline(xs, ys);
  };
  const vols = rows.map((b) => Number(b.volume) || 0);
  const maxVol = Math.max(...vols, 0);
  const volBars = rows.map((b, i) => {
    const x = pad.l + ((i + 0.5) / n) * innerW;
    const v = vols[i];
    const vh = maxVol > 0 ? (v / maxVol) * (volH - 2) : 0;
    return {
      x,
      y: volTop + volH - vh,
      h: Math.max(vh, v > 0 ? 1 : 0),
      bw,
      up: Number(b.close) >= Number(b.open),
    };
  });
  const gridYs = [0, 0.5, 1].map((t) => mainTop + t * mainH);
  const priceLabels = [
    { y: mainTop + 4, text: ymax.toFixed(2) },
    { y: mainTop + mainH / 2, text: ((ymin + ymax) / 2).toFixed(2) },
    { y: mainTop + mainH - 2, text: ymin.toFixed(2) },
  ];
  const first = dayKey(rows[0]?.ts);
  const last = dayKey(rows[rows.length - 1]?.ts);
  const axis = [
    { x: pad.l, text: first ? first.slice(5) : "" },
    { x: pad.l + innerW, text: last ? last.slice(5) : "" },
  ];
  return {
    candles,
    ma5: maPath(ma5),
    ma10: maPath(ma10),
    ma20: maPath(ma20),
    volBars,
    gridYs,
    priceLabels,
    axis,
    hasVol: maxVol > 0,
  };
});

async function loadBars() {
  const sym = (props.symbol || "").trim();
  if (!sym) {
    bars.value = [];
    prevClose.value = null;
    status.value = "";
    degraded.value = false;
    return;
  }
  const id = ++reqId;
  try {
    const data = await apiRequest<{
      items?: ChartBar[];
      prev_close?: number | null;
      degraded?: boolean;
      message?: string;
    }>(`/api/v1/watch/bars?symbol=${encodeURIComponent(sym)}&period=${period.value}`);
    if (id !== reqId) return;
    const next = data.items || [];
    if (data.degraded && !next.length && bars.value.length) {
      degraded.value = true;
      status.value = data.message || "行情降级，保留上一帧";
      return;
    }
    bars.value = next;
    if (period.value === "1m") {
      const pc = data.prev_close;
      prevClose.value =
        pc !== undefined && pc !== null && Number.isFinite(Number(pc)) ? Number(pc) : null;
    } else {
      prevClose.value = null;
    }
    degraded.value = Boolean(data.degraded);
    if (data.degraded && data.message) {
      status.value = data.message;
    } else if (next.length) {
      status.value =
        period.value === "1m"
          ? formatSessionLabel(cropLastSession(next))
          : formatDailyRange(
              [...next]
                .sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")))
                .slice(-120),
            );
    } else {
      status.value = data.message || "暂无 K 线数据";
    }
  } catch (err) {
    if (id !== reqId) return;
    if (err instanceof ApiError && (err.status === 502 || err.status >= 500)) {
      degraded.value = true;
      status.value = bars.value.length ? "拉取失败，保留上一帧" : "拉取失败";
      return;
    }
    if (err instanceof ApiError && err.status === 400) {
      bars.value = [];
      prevClose.value = null;
      status.value = err.message || "无效标的";
      return;
    }
    degraded.value = true;
    status.value = "K 线拉取失败";
  }
}

watch(
  () => [props.symbol, period.value] as const,
  () => {
    const sym = (props.symbol || "").trim();
    if (!sym) {
      bars.value = [];
      prevClose.value = null;
      status.value = "";
      degraded.value = false;
      return;
    }
    bars.value = [];
    prevClose.value = null;
    degraded.value = false;
    status.value = "加载中…";
    void loadBars();
  },
  { immediate: true },
);

defineExpose({ reload: loadBars });
</script>

<template>
  <div class="chart-panel">
    <header class="chart-panel__head">
      <div class="chart-quote" v-if="symbol">
        <div class="chart-quote__main">
          <h3>{{ title || symbol }}</h3>
          <span v-if="title && title !== symbol" class="muted chart-quote__code">{{ symbol }}</span>
          <span class="chart-quote__last" :class="`is-${quote.dir}`">{{ quote.lastText }}</span>
          <span class="chart-quote__chg" :class="`is-${quote.dir}`">
            {{ quote.changeText }} {{ quote.pctText }}
          </span>
        </div>
        <div class="chart-quote__ohlc muted">
          <span>开 {{ quote.openText }}</span>
          <span>高 {{ quote.highText }}</span>
          <span>低 {{ quote.lowText }}</span>
          <span>收 {{ quote.closeText }}</span>
        </div>
      </div>
      <div v-else>
        <h3>—</h3>
      </div>
      <div class="chart-panel__tabs">
        <span class="muted chart-panel__date">{{ status || dateLabel }}</span>
        <div class="row">
          <button
            type="button"
            class="btn btn--sm"
            :class="period === '1m' ? 'btn--primary' : 'btn--secondary'"
            @click="period = '1m'"
          >
            分时
          </button>
          <button
            type="button"
            class="btn btn--sm"
            :class="period === '1d' ? 'btn--primary' : 'btn--secondary'"
            @click="period = '1d'"
          >
            日K
          </button>
        </div>
      </div>
    </header>
    <p v-if="degraded" class="warn-text" style="margin: 0 0 8px">数据可能陈旧</p>
    <div v-if="!symbol" class="chart-panel__empty muted">点击左侧选股</div>
    <template v-else>
      <div class="chart-legend muted">
        <template v-if="period === '1m'">
          <span class="chart-legend__item"><i class="chart-legend__swatch is-price" />价</span>
          <span v-if="showIntradayAvg" class="chart-legend__item"
            ><i class="chart-legend__swatch is-avg" />均</span
          >
        </template>
        <template v-else>
          <span class="chart-legend__item"><i class="chart-legend__swatch is-ma5" />MA5</span>
          <span class="chart-legend__item"><i class="chart-legend__swatch is-ma10" />MA10</span>
          <span class="chart-legend__item"><i class="chart-legend__swatch is-ma20" />MA20</span>
        </template>
      </div>
      <svg
        class="chart-panel__svg"
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
        role="img"
        :aria-label="`${symbol} ${period}`"
      >
        <template v-if="period === '1m' && intradayModel">
          <line
            v-for="(gy, i) in intradayModel.gridYs"
            :key="'g' + i"
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="gy"
            :y2="gy"
            class="chart-grid"
          />
          <line
            v-if="intradayModel.prevY != null"
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="intradayModel.prevY"
            :y2="intradayModel.prevY"
            class="chart-prev"
          />
          <path
            v-if="showIntradayAvg && intradayModel.avgPath"
            :d="intradayModel.avgPath"
            class="chart-avg"
            fill="none"
          />
          <path
            v-if="intradayModel.pricePath"
            :d="intradayModel.pricePath"
            class="chart-price"
            fill="none"
          />
          <text
            v-for="(lb, i) in intradayModel.priceLabels"
            :key="'pl' + i"
            :x="2"
            :y="lb.y"
            class="chart-axis"
          >
            {{ lb.text }}
          </text>
          <line
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="volTop - gap / 2"
            :y2="volTop - gap / 2"
            class="chart-sep"
          />
          <template v-if="intradayModel.hasVol">
            <rect
              v-for="(v, i) in intradayModel.volBars"
              :key="'v' + i"
              :x="v.x - v.bw / 2"
              :y="v.y"
              :width="v.bw"
              :height="v.h"
              class="chart-vol"
              :class="v.up ? 'is-up' : 'is-down'"
            />
          </template>
          <text
            v-else
            :x="W / 2"
            :y="volTop + volH / 2"
            text-anchor="middle"
            class="chart-empty"
          >
            暂无量
          </text>
          <text
            v-for="(a, i) in intradayModel.axis"
            :key="'a' + i"
            :x="a.x"
            :y="H - 4"
            :text-anchor="i === 0 ? 'start' : i === 2 ? 'end' : 'middle'"
            class="chart-axis"
          >
            {{ a.text }}
          </text>
        </template>
        <template v-else-if="period === '1d' && dailyModel">
          <line
            v-for="(gy, i) in dailyModel.gridYs"
            :key="'dg' + i"
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="gy"
            :y2="gy"
            class="chart-grid"
          />
          <g v-for="(c, i) in dailyModel.candles" :key="'c' + i">
            <line
              :x1="c.x"
              :x2="c.x"
              :y1="c.yHigh"
              :y2="c.yLow"
              class="chart-wick"
              :class="c.up ? 'is-up' : 'is-down'"
            />
            <rect
              :x="c.x - c.bw / 2"
              :y="c.bodyY"
              :width="c.bw"
              :height="c.bodyH"
              class="chart-body"
              :class="c.up ? 'is-up' : 'is-down'"
            />
          </g>
          <path v-if="dailyModel.ma5" :d="dailyModel.ma5" class="chart-ma5" fill="none" />
          <path v-if="dailyModel.ma10" :d="dailyModel.ma10" class="chart-ma10" fill="none" />
          <path v-if="dailyModel.ma20" :d="dailyModel.ma20" class="chart-ma20" fill="none" />
          <text
            v-for="(lb, i) in dailyModel.priceLabels"
            :key="'dpl' + i"
            :x="2"
            :y="lb.y"
            class="chart-axis"
          >
            {{ lb.text }}
          </text>
          <line
            :x1="pad.l"
            :x2="W - pad.r"
            :y1="volTop - gap / 2"
            :y2="volTop - gap / 2"
            class="chart-sep"
          />
          <template v-if="dailyModel.hasVol">
            <rect
              v-for="(v, i) in dailyModel.volBars"
              :key="'dv' + i"
              :x="v.x - v.bw / 2"
              :y="v.y"
              :width="v.bw"
              :height="v.h"
              class="chart-vol"
              :class="v.up ? 'is-up' : 'is-down'"
            />
          </template>
          <text
            v-else
            :x="W / 2"
            :y="volTop + volH / 2"
            text-anchor="middle"
            class="chart-empty"
          >
            暂无量
          </text>
          <text
            v-for="(a, i) in dailyModel.axis"
            :key="'da' + i"
            :x="a.x"
            :y="H - 4"
            :text-anchor="i === 0 ? 'start' : 'end'"
            class="chart-axis"
          >
            {{ a.text }}
          </text>
        </template>
        <text
          v-else
          x="50%"
          y="45%"
          text-anchor="middle"
          class="chart-empty"
        >
          {{ period === "1m" ? "暂无分时" : "暂无日K" }}
        </text>
      </svg>
    </template>
  </div>
</template>
