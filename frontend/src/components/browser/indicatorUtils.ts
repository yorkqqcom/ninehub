import type { BrowserIndicatorRef, BrowserIndicatorTreeNode } from "@/api/types";

export const INDICATOR_LIMIT = 40;

export const FREQ_LABELS: Record<string, string> = {
  static: "静态",
  daily: "日频",
  period: "期频",
};

export function filterTreeByIds(
  nodes: BrowserIndicatorTreeNode[],
  allowed: Set<string>,
): BrowserIndicatorTreeNode[] {
  const out: BrowserIndicatorTreeNode[] = [];
  for (const n of nodes) {
    if (n.node_type === "indicator") {
      if (allowed.has(n.id)) out.push(n);
      continue;
    }
    const children = n.children ? filterTreeByIds(n.children, allowed) : [];
    if (children.length) out.push({ ...n, children });
  }
  return out;
}

export function filterTreeByDataReady(nodes: BrowserIndicatorTreeNode[]): BrowserIndicatorTreeNode[] {
  const out: BrowserIndicatorTreeNode[] = [];
  for (const n of nodes) {
    if (n.node_type === "indicator") {
      if (n.indicator?.data_ready) out.push(n);
      continue;
    }
    const children = n.children ? filterTreeByDataReady(n.children) : [];
    if (children.length) out.push({ ...n, children });
  }
  return out;
}

export function filterTreeByDomain(
  nodes: BrowserIndicatorTreeNode[],
  domain: string,
): BrowserIndicatorTreeNode[] {
  return nodes.filter((n) => n.id === `domain:${domain}`);
}

export function countTreeLeaves(nodes: BrowserIndicatorTreeNode[]): number {
  let n = 0;
  for (const node of nodes) {
    if (node.node_type === "indicator") n += 1;
    else if (node.children?.length) n += countTreeLeaves(node.children);
  }
  return n;
}

export function domainStats(
  flat: BrowserIndicatorRef[],
  domainKey: string,
): { ready: number; total: number } {
  const items = flat.filter((i) => i.domain === domainKey);
  return {
    ready: items.filter((i) => i.available && i.data_ready).length,
    total: items.filter((i) => i.available).length,
  };
}

export function uniqueGroups(flat: BrowserIndicatorRef[], domain: string | null): string[] {
  const groups = new Set<string>();
  for (const i of flat) {
    if (domain && i.domain !== domain) continue;
    if (i.group) groups.add(i.group);
  }
  return [...groups].sort();
}
