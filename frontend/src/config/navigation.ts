export type NavIconName =
  | "dashboard"
  | "search"
  | "table"
  | "task"
  | "workflow"
  | "database"
  | "shield"
  | "standards"
  | "quality"
  | "settings";

export type NavItem = {
  name: string;
  label: string;
  icon: NavIconName;
  to?: string;
  desc?: string;
  adminOnly?: boolean;
  browseOnly?: boolean;
  children?: NavItem[];
};

export type NavGroup = {
  section: string;
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    section: "数据平台",
    items: [
      {
        name: "dashboard",
        to: "/",
        label: "概览",
        icon: "dashboard",
        desc: "平台 KPI 与模块入口",
      },
    ],
  },
  {
    section: "数据查询",
    items: [
      {
        name: "data-browser",
        to: "/data-browser",
        label: "数据浏览器",
        icon: "table",
        desc: "证券池 × 多指标宽表截面",
      },
      {
        name: "browse",
        to: "/browse",
        label: "数据查询",
        icon: "search",
        desc: "L3 激活事实表分页查询",
        browseOnly: true,
      },
    ],
  },
  {
    section: "数据采集",
    items: [
      {
        name: "tasks",
        to: "/tasks",
        label: "采集任务",
        icon: "task",
        desc: "catalog 驱动动态类型",
        adminOnly: true,
      },
      {
        name: "workflows",
        to: "/workflows",
        label: "工作流",
        icon: "workflow",
        desc: "DAG 编排与运行",
      },
      {
        name: "sources",
        to: "/sources",
        label: "数据源",
        icon: "database",
        desc: "Tushare / AkShare 配置",
        adminOnly: true,
      },
    ],
  },
  {
    section: "数据治理",
    items: [
      {
        name: "tia",
        to: "/tia",
        label: "提案治理",
        icon: "shield",
        desc: "扫描 · 审批 · L3 激活流水线",
        adminOnly: true,
      },
      {
        name: "standards",
        to: "/standards",
        label: "数据标准",
        icon: "standards",
        desc: "命名规范与 Schema 覆盖",
        adminOnly: true,
      },
      {
        name: "tia-coverage",
        to: "/tia/coverage",
        label: "官网覆盖",
        icon: "shield",
        desc: "本地 catalog 与官方索引对照",
        adminOnly: true,
      },
      {
        name: "quality",
        to: "/quality",
        label: "质量监控",
        icon: "quality",
        desc: "规则引擎与报告",
      },
    ],
  },
  {
    section: "系统管理",
    items: [
      {
        name: "settings",
        to: "/settings",
        label: "平台设置",
        icon: "settings",
        desc: "同步起始日 · 用户管理",
        adminOnly: true,
      },
    ],
  },
];

/** Flatten nav tree for dashboard module cards (leaf items with `to` only). */
export function flattenNavItems(groups: NavGroup[] = NAV_GROUPS): NavItem[] {
  const result: NavItem[] = [];
  for (const group of groups) {
    for (const item of group.items) {
      if (item.children?.length) {
        for (const child of item.children) {
          if (child.to) {
            result.push(child);
          }
        }
      } else if (item.to) {
        result.push(item);
      }
    }
  }
  return result;
}

/** Dashboard module card path — data-browser uses template query. */
export function moduleCardPath(item: NavItem): string {
  if (item.name === "data-browser") {
    return "/data-browser?tpl=wind_ohlc_demo";
  }
  return item.to ?? "/";
}
