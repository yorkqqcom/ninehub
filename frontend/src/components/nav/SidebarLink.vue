<script setup lang="ts">
import NavIcon from "@/components/nav/NavIcon.vue";
import type { NavIconName } from "@/config/navigation";

defineProps<{
  to: string;
  label: string;
  icon: NavIconName;
  active?: boolean;
  sub?: boolean;
  collapsed?: boolean;
}>();
</script>

<template>
  <RouterLink
    :to="to"
    class="app-sidebar__link"
    :class="{
      active,
      'app-sidebar__sublink': sub,
      'app-sidebar__link--collapsed': collapsed,
    }"
    :aria-current="active ? 'page' : undefined"
    :title="collapsed ? label : undefined"
  >
    <NavIcon :name="icon" :active="active" />
    <span v-if="!collapsed" class="app-sidebar__label">{{ label }}</span>
  </RouterLink>
</template>
