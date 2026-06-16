<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getApiBase } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const router = useRouter();
const auth = useAuthStore();
const ui = useUiStore();
const clock = ref("");
const dateStr = ref("");

onMounted(() => {
  ui.applyTheme();
  const tick = () => {
    const now = new Date();
    clock.value = now.toLocaleTimeString("zh-CN", { hour12: false });
    dateStr.value = now.toLocaleDateString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      weekday: "short",
    });
  };
  tick();
  window.setInterval(tick, 1000);
  void checkHealth();
});

async function checkHealth() {
  try {
    const base = getApiBase();
    const res = await fetch(`${base}/health`);
    ui.setHealth(res.ok);
  } catch {
    ui.setHealth(false);
  }
}

function logout() {
  auth.logout();
  router.push({ name: "login" });
}
</script>

<template>
  <header class="top-bar">
    <div class="top-bar__start">
      <h1 class="top-bar__brand">NineHub</h1>
      <span class="top-bar__sep" aria-hidden="true" />
      <div class="top-bar__meta">
        <span class="top-bar__meta-item">A 股数据平台</span>
        <span class="top-bar__meta-item numeric">{{ dateStr }} {{ clock }}</span>
        <span
          class="health-badge"
          :class="ui.healthOk ? 'health-ok' : 'health-bad'"
        >
          {{ ui.healthOk ? "API 在线" : "API 离线" }}
        </span>
      </div>
    </div>
    <div class="top-bar__end">
      <span v-if="auth.username" class="top-bar__user">
        {{ auth.username }}
        <span v-if="auth.isAdmin" class="top-bar__role">管理员</span>
      </span>
      <button type="button" class="top-bar__btn" @click="ui.toggleTheme()">
        {{ ui.theme === "dark" ? "浅色" : "暗色" }}
      </button>
      <a class="top-bar__btn" href="/docs" target="_blank" rel="noreferrer">API</a>
      <button type="button" class="top-bar__btn" @click="logout">退出</button>
    </div>
  </header>
</template>
