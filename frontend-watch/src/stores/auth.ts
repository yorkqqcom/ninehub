import { defineStore } from "pinia";
import { apiRequest, clearToken, getToken, setToken } from "@/api/client";

type LoginResp = { access_token: string };
type MeResp = { id: number; username: string; role: string; is_active: boolean };

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: getToken() as string | null,
    username: "" as string,
    role: "" as string,
  }),
  getters: {
    isAuthenticated: (s) => Boolean(s.token),
    isAdmin: (s) => s.role === "admin",
  },
  actions: {
    async login(username: string, password: string) {
      const base = window.location.origin;
      const response = await fetch(`${base}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const text = await response.text();
      const looksHtml =
        text.trim().toLowerCase().startsWith("<!doctype") ||
        text.trim().toLowerCase().startsWith("<html");
      if (looksHtml) {
        throw new Error("登录接口返回了网页。请用 http://127.0.0.1:8888/watch/ 访问盯盘。");
      }
      let data: LoginResp & { detail?: unknown } = { access_token: "" };
      try {
        data = text ? (JSON.parse(text) as LoginResp & { detail?: unknown }) : data;
      } catch {
        throw new Error("登录响应不是合法 JSON");
      }
      if (!response.ok) {
        const detail =
          typeof data?.detail === "string" ? data.detail : "登录失败";
        throw new Error(detail);
      }
      if (!data.access_token) {
        throw new Error("登录响应缺少 access_token");
      }
      setToken(data.access_token);
      this.token = data.access_token;
      this.username = username;
      await this.hydrateMe();
    },
    async hydrateMe() {
      if (!getToken()) {
        this.role = "";
        this.username = "";
        return;
      }
      const me = await apiRequest<MeResp>("/api/v1/auth/me");
      this.username = me.username;
      this.role = me.role;
    },
    logout() {
      clearToken();
      this.token = null;
      this.username = "";
      this.role = "";
    },
    hydrate() {
      this.token = getToken();
    },
  },
});
