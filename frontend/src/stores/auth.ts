import { defineStore } from "pinia";
import { apiRequest, clearToken, getToken, setApiBase, setToken } from "@/api/client";

interface LoginResponse {
  access_token: string;
}

interface MeResponse {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
}

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
    async login(apiBase: string, username: string, password: string) {
      setApiBase(apiBase);
      const data = await apiRequest<LoginResponse>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(data.access_token);
      this.token = data.access_token;
      await this.fetchMe();
    },
    async fetchMe() {
      if (!this.token) return;
      const me = await apiRequest<MeResponse>("/api/v1/auth/me");
      this.username = me.username;
      this.role = me.role;
    },
    logout() {
      clearToken();
      this.token = null;
      this.username = "";
      this.role = "";
    },
    async hydrate() {
      this.token = getToken();
      if (this.token) {
        try {
          await this.fetchMe();
        } catch {
          this.logout();
        }
      }
    },
  },
});
