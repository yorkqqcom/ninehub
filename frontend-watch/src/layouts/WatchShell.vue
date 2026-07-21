<template>
  <div class="watch-shell">
    <header class="watch-topbar">
      <h1 class="watch-topbar__brand">NineHub 盯盘</h1>
      <div class="watch-topbar__end">
        <button type="button" class="top-bar__btn" @click="ui.toggleTheme()">
          {{ ui.theme === "dark" ? "浅色" : "暗色" }}
        </button>
      </div>
    </header>
    <div class="watch-body">
      <aside class="watch-nav">
        <div class="watch-nav__section">盯盘</div>
        <RouterLink to="/board">看板</RouterLink>
        <RouterLink to="/manage">盯盘管理</RouterLink>
        <RouterLink to="/alerts">告警</RouterLink>
        <RouterLink v-if="auth.isAdmin" to="/notify">Hermes 外发</RouterLink>
        <div class="watch-nav__spacer" />
        <div class="watch-nav__footer">
          <a href="/">返回数据平台</a>
          <button class="btn btn--secondary" type="button" @click="logout">退出</button>
        </div>
      </aside>
      <main class="watch-main">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import { RouterLink, RouterView, useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const router = useRouter();

onMounted(async () => {
  auth.hydrate();
  if (auth.token && !auth.role) {
    try {
      await auth.hydrateMe();
    } catch {
      /* 401 由 apiRequest 跳转登录 */
    }
  }
});

function logout() {
  auth.logout();
  router.push("/login");
}
</script>
