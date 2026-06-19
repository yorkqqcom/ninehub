import type { ECharts } from "echarts";

const THEME_PREFIX = "ninehub";
let registeredKey: string | null = null;

function cssVar(name: string, fallback = ""): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function themeKey(mode: "light" | "dark"): string {
  return `${THEME_PREFIX}-${mode}`;
}

export function buildEchartsTheme(): Record<string, unknown> {
  const axis = {
    axisLine: { lineStyle: { color: cssVar("--color-border") } },
    axisTick: { lineStyle: { color: cssVar("--color-border") } },
    axisLabel: { color: cssVar("--color-text-muted") },
    splitLine: { lineStyle: { color: cssVar("--color-border"), opacity: 0.35 } },
  };

  return {
    color: [
      cssVar("--color-primary"),
      cssVar("--color-fall"),
      cssVar("--color-warn-text"),
      cssVar("--color-rise"),
      cssVar("--color-wf-quality"),
      cssVar("--color-info-text"),
    ],
    backgroundColor: "transparent",
    textStyle: { color: cssVar("--color-text") },
    title: {
      textStyle: { color: cssVar("--color-text") },
      subtextStyle: { color: cssVar("--color-text-muted") },
    },
    legend: { textStyle: { color: cssVar("--color-text-secondary") } },
    categoryAxis: axis,
    valueAxis: axis,
    line: { itemStyle: { color: cssVar("--color-primary") } },
    bar: { itemStyle: { color: cssVar("--color-primary") } },
    scatter: { itemStyle: { color: cssVar("--color-primary") } },
    tooltip: {
      backgroundColor: cssVar("--color-surface-elevated"),
      borderColor: cssVar("--color-border"),
      textStyle: { color: cssVar("--color-text") },
    },
  };
}

async function registerTheme(mode: "light" | "dark"): Promise<string> {
  const echarts = await import("echarts");
  const key = themeKey(mode);
  echarts.registerTheme(key, buildEchartsTheme());
  registeredKey = key;
  return key;
}

export async function ensureChartInstance(
  el: HTMLElement,
  existing: ECharts | null,
  mode: "light" | "dark",
): Promise<ECharts> {
  const key = await registerTheme(mode);
  if (existing && !existing.isDisposed()) {
    return existing;
  }
  const echarts = await import("echarts");
  return echarts.init(el, key);
}

export async function disposeAndReinitChart(
  el: HTMLElement | null,
  existing: ECharts | null,
  mode: "light" | "dark",
): Promise<ECharts | null> {
  if (!el) return null;
  existing?.dispose();
  const echarts = await import("echarts");
  const key = await registerTheme(mode);
  registeredKey = key;
  return echarts.init(el, key);
}

export function invalidateEchartsThemeCache(): void {
  registeredKey = null;
}
