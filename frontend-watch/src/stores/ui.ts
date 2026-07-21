import { defineStore } from "pinia";

/** 与数据平台共用 localStorage key，主题切换可跨 SPA 一致。 */
export const useUiStore = defineStore("ui", {
  state: () => ({
    theme: (localStorage.getItem("ninehub.theme") || "dark") as "light" | "dark",
  }),
  actions: {
    applyTheme() {
      document.documentElement.setAttribute("data-theme", this.theme);
      localStorage.setItem("ninehub.theme", this.theme);
    },
    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      this.applyTheme();
    },
  },
});
