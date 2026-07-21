import { createRouter, createWebHistory } from "vue-router";
import { getToken } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import AppShell from "@/layouts/AppShell.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/pages/LoginPage.vue"),
      meta: { public: true },
    },
    {
      path: "/",
      component: AppShell,
      children: [
        { path: "", name: "dashboard", component: () => import("@/pages/DashboardPage.vue") },
        {
          path: "browse",
          name: "browse",
          component: () => import("@/pages/browse/DataBrowsePage.vue"),
        },
        {
          path: "data-browser",
          name: "data-browser",
          component: () => import("@/pages/browser/DataBrowserPage.vue"),
        },
        {
          path: "backtest",
          name: "backtest",
          component: () => import("@/pages/backtest/BacktestPage.vue"),
          meta: { adminOnly: true },
        },
        {
          path: "tasks",
          name: "tasks",
          component: () => import("@/pages/tasks/TasksPage.vue"),
          meta: { adminOnly: true },
        },
        {
          path: "workflows",
          name: "workflows",
          component: () => import("@/pages/workflows/WorkflowsPage.vue"),
        },
        {
          path: "tia",
          name: "tia",
          component: () => import("@/pages/tia/TiaPage.vue"),
          meta: { adminOnly: true },
          beforeEnter: (to) => {
            const tab = to.query.tab;
            if (tab === "standards") {
              const { tab: _tab, ...rest } = to.query;
              return { name: "standards", query: rest };
            }
            if (tab === "coverage") {
              const { tab: _tab, ...rest } = to.query;
              return { name: "tia-coverage", query: rest };
            }
            if (tab === "builtin" || tab === "proposals") {
              const { tab: _tab, ...rest } = to.query;
              return { name: "tia", query: rest, replace: true };
            }
            return true;
          },
        },
        {
          path: "tia/coverage",
          name: "tia-coverage",
          component: () => import("@/pages/tia/TiaCoveragePage.vue"),
          meta: { adminOnly: true },
        },
        { path: "quality", name: "quality", component: () => import("@/pages/quality/QualityPage.vue") },
        {
          path: "sources",
          name: "sources",
          component: () => import("@/pages/sources/SourcesPage.vue"),
        },
        {
          path: "standards",
          name: "standards",
          component: () => import("@/pages/standards/StandardsPage.vue"),
          meta: { adminOnly: true },
        },
        {
          path: "settings",
          name: "settings",
          component: () => import("@/pages/settings/SettingsPage.vue"),
          meta: { adminOnly: true },
        },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  if (to.meta.public) {
    return true;
  }
  if (!getToken()) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.adminOnly) {
    const auth = useAuthStore();
    if (!auth.role) {
      try {
        await auth.hydrate();
      } catch {
        return { name: "login", query: { redirect: to.fullPath } };
      }
    }
    if (!auth.isAdmin) {
      return { name: "dashboard" };
    }
  }
  return true;
});

export default router;
