<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getApiBase, setApiBase } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const ui = useUiStore();

const apiUrl = ref(getApiBase() || window.location.origin);
const username = ref("admin");
const password = ref("");
const busy = ref(false);
const error = ref("");

onMounted(() => {
  ui.applyTheme();
});

async function submit() {
  if (!apiUrl.value.trim()) {
    error.value = "请填写 API 地址";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await auth.login(apiUrl.value.trim(), username.value.trim(), password.value);
    ui.showMessage("登录成功", "success");
    const redirect = (route.query.redirect as string) || "/";
    router.push(redirect);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-page__toolbar">
      <button type="button" class="btn btn--secondary" @click="ui.toggleTheme()">
        {{ ui.theme === "dark" ? "浅色" : "暗色" }}
      </button>
      <a class="btn btn--secondary" href="/docs" target="_blank" rel="noreferrer">API 文档</a>
    </div>

    <div class="login-shell">
      <div class="login-card">
        <header class="login-brand">
          <div class="login-logo" aria-hidden="true">NH</div>
          <h1>NineHub 数据平台</h1>
          <p class="login-tagline">A 股数据管理 · 采集 · 治理</p>
        </header>

        <form class="login-form" @submit.prevent="submit">
          <label class="login-field">
            <span class="login-label">API 地址</span>
            <input v-model="apiUrl" type="url" class="input-w-full" placeholder="http://127.0.0.1:8888" />
            <span class="login-hint">与 FastAPI 服务同源时可留空使用当前地址</span>
          </label>

          <label class="login-field">
            <span class="login-label">用户名</span>
            <input v-model="username" type="text" autocomplete="username" />
          </label>

          <label class="login-field">
            <span class="login-label">密码</span>
            <input v-model="password" type="password" autocomplete="current-password" />
          </label>

          <p v-if="error" class="login-error" role="alert">{{ error }}</p>

          <button type="submit" class="btn btn--primary login-submit" :disabled="busy">
            {{ busy ? "登录中…" : "登录" }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-submit {
  width: 100%;
  height: 36px;
  margin-top: var(--space-xs);
}
</style>
