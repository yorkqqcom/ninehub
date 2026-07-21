<template>
  <div class="login-page">
    <div class="login-page__toolbar">
      <button type="button" class="btn btn--secondary" @click="ui.toggleTheme()">
        {{ ui.theme === "dark" ? "浅色" : "暗色" }}
      </button>
      <a class="btn btn--secondary" href="/">数据平台</a>
    </div>
    <div class="login-shell">
      <form class="login-card" @submit.prevent="submit">
        <header class="login-brand">
          <div class="login-logo" aria-hidden="true">NH</div>
          <h1>NineHub 盯盘</h1>
          <p class="login-tagline">与数据平台共用账号（ninehub.token）</p>
        </header>
        <div class="login-form">
          <label class="login-field">
            <span class="login-label">用户名</span>
            <input v-model="username" name="username" autocomplete="username" />
          </label>
          <label class="login-field">
            <span class="login-label">密码</span>
            <input
              v-model="password"
              name="password"
              type="password"
              autocomplete="current-password"
            />
          </label>
          <p v-if="error" class="err-text" role="alert">{{ error }}</p>
          <div class="login-actions">
            <button class="btn btn--primary" type="submit" :disabled="loading">
              {{ loading ? "登录中…" : "登录" }}
            </button>
          </div>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const router = useRouter();
const route = useRoute();
const username = ref("admin");
const password = ref("");
const error = ref("");
const loading = ref(false);

onMounted(() => {
  ui.applyTheme();
});

/** Strip Vite base (/watch/) so vue-router paths stay app-relative. */
function normalizeRedirect(raw: string): string {
  const base = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");
  let path = raw || "/board";
  if (base && path.startsWith(base)) {
    path = path.slice(base.length) || "/";
  }
  if (!path.startsWith("/")) path = `/${path}`;
  return path;
}

async function submit(ev: Event) {
  loading.value = true;
  error.value = "";
  try {
    const form = ev.target as HTMLFormElement | null;
    if (form) {
      const fd = new FormData(form);
      const u = String(fd.get("username") || "").trim();
      const p = String(fd.get("password") || "");
      if (u) username.value = u;
      if (p) password.value = p;
    }
    await auth.login(username.value, password.value);
    const redirect =
      typeof route.query.redirect === "string" ? normalizeRedirect(route.query.redirect) : "/board";
    await router.replace(redirect);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "登录失败";
  } finally {
    loading.value = false;
  }
}
</script>
