import { createRouter, createWebHistory } from "vue-router";
import { getToken } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import WatchShell from "@/layouts/WatchShell.vue";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/pages/LoginPage.vue"),
      meta: { public: true },
    },
    {
      path: "/",
      component: WatchShell,
      children: [
        { path: "", redirect: "/board" },
        { path: "board", name: "board", component: () => import("@/pages/BoardPage.vue") },
        { path: "manage", name: "manage", component: () => import("@/pages/ManagePage.vue") },
        { path: "alerts", name: "alerts", component: () => import("@/pages/AlertsPage.vue") },
        {
          path: "notify",
          name: "notify",
          component: () => import("@/pages/NotifyPage.vue"),
          meta: { adminOnly: true },
        },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.path === "/login" && getToken()) {
      return { path: "/board" };
    }
    return true;
  }
  if (!getToken()) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  if (to.meta.adminOnly) {
    const auth = useAuthStore();
    if (!auth.role) {
      try {
        await auth.hydrateMe();
      } catch {
        return { path: "/login", query: { redirect: to.fullPath } };
      }
    }
    if (!auth.isAdmin) {
      return { path: "/board" };
    }
  }
  return true;
});

export default router;
