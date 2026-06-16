<script setup lang="ts">
import { onMounted } from "vue";
import { RouterView } from "vue-router";
import TopBar from "@/components/TopBar.vue";
import SidebarNav from "@/layouts/SidebarNav.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
onMounted(() => void auth.hydrate());
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <div class="app-body">
      <SidebarNav />
      <main class="app-main">
        <RouterView />
      </main>
    </div>
  </div>
</template>
