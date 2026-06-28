<script setup lang="ts">

import { computed, onMounted, ref } from "vue";

import { useRoute } from "vue-router";

import { apiRequest } from "@/api/client";

import { useAuthStore } from "@/stores/auth";



const route = useRoute();

const auth = useAuthStore();

const hasBrowseTypes = ref(false);



type NavItem = { to: string; label: string; name: string; adminOnly?: boolean };



const navItems = computed(() => {
  const dataItems: NavItem[] = [
    { to: "/data-browser", label: "数据浏览器", name: "data-browser" },
  ];
  if (hasBrowseTypes.value) {
    dataItems.push({ to: "/browse", label: "数据查询", name: "browse" });
  }

  const groups = [
    { section: "九汇平台", items: [{ to: "/", label: "概览", name: "dashboard" }] },
    ...(dataItems.length
      ? [{ section: "数据查询", items: dataItems }]
      : []),
    {
      section: "数据采集",
      items: [
        { to: "/tasks", label: "采集任务", name: "tasks", adminOnly: true },
        { to: "/workflows", label: "工作流", name: "workflows" },
        { to: "/sources", label: "数据源", name: "sources", adminOnly: true },
      ],
    },
    {
      section: "数据治理",
      items: [
        { to: "/tia", label: "提案治理", name: "tia", adminOnly: true },
        { to: "/standards", label: "数据标准", name: "standards", adminOnly: true },
        { to: "/tia/coverage", label: "官网覆盖", name: "tia-coverage", adminOnly: true },
        { to: "/quality", label: "质量监控", name: "quality" },
      ],
    },
    {
      section: "系统管理",
      items: [{ to: "/settings", label: "平台设置", name: "settings", adminOnly: true }],
    },
  ];

  return groups;
});



onMounted(async () => {

  if (!auth.role) {

    try {

      await auth.hydrate();

    } catch {

      return;

    }

  }

  try {

    const data = await apiRequest<{ items: Array<{ browse_enabled: boolean }> }>(

      "/api/v1/catalog/data-types",

    );

    hasBrowseTypes.value = data.items.some((i) => i.browse_enabled);

  } catch {

    hasBrowseTypes.value = false;

  }

});



function visible(item: NavItem) {

  return !item.adminOnly || auth.isAdmin;

}



function isActive(name: string) {
  return route.name === name;
}

</script>



<template>

  <nav class="app-sidebar" aria-label="主导航">

    <template v-for="group in navItems" :key="group.section">

      <div class="app-sidebar__section">{{ group.section }}</div>

      <RouterLink

        v-for="item in group.items"

        :key="item.name"

        v-show="visible(item)"

        :to="item.to"

        class="app-sidebar__link"

        :class="{ active: isActive(item.name) }"

      >

        {{ item.label }}

      </RouterLink>

    </template>

  </nav>

</template>

