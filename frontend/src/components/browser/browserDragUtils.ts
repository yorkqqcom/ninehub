import type { BrowserIndicatorRef } from "@/api/types";
import { INDICATOR_LIMIT } from "./indicatorUtils";

export type IndicatorPick = { id: string; adjust?: string };

export const BROWSER_INDICATOR_GROUP = "browser-indicators";

export const BROWSER_INDICATOR_SOURCE_GROUP = {
  name: BROWSER_INDICATOR_GROUP,
  pull: "clone" as const,
  put: false,
};

export const BROWSER_INDICATOR_TARGET_GROUP = {
  name: BROWSER_INDICATOR_GROUP,
  pull: true,
  put: true,
};

export const BROWSER_INDICATOR_REMOVE_GROUP = {
  name: BROWSER_INDICATOR_GROUP,
  pull: false,
  put: true,
};

export type DragRejectReason = "duplicate" | "limit" | "unavailable" | "not_ready";

export function cloneIndicatorPick(ind: BrowserIndicatorRef): IndicatorPick {
  return {
    id: ind.id,
    adjust: ind.supports_adjust ? "none" : undefined,
  };
}

export function canDragIndicator(
  ind: BrowserIndicatorRef,
  opts: { dataReadyOnly: boolean },
): boolean {
  if (!ind.available) return false;
  if (opts.dataReadyOnly && !ind.data_ready) return false;
  return true;
}

export function indicatorDragDataset(ind: BrowserIndicatorRef): Record<string, string> {
  return { "data-indicator-id": ind.id };
}

export function parseIndicatorIdFromElement(el: HTMLElement): string | null {
  const id = el.dataset.indicatorId;
  if (id) return id;
  const nested = el.querySelector<HTMLElement>("[data-indicator-id]");
  return nested?.dataset.indicatorId ?? null;
}

export function resolveDragRejectMessage(reason: DragRejectReason): string {
  switch (reason) {
    case "duplicate":
      return "指标已在篮中";
    case "limit":
      return `指标数已达上限 ${INDICATOR_LIMIT}`;
    case "unavailable":
      return "该指标未激活，无法添加";
    case "not_ready":
      return "该指标暂无数据";
    default:
      return "无法添加该指标";
  }
}
